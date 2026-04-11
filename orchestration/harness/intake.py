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


def intake_dir(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).intakes_root / intake_ref


def raw_request_path(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return intake_dir(intake_ref, repo_root=repo_root) / "raw_human_request.md"


def request_draft_path(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return intake_dir(intake_ref, repo_root=repo_root) / "request_draft.json"


def accepted_intake_path(intake_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return intake_dir(intake_ref, repo_root=repo_root) / "accepted_intake.json"


def _build_initial_draft(prompt: str, intake_ref: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	now = utc_now()
	constraints = constraint_hints_from_text(prompt)
	needs_clarification = len(constraints) == 0

	return {
		"intake_ref": intake_ref,
		"shell_state": "clarification_needed" if needs_clarification else "ready_for_acceptance",
		"raw_request_ref": repo_relative(raw_request_path(intake_ref, repo_root=repo_root), repo_root),
		"draft_summary": summarize(prompt, 96),
		"normalized_goal": trim_text(prompt),
		"constraints": constraints,
		"clarification_history": [],
		"clarification_request": (
			{
				"id": f"clarification-{intake_ref}",
				"title": CLARIFICATION_TITLE,
				"body": CLARIFICATION_BODY,
				"placeholder": CLARIFICATION_PLACEHOLDER,
				"requestedAt": now,
			}
			if needs_clarification
			else None
		),
		"lane_hint": None,
		"task_hint": summarize(prompt, 60),
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


def start_intake(prompt: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	normalized = trim_text(prompt)
	if not normalized:
		raise ValueError("prompt text is required")

	intake_ref = next_intake_ref(normalized)
	write_text(raw_request_path(intake_ref, repo_root=repo_root), normalized + "\n")
	draft = _build_initial_draft(normalized, intake_ref, repo_root=repo_root)
	write_json(request_draft_path(intake_ref, repo_root=repo_root), draft)
	return _envelope_from_draft(draft, repo_root=repo_root)


def answer_intake_clarification(
	intake_ref: str,
	answer: str,
	*,
	repo_root: str | Path | None = None,
) -> dict[str, Any]:
	draft = load_json(request_draft_path(intake_ref, repo_root=repo_root))
	normalized = trim_text(answer)
	if not normalized:
		raise ValueError("clarification answer is required")

	current_request = draft.get("clarification_request")
	if not current_request:
		raise ValueError("no clarification request is active")

	history = list(draft.get("clarification_history", []))
	history.append(
		{
			"question": current_request["body"],
			"askedAt": current_request["requestedAt"],
			"answer": normalized,
			"answeredAt": utc_now(),
		}
	)

	constraints = unique_strings(
		list(draft.get("constraints", [])) + constraint_hints_from_text(normalized) + [normalized]
	)
	draft["constraints"] = constraints
	draft["clarification_history"] = history
	draft["clarification_request"] = None
	draft["shell_state"] = "ready_for_acceptance"
	draft["draft_summary"] = summarize(
		f"{draft['normalized_goal']} Constraint: {normalized}",
		96,
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
