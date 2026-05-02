#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness import session  # noqa: E402
from orchestration.harness.intake import (  # noqa: E402
	accept_intake,
	answer_intake_clarification,
	raw_request_path,
	request_draft_path,
	start_intake,
)
from orchestration.harness.paths import (  # noqa: E402
	default_lane,
	git_branch_name,
	repo_relative,
	resolve_paths,
	utc_now,
)


DEFAULT_PROMPT = "Analyze the repository."
DEFAULT_CLARIFICATION = "Focus on architecture, structure, and subsystem boundaries."


def _artifact(path: str, *, summary: str, authoritative: bool, status: str) -> dict[str, Any]:
	return session._artifact(  # noqa: SLF001 - this is a dev fixture script for the session model.
		path,
		summary=summary,
		authoritative=authoritative,
		status=status,
	)


def _accepted_artifacts(intake_ref: str, accepted_ref: str, repo_root: Path) -> list[dict[str, Any]]:
	return [
		_artifact(
			repo_relative(raw_request_path(intake_ref, repo_root=repo_root), repo_root),
			summary="Canonical raw human input.",
			authoritative=True,
			status="recorded",
		),
		_artifact(
			repo_relative(request_draft_path(intake_ref, repo_root=repo_root), repo_root),
			summary="Intake shell draft. Informational only.",
			authoritative=False,
			status="draft",
		),
		_artifact(
			accepted_ref,
			summary="Canonical accepted intake for downstream governor consumption.",
			authoritative=True,
			status="accepted",
		),
	]


def seed_plan_ready_session(
	repo_root: Path,
	*,
	prompt: str = DEFAULT_PROMPT,
	clarification: str = DEFAULT_CLARIFICATION,
) -> dict[str, Any]:
	now = utc_now()
	paths = resolve_paths(repo_root)
	paths.orchestration_state_root.mkdir(parents=True, exist_ok=True)

	intake = start_intake(prompt, normalized_text=prompt, repo_root=repo_root)
	answer_intake_clarification(
		intake["intake_ref"],
		clarification,
		normalized_text=clarification,
		repo_root=repo_root,
	)
	branch = git_branch_name(repo_root)
	lane = default_lane(branch)
	accepted = accept_intake(
		intake["intake_ref"],
		lane=lane,
		branch=branch,
		task="Analyze the repository.",
		repo_root=repo_root,
	)

	payload = session.load_session(repo_root)
	model = payload["model"]
	foreground_request_id = "corgi-fixture:executor-plan"
	accepted_summary = accepted["accepted_summary"]
	accepted_ref = accepted["accepted_intake_ref"]

	model["acceptedIntakeSummary"] = {
		"title": "Accepted intake summary",
		"body": accepted_summary,
	}
	model["activeClarification"] = None
	model["activeForegroundRequestId"] = None
	model["planVersion"] = 1
	model["snapshot"].update(
		{
			"lane": accepted["lane"],
			"branch": accepted["branch"],
			"task": accepted["task"],
			"currentActor": "governor",
			"currentStage": "plan_ready",
			"permissionScope": "plan",
			"runState": "idle",
			"transportState": "connected",
			"pendingPermissionRequest": None,
			"pendingInterrupt": None,
			"recentArtifacts": _accepted_artifacts(intake["intake_ref"], accepted_ref, repo_root),
			"snapshotFreshness": {"receivedAt": now},
		}
	)
	model["feed"] = [
		session._feed_item(  # noqa: SLF001
			"system_status",
			"Ready when you are",
			"Executor fixture loaded. Use the Plan-ready actions to test execution without Governor startup.",
			authoritative=True,
			now=now,
		),
		session._feed_item(  # noqa: SLF001
			"user_message",
			"Prompt submitted",
			prompt.lower(),
			authoritative=False,
			now=now,
			source_layer="dialog_controller",
			source_actor="human",
			turn_type="governed_work_intent",
			in_response_to_request_id=foreground_request_id,
		),
		session._feed_item(  # noqa: SLF001
			"user_message",
			"Clarification answered",
			clarification,
			authoritative=False,
			now=now,
			source_layer="dialog_controller",
			source_actor="human",
			turn_type="clarification_reply",
			in_response_to_request_id="corgi-fixture:clarification",
		),
		session._feed_item(  # noqa: SLF001
			"actor_event",
			"Governor response",
			(
				"Objective: analyze the repository architecture and subsystem boundaries. "
				"Proposed steps: start from the accepted intake and runtime authority docs, "
				"then inspect extension/orchestration seams. Likely files/areas: "
				"`src/executionWindowPanel.ts`, `src/executionTransport.ts`, "
				"`src/phase1Model.ts`, `orchestration/harness/session.py`, and "
				"`orchestration/contracts/ux.md`. Risks or unknowns: runtime docs and "
				"code may drift. Execution readiness: plan-ready fixture for Executor-only testing."
			),
			authoritative=True,
			now=now,
			source_layer="governor",
			source_actor="governor",
			source_artifact_ref=accepted_ref,
			turn_type="permission_action",
			in_response_to_request_id=foreground_request_id,
		),
	]
	session._set_plan_ready_request(  # noqa: SLF001
		model,
		now,
		foreground_request_id=foreground_request_id,
		advance_version=False,
	)
	payload["meta"]["activeIntakeRef"] = intake["intake_ref"]
	payload["meta"].setdefault("processedRequestIds", {})
	session.save_session(payload, repo_root=repo_root)
	return payload


def seed_execute_permission_session(repo_root: Path) -> dict[str, Any]:
	# Compatibility alias: the old Execute permission card was merged into the
	# Plan-ready "Execute plan" action, so the executor fixture now starts at the
	# checkpoint that can launch execution directly.
	return seed_plan_ready_session(repo_root)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Seed a dev/test Corgi session for modular Executor testing."
	)
	parser.add_argument(
		"--scenario",
		choices=["plan-ready", "execute-permission"],
		default="execute-permission",
		help=(
			"plan-ready starts at the plan checkpoint; execute-permission is a "
			"compatibility alias for the same checkpoint."
		),
	)
	parser.add_argument("--root", default=".", help="Repository root to seed.")
	return parser


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	repo_root = Path(args.root).resolve()
	if args.scenario == "plan-ready":
		seed_plan_ready_session(repo_root)
	else:
		seed_execute_permission_session(repo_root)
	print(f"Seeded Corgi test session: {args.scenario}")
	print(f"  session: {resolve_paths(repo_root).ui_session_path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
