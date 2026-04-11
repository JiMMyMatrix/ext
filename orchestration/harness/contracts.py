from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from orchestration.harness.paths import load_json, resolve_paths

REQUEST_DRAFT_REQUIRED = {
	"intake_ref",
	"shell_state",
	"raw_request_ref",
	"draft_summary",
	"normalized_goal",
	"constraints",
	"clarification_history",
}
REQUEST_DRAFT_ALLOWED = REQUEST_DRAFT_REQUIRED | {
	"clarification_request",
	"lane_hint",
	"task_hint",
}
ACCEPTED_REQUIRED = {
	"intake_ref",
	"raw_request_ref",
	"request_draft_ref",
	"accepted_at",
	"accepted_summary",
	"goal",
	"constraints",
	"lane",
}
ACCEPTED_ALLOWED = ACCEPTED_REQUIRED | {"branch", "task"}
FORBIDDEN_OVERREACH_KEYS = {
	"request_ref",
	"request_path",
	"dispatch_ref",
	"result_ref",
	"review_ref",
	"governor_decision_ref",
	"transition",
	"transition_ref",
	"proposed_transition",
	"interrupt_reason",
	"merge_ready",
	"actor_launch",
	"actor_launch_intent",
	"child_work",
	"review_routing",
	"integration_intent",
	"work_intent",
}


def _require_keys(payload: dict[str, Any], required: set[str], label: str) -> None:
	missing = sorted(required - set(payload))
	if missing:
		raise ValueError(f"{label} missing required keys: {', '.join(missing)}")


def _reject_extra_keys(payload: dict[str, Any], allowed: set[str], label: str) -> None:
	extra = sorted(set(payload) - allowed)
	if extra:
		raise ValueError(f"{label} has unsupported keys: {', '.join(extra)}")


def validate_request_draft(payload: dict[str, Any], *, require_ready: bool = False) -> None:
	_require_keys(payload, REQUEST_DRAFT_REQUIRED, "request_draft.json")
	_reject_extra_keys(payload, REQUEST_DRAFT_ALLOWED, "request_draft.json")

	forbidden = sorted(set(payload) & FORBIDDEN_OVERREACH_KEYS)
	if forbidden:
		raise ValueError(
			"request_draft.json contains workflow-authority keys: " + ", ".join(forbidden)
		)

	if payload["shell_state"] not in {"clarification_needed", "ready_for_acceptance"}:
		raise ValueError("request_draft.json shell_state is invalid")
	if not isinstance(payload["constraints"], list):
		raise ValueError("request_draft.json constraints must be a list")
	if not isinstance(payload["clarification_history"], list):
		raise ValueError("request_draft.json clarification_history must be a list")
	if require_ready and payload["shell_state"] != "ready_for_acceptance":
		raise ValueError("request_draft.json must be ready_for_acceptance before acceptance")


def validate_accepted_intake(payload: dict[str, Any]) -> None:
	_require_keys(payload, ACCEPTED_REQUIRED, "accepted_intake.json")
	_reject_extra_keys(payload, ACCEPTED_ALLOWED, "accepted_intake.json")
	forbidden = sorted(set(payload) & FORBIDDEN_OVERREACH_KEYS)
	if forbidden:
		raise ValueError(
			"accepted_intake.json contains workflow-authority keys: " + ", ".join(forbidden)
		)
	if not isinstance(payload["constraints"], list):
		raise ValueError("accepted_intake.json constraints must be a list")


def build_intake_validator_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Validate intake artifacts")
	subparsers = parser.add_subparsers(dest="command", required=True)

	draft_parser = subparsers.add_parser("draft")
	draft_parser.add_argument("--path")
	draft_parser.add_argument("--intake-ref")
	draft_parser.add_argument("--require-ready", action="store_true")

	accepted_parser = subparsers.add_parser("accepted")
	accepted_parser.add_argument("--path")
	accepted_parser.add_argument("--intake-ref")
	return parser


def _resolve_intake_artifact_path(
	command: str,
	*,
	path: str | None,
	intake_ref: str | None,
	repo_root: str | Path | None = None,
) -> Path:
	if path:
		return Path(path)
	if not intake_ref:
		raise ValueError(f"{command} requires --path or --intake-ref")
	intake_dir = resolve_paths(repo_root).intakes_root / intake_ref
	if command == "draft":
		return intake_dir / "request_draft.json"
	return intake_dir / "accepted_intake.json"


def validate_intake_command(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	parser = build_intake_validator_parser()
	args = parser.parse_args(argv)

	try:
		path = _resolve_intake_artifact_path(
			args.command,
			path=args.path,
			intake_ref=getattr(args, "intake_ref", None),
			repo_root=repo_root,
		)
		payload = load_json(path)
		if args.command == "draft":
			validate_request_draft(payload, require_ready=args.require_ready)
		else:
			validate_accepted_intake(payload)
	except (FileNotFoundError, ValueError) as exc:
		raise SystemExit(str(exc))

	print(json.dumps({"ok": True, "path": str(path)}, indent=2, sort_keys=True))
	return 0


def run_dispatch_validator(argv: list[str]) -> int:
	from orchestration.harness import dispatch_contracts

	return dispatch_contracts.main(argv)
