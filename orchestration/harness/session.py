from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from orchestration.harness.intake import (
	accept_intake,
	answer_intake_clarification,
	raw_request_path,
	request_draft_path,
	start_intake,
)
from orchestration.harness.paths import (
	default_lane,
	git_branch_name,
	load_json,
	repo_relative,
	resolve_paths,
	summarize,
	trim_text,
	utc_now,
	write_json,
)


def _next_id(prefix: str) -> str:
	return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _feed_item(
	item_type: str,
	title: str,
	body: str | None,
	*,
	authoritative: bool,
	now: str,
	details: list[str] | None = None,
	activity: dict[str, Any] | None = None,
) -> dict[str, Any]:
	payload: dict[str, Any] = {
		"id": _next_id(item_type),
		"type": item_type,
		"timestamp": now,
		"title": title,
		"authoritative": authoritative,
	}
	if body is not None:
		payload["body"] = body
	if details:
		payload["details"] = details
	if activity:
		payload["activity"] = activity
	return payload


def _artifact(path: str, *, summary: str | None, authoritative: bool, status: str) -> dict[str, Any]:
	return {
		"id": _next_id("artifact"),
		"label": Path(path).name,
		"path": path,
		"status": status,
		"summary": summary,
		"authoritative": authoritative,
	}


def _artifact_feed_item(artifact: dict[str, Any], now: str) -> dict[str, Any]:
	return {
		"id": _next_id("artifact_reference"),
		"type": "artifact_reference",
		"timestamp": now,
		"title": artifact["label"],
		"body": artifact.get("summary"),
		"authoritative": artifact["authoritative"],
		"artifact": artifact,
		"activity": {
			"kind": "artifact",
			"state": "completed",
			"path": artifact["path"],
			"summary": artifact.get("status"),
		},
	}


def _request_card(title: str, body: str, now: str) -> dict[str, Any]:
	return {"id": _next_id("request"), "title": title, "body": body, "requestedAt": now}


def _initial_model(now: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	branch = git_branch_name(repo_root)
	return {
		"snapshot": {
			"lane": None,
			"branch": branch,
			"task": None,
			"currentActor": "intake_shell",
			"currentStage": "idle",
			"transportState": "connected",
			"pendingApproval": None,
			"pendingInterrupt": None,
			"recentArtifacts": [],
			"snapshotFreshness": {"receivedAt": now},
		},
		"feed": [
			_feed_item(
				"system_status",
				"Ready when you are",
				"Ask Codex to work on this repo.",
				authoritative=True,
				now=now,
			)
		],
		"activeClarification": None,
		"acceptedIntakeSummary": None,
	}


def load_session(repo_root: str | Path | None = None) -> dict[str, Any]:
	now = utc_now()
	session_path = resolve_paths(repo_root).ui_session_path
	payload = load_json(session_path, default=None)
	if payload is None:
		return {"model": _initial_model(now, repo_root=repo_root), "meta": {"activeIntakeRef": None}}
	return payload


def save_session(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	write_json(resolve_paths(repo_root).ui_session_path, session)


def _refresh_snapshot(model: dict[str, Any], now: str, **overrides: Any) -> None:
	model["snapshot"].update(overrides)
	model["snapshot"]["snapshotFreshness"] = {"receivedAt": now}


def public_model(session: dict[str, Any]) -> dict[str, Any]:
	return session["model"]


def _append_error(model: dict[str, Any], title: str, body: str, now: str) -> None:
	model["feed"].append(
		_feed_item("error", title, body, authoritative=True, now=now)
	)
	_refresh_snapshot(model, now)


def handle_submit_prompt(session: dict[str, Any], text: str, *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	model = session["model"]
	prompt = trim_text(text)
	if not prompt:
		_append_error(model, "Prompt required", "Enter a prompt before sending it.", now)
		return

	envelope = start_intake(prompt, repo_root=repo_root)
	session["meta"]["activeIntakeRef"] = envelope["intake_ref"]

	model["feed"].append(
		_feed_item("user_message", "Prompt submitted", prompt, authoritative=False, now=now)
	)
	model["feed"].append(
		_feed_item(
			"shell_event",
			"Intake shell normalized the request",
			envelope["draft_summary"],
			authoritative=False,
			now=now,
			details=[
				"Request drafts are informational only.",
				"Intake acceptance remains orchestration-owned.",
			],
			activity={"kind": "status", "state": "completed", "summary": "Draft updated"},
		)
	)
	model["acceptedIntakeSummary"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["recentArtifacts"] = []
	model["snapshot"]["task"] = envelope.get("task_hint") or summarize(prompt, 60)
	model["snapshot"]["branch"] = model["snapshot"].get("branch") or git_branch_name(repo_root)

	if envelope["shell_state"] == "clarification_needed":
		clarification = envelope["clarification_request"]
		model["activeClarification"] = clarification
		model["snapshot"]["pendingApproval"] = None
		model["feed"].append(
			_feed_item(
				"clarification_request",
				clarification["title"],
				clarification["body"],
				authoritative=True,
				now=now,
			)
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="intake_shell",
			currentStage="clarification_needed",
			transportState="connected",
		)
		return

	model["activeClarification"] = None
	model["snapshot"]["pendingApproval"] = _request_card(
		"Accept intake",
		"Approve this accepted intake draft so orchestration can continue.",
		now,
	)
	model["feed"].append(
		_feed_item(
			"approval_request",
			"Accept intake",
			"Orchestration is waiting for approval before canonical acceptance.",
			authoritative=True,
			now=now,
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="ready_for_acceptance",
		transportState="connected",
	)


def handle_answer_clarification(
	session: dict[str, Any],
	text: str,
	*,
	repo_root: str | Path | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	intake_ref = session["meta"].get("activeIntakeRef")
	if not intake_ref or not model.get("activeClarification"):
		_append_error(
			model,
			"No clarification is active",
			"There is no active clarification request to answer.",
			now,
		)
		return

	answer = trim_text(text)
	if not answer:
		_append_error(
			model,
			"Clarification answer required",
			"Enter a clarification answer before sending it.",
			now,
		)
		return

	envelope = answer_intake_clarification(intake_ref, answer, repo_root=repo_root)
	model["feed"].append(
		_feed_item("user_message", "Clarification answered", answer, authoritative=False, now=now)
	)
	model["feed"].append(
		_feed_item(
			"shell_event",
			"Draft is ready for acceptance",
			"Intake updated the draft and handed it back for orchestration acceptance.",
			authoritative=False,
			now=now,
			activity={"kind": "status", "state": "completed", "summary": "Ready for acceptance"},
		)
	)
	model["feed"].append(
		_feed_item(
			"approval_request",
			"Accept intake",
			"Orchestration is waiting for approval before canonical acceptance.",
			authoritative=True,
			now=now,
		)
	)
	model["activeClarification"] = None
	model["snapshot"]["pendingApproval"] = _request_card(
		"Accept intake",
		"Approve this accepted intake draft so orchestration can continue.",
		now,
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage=envelope["shell_state"],
		transportState="connected",
	)


def handle_approve(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	model = session["model"]
	intake_ref = session["meta"].get("activeIntakeRef")
	pending_approval = model["snapshot"].get("pendingApproval")
	if not intake_ref or not pending_approval:
		_append_error(model, "No approval is active", "There is no approval to apply.", now)
		return

	branch = model["snapshot"].get("branch") or git_branch_name(repo_root)
	lane = model["snapshot"].get("lane") or default_lane(branch)
	task = model["snapshot"].get("task")
	envelope = accept_intake(intake_ref, lane=lane, branch=branch, task=task, repo_root=repo_root)

	artifacts = [
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
			envelope["accepted_intake_ref"],
			summary="Canonical accepted intake for downstream governor consumption.",
			authoritative=True,
			status="accepted",
		),
	]

	model["acceptedIntakeSummary"] = {
		"title": "Accepted intake summary",
		"body": envelope["accepted_summary"],
	}
	model["snapshot"]["pendingApproval"] = None
	model["snapshot"]["lane"] = envelope["lane"]
	model["snapshot"]["branch"] = envelope["branch"]
	model["snapshot"]["task"] = envelope["task"]
	model["snapshot"]["recentArtifacts"] = artifacts
	model["feed"].append(
		_feed_item(
			"system_status",
			"Intake accepted",
			envelope["accepted_summary"],
			authoritative=True,
			now=now,
		)
	)
	for artifact in artifacts:
		model["feed"].append(_artifact_feed_item(artifact, now))
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="intake_accepted",
		transportState="connected",
	)


def handle_decline_or_hold(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	model = session["model"]
	if not model["snapshot"].get("pendingApproval"):
		_append_error(model, "Nothing to hold", "There is no approval request to hold.", now)
		return

	model["snapshot"]["pendingApproval"] = None
	model["feed"].append(
		_feed_item(
			"system_status",
			"Intake placed on hold",
			"Approval was declined or deferred. No canonical intake was written.",
			authoritative=True,
			now=now,
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="on_hold",
		transportState="connected",
	)


def handle_interrupt(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	model = session["model"]
	model["snapshot"]["pendingInterrupt"] = _request_card(
		"Interrupt requested",
		"Interrupt has been requested and is waiting for orchestration handling.",
		now,
	)
	model["feed"].append(
		_feed_item(
			"interrupt_request",
			"Interrupt requested",
			"Interrupt has been requested and is waiting for orchestration handling.",
			authoritative=True,
			now=now,
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="interrupt_requested",
		transportState="connected",
	)


def handle_reconnect(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	model = session["model"]
	model["feed"].append(
		_feed_item(
			"system_status",
			"Reconnected",
			"Reloaded the latest orchestration-backed session snapshot.",
			authoritative=True,
			now=now,
		)
	)
	_refresh_snapshot(model, now, transportState="connected")


def dispatch_session_action(
	command: str,
	*,
	text: str | None = None,
	repo_root: str | Path | None = None,
) -> dict[str, Any]:
	session = load_session(repo_root)
	if command == "submit_prompt":
		handle_submit_prompt(session, text or "", repo_root=repo_root)
	elif command == "answer_clarification":
		handle_answer_clarification(session, text or "", repo_root=repo_root)
	elif command == "approve":
		handle_approve(session, repo_root=repo_root)
	elif command == "decline_or_hold":
		handle_decline_or_hold(session, repo_root=repo_root)
	elif command == "interrupt_run":
		handle_interrupt(session, repo_root=repo_root)
	elif command == "reconnect":
		handle_reconnect(session, repo_root=repo_root)
	elif command != "state":
		raise ValueError(f"unsupported session command: {command}")

	save_session(session, repo_root=repo_root)
	return public_model(session)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="UI session bridge for orchestration-backed extension state")
	subparsers = parser.add_subparsers(dest="command", required=True)

	subparsers.add_parser("state")

	submit = subparsers.add_parser("submit_prompt")
	submit.add_argument("--text", required=True)

	answer = subparsers.add_parser("answer_clarification")
	answer.add_argument("--text", required=True)

	subparsers.add_parser("approve")
	subparsers.add_parser("decline_or_hold")
	subparsers.add_parser("interrupt_run")
	subparsers.add_parser("reconnect")
	return parser


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	args = build_parser().parse_args(argv)
	try:
		model = dispatch_session_action(
			args.command,
			text=getattr(args, "text", None),
			repo_root=repo_root,
		)
	except ValueError as exc:
		raise SystemExit(str(exc))
	print(json.dumps(model, indent=2, sort_keys=True))
	return 0
