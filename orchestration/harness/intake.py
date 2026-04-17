from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from orchestration.harness.contracts import (
	validate_accepted_intake,
	validate_intake_command,
	validate_request_draft,
)
from orchestration.harness.paths import (
	constraint_hints_from_text,
	load_json,
	next_intake_ref,
	repo_relative,
	resolve_paths,
	summarize,
	trim_text,
	unique_strings,
	utc_now,
	write_json,
	write_text,
)

CLARIFICATION_TITLE = "Clarification required"
CLARIFICATION_BODY = (
	"Name one non-negotiable constraint or visible surface this work must keep."
)
CLARIFICATION_PLACEHOLDER = (
	"Example: Keep the composer compact and preserve inline artifact actions."
)


def _sentence(text: str) -> str:
	normalized = trim_text(text).rstrip(".!?")
	if not normalized:
		return ""
	return normalized[0].upper() + normalized[1:] + "."


def _humanize_draft_summary(goal: str, constraint: str) -> str:
	goal_sentence = _sentence(goal)
	normalized_constraint = trim_text(constraint).rstrip(".!?")
	if not goal_sentence:
		return summarize(_sentence(normalized_constraint), 96)
	if not normalized_constraint:
		return summarize(goal_sentence, 96)

	lower = normalized_constraint.lower()
	if lower.startswith(
		(
			"focus on ",
			"keep ",
			"preserve ",
			"avoid ",
			"use ",
			"include ",
			"highlight ",
			"compare ",
			"cover ",
		)
	):
		body = f"{goal_sentence} {normalized_constraint}."
	else:
		body = f"{goal_sentence} Keep in mind: {normalized_constraint}."
	return summarize(body, 96)


def _clarification_request_for_prompt(prompt: str, intake_ref: str) -> dict[str, Any]:
	now = utc_now()
	lower = prompt.lower()

	if any(token in lower for token in ("analyze", "analyse", "review", "inspect", "explore")) and any(
		token in lower for token in ("folder", "repo", "repository", "project", "codebase", "directory")
	):
		return {
			"id": f"clarification-{intake_ref}",
			"title": CLARIFICATION_TITLE,
			"body": "What kind of analysis do you want for this folder?",
			"placeholder": "Optional: add a short detail if none of these fit exactly.",
			"requestedAt": now,
			"kind": "analysis_focus",
			"options": [
				{
					"id": "analysis-architecture",
					"label": "Architecture",
					"answer": "Focus on architecture, structure, and subsystem boundaries.",
					"description": "Look at structure, boundaries, and responsibilities.",
				},
				{
					"id": "analysis-risks",
					"label": "Bugs and risks",
					"answer": "Focus on bugs, regressions, and architectural risks.",
					"description": "Look for concrete risks and likely failures.",
				},
				{
					"id": "analysis-plan",
					"label": "Implementation plan",
					"answer": "Focus on implementation opportunities and the next practical plan.",
					"description": "Turn the folder analysis into an actionable next-step plan.",
				},
			],
			"allowFreeText": True,
		}

	if any(token in lower for token in ("build", "implement", "change", "refactor", "update", "fix")):
		return {
			"id": f"clarification-{intake_ref}",
			"title": CLARIFICATION_TITLE,
			"body": "What should this change preserve while I work?",
			"placeholder": CLARIFICATION_PLACEHOLDER,
			"requestedAt": now,
			"kind": "implementation_guardrail",
			"options": [
				{
					"id": "guardrail-scope",
					"label": "Keep scope minimal",
					"answer": "Keep the scope minimal and avoid broad side effects.",
					"description": "Prefer the smallest safe change.",
				},
				{
					"id": "guardrail-ui",
					"label": "Preserve visible UX",
					"answer": "Preserve the current visible UX and control flow unless I ask for a redesign.",
					"description": "Avoid changing the human-facing interaction model.",
				},
				{
					"id": "guardrail-artifacts",
					"label": "Preserve artifact flow",
					"answer": "Preserve the current artifact and orchestration flow while making the change.",
					"description": "Keep current orchestration and artifact behavior intact.",
				},
			],
			"allowFreeText": True,
		}

	return {
		"id": f"clarification-{intake_ref}",
		"title": CLARIFICATION_TITLE,
		"body": CLARIFICATION_BODY,
		"placeholder": CLARIFICATION_PLACEHOLDER,
		"requestedAt": now,
		"kind": "constraint",
		"options": None,
		"allowFreeText": True,
	}


def intake_dir(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).intakes_root / intake_ref


def raw_request_path(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return intake_dir(intake_ref, repo_root=repo_root) / "raw_human_request.md"


def request_draft_path(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return intake_dir(intake_ref, repo_root=repo_root) / "request_draft.json"


def accepted_intake_path(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return intake_dir(intake_ref, repo_root=repo_root) / "accepted_intake.json"


def _build_initial_draft(
	normalized_text: str, intake_ref: str, *, repo_root: str | Path | None = None
) -> dict[str, Any]:
	constraints = constraint_hints_from_text(normalized_text)
	needs_clarification = len(constraints) == 0

	return {
		"intake_ref": intake_ref,
		"shell_state": "clarification_needed" if needs_clarification else "ready_for_acceptance",
		"raw_request_ref": repo_relative(raw_request_path(intake_ref, repo_root=repo_root), repo_root),
		"draft_summary": summarize(normalized_text, 96),
		"normalized_goal": trim_text(normalized_text),
		"constraints": constraints,
		"clarification_history": [],
		"clarification_request": _clarification_request_for_prompt(normalized_text, intake_ref)
		if needs_clarification
		else None,
		"lane_hint": None,
		"task_hint": summarize(normalized_text, 60),
	}


def _envelope_from_draft(draft: dict[str, Any], *, repo_root: str | Path | None = None) -> dict[str, Any]:
	return {
		"intake_ref": draft["intake_ref"],
		"shell_state": draft["shell_state"],
		"raw_request_ref": draft["raw_request_ref"],
		"request_draft_ref": repo_relative(
			request_draft_path(draft["intake_ref"], repo_root=repo_root),
			repo_root,
		),
		"draft_summary": draft["draft_summary"],
		"normalized_goal": draft["normalized_goal"],
		"constraints": draft["constraints"],
		"clarification_request": draft.get("clarification_request"),
		"lane_hint": draft.get("lane_hint"),
		"task_hint": draft.get("task_hint"),
	}


def start_intake(
	prompt: str,
	*,
	normalized_text: str | None = None,
	repo_root: str | Path | None = None,
) -> dict[str, Any]:
	raw_prompt = trim_text(prompt)
	if not raw_prompt:
		raise ValueError("prompt text is required")

	semantic_prompt = trim_text(normalized_text) or raw_prompt
	intake_ref = next_intake_ref(raw_prompt)
	write_text(raw_request_path(intake_ref, repo_root=repo_root), raw_prompt + "\n")
	draft = _build_initial_draft(semantic_prompt, intake_ref, repo_root=repo_root)
	write_json(request_draft_path(intake_ref, repo_root=repo_root), draft)
	return _envelope_from_draft(draft, repo_root=repo_root)


def answer_intake_clarification(
	intake_ref: str,
	answer: str,
	*,
	normalized_text: str | None = None,
	repo_root: str | Path | None = None,
) -> dict[str, Any]:
	draft = load_json(request_draft_path(intake_ref, repo_root=repo_root))
	raw_answer = trim_text(answer)
	if not raw_answer:
		raise ValueError("clarification answer is required")
	semantic_answer = trim_text(normalized_text) or raw_answer

	current_request = draft.get("clarification_request")
	if not current_request:
		raise ValueError("no clarification request is active")

	history = list(draft.get("clarification_history", []))
	history.append(
		{
			"question": current_request["body"],
			"askedAt": current_request["requestedAt"],
			"answer": semantic_answer,
			"answeredAt": utc_now(),
		}
	)

	constraints = unique_strings(
		list(draft.get("constraints", []))
		+ constraint_hints_from_text(semantic_answer)
		+ [semantic_answer]
	)
	draft["constraints"] = constraints
	draft["clarification_history"] = history
	draft["clarification_request"] = None
	draft["shell_state"] = "ready_for_acceptance"
	draft["draft_summary"] = _humanize_draft_summary(
		draft["normalized_goal"], semantic_answer
	)
	write_json(request_draft_path(intake_ref, repo_root=repo_root), draft)
	return _envelope_from_draft(draft, repo_root=repo_root)


def accept_intake(
	intake_ref: str,
	*,
	lane: str,
	branch: str | None = None,
	task: str | None = None,
	repo_root: str | Path | None = None,
) -> dict[str, Any]:
	draft = json.loads(
		request_draft_path(intake_ref, repo_root=repo_root).read_text(encoding="utf-8")
	)
	validate_request_draft(draft, require_ready=True)

	accepted = {
		"intake_ref": intake_ref,
		"raw_request_ref": draft["raw_request_ref"],
		"request_draft_ref": repo_relative(
			request_draft_path(intake_ref, repo_root=repo_root),
			repo_root,
		),
		"accepted_at": utc_now(),
		"accepted_summary": draft["draft_summary"],
		"goal": draft["normalized_goal"],
		"constraints": draft["constraints"],
		"lane": trim_text(lane),
		"branch": trim_text(branch) if branch else None,
		"task": trim_text(task) if task else draft.get("task_hint"),
	}
	validate_accepted_intake(accepted)
	write_json(accepted_intake_path(intake_ref, repo_root=repo_root), accepted)
	return {
		"intake_ref": intake_ref,
		"accepted_intake_ref": repo_relative(
			accepted_intake_path(intake_ref, repo_root=repo_root),
			repo_root,
		),
		"accepted_summary": accepted["accepted_summary"],
		"goal": accepted["goal"],
		"constraints": accepted["constraints"],
		"lane": accepted["lane"],
		"branch": accepted["branch"],
		"task": accepted["task"],
	}


def build_shell_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Repo-local intake shell")
	subparsers = parser.add_subparsers(dest="command", required=True)

	start_parser = subparsers.add_parser("start")
	start_parser.add_argument("--text", required=True)

	answer_parser = subparsers.add_parser("answer")
	answer_parser.add_argument("--intake-ref", required=True)
	answer_parser.add_argument("--text", required=True)
	return parser


def shell_main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	parser = build_shell_parser()
	args = parser.parse_args(argv)

	try:
		if args.command == "start":
			payload = start_intake(args.text, repo_root=repo_root)
		else:
			payload = answer_intake_clarification(
				args.intake_ref,
				args.text,
				repo_root=repo_root,
			)
	except (FileNotFoundError, ValueError) as exc:
		raise SystemExit(str(exc))

	print(json.dumps(payload, indent=2, sort_keys=True))
	return 0


def build_accept_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Accept an intake draft into canonical intake")
	parser.add_argument("--intake-ref", required=True)
	parser.add_argument("--lane", required=True)
	parser.add_argument("--branch")
	parser.add_argument("--task")
	return parser


def accept_main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	args = build_accept_parser().parse_args(argv)
	try:
		payload = accept_intake(
			args.intake_ref,
			lane=args.lane,
			branch=args.branch,
			task=args.task,
			repo_root=repo_root,
		)
	except (FileNotFoundError, ValueError) as exc:
		raise SystemExit(str(exc))

	print(json.dumps(payload, indent=2, sort_keys=True))
	return 0


def validate_main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	return validate_intake_command(argv, repo_root=repo_root)
