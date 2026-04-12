from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from orchestration.harness.intake import (
	accept_intake,
	accepted_intake_path,
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
from orchestration.harness.transition import load_transition


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
	source_layer: str | None = None,
	source_actor: str | None = None,
	source_artifact_ref: str | None = None,
	turn_type: str | None = None,
) -> dict[str, Any]:
	default_provenance = _default_feed_provenance(item_type)
	payload: dict[str, Any] = {
		"id": _next_id(item_type),
		"type": item_type,
		"timestamp": now,
		"title": title,
		"authoritative": authoritative,
		"source_layer": source_layer or default_provenance["source_layer"],
		"source_actor": source_actor or default_provenance["source_actor"],
		"turn_type": turn_type or default_provenance["turn_type"],
	}
	if body is not None:
		payload["body"] = body
	if details:
		payload["details"] = details
	if activity:
		payload["activity"] = activity
	if source_artifact_ref:
		payload["source_artifact_ref"] = source_artifact_ref
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
		"source_layer": "orchestration",
		"source_actor": "orchestration",
		"source_artifact_ref": artifact["path"],
		"turn_type": "system",
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


def _default_feed_provenance(item_type: str) -> dict[str, str]:
	if item_type == "user_message":
		return {
			"source_layer": "dialog_controller",
			"source_actor": "human",
			"turn_type": "system",
		}
	if item_type in {"shell_event", "clarification_request"}:
		return {
			"source_layer": "intake",
			"source_actor": "intake_shell",
			"turn_type": "system",
		}
	if item_type == "actor_event":
		return {
			"source_layer": "governor",
			"source_actor": "governor",
			"turn_type": "governor_dialogue",
		}
	return {
		"source_layer": "orchestration",
		"source_actor": "orchestration",
		"turn_type": "system",
	}


def _classify_turn(prompt: str) -> str:
	lower = prompt.lower()
	dialogue_tokens = (
		"progress",
		"status",
		"where are we",
		"what are you doing",
		"what is the current",
		"what's the current",
		"why",
		"explain",
		"help me understand",
		"what do you think",
		"should we",
		"which option",
		"compare",
	)
	if any(token in lower for token in dialogue_tokens):
		return "governor_dialogue"
	return "governed_work_intent"


def _load_request_draft_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	intake_ref = session["meta"].get("activeIntakeRef")
	if not isinstance(intake_ref, str) or not intake_ref:
		return None, None
	draft_path = request_draft_path(intake_ref, repo_root=repo_root)
	if not draft_path.exists():
		return None, None
	return load_json(draft_path), repo_relative(draft_path, repo_root)


def _load_accepted_intake_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	intake_ref = session["meta"].get("activeIntakeRef")
	if not isinstance(intake_ref, str) or not intake_ref:
		return None, None
	accepted_path = accepted_intake_path(intake_ref, repo_root=repo_root)
	if not accepted_path.exists():
		return None, None
	return load_json(accepted_path), repo_relative(accepted_path, repo_root)


def _latest_dispatch_summary(
	lane: str | None, *, repo_root: str | Path | None = None
) -> dict[str, Any] | None:
	if not isinstance(lane, str) or not lane.strip():
		return None

	queue_root = resolve_paths(repo_root).agent_root / "dispatches"
	if not queue_root.exists():
		return None

	best: tuple[float, dict[str, Any]] | None = None
	for state_path in queue_root.rglob("state.json"):
		dispatch_dir = state_path.parent
		request_path = dispatch_dir / "request.json"
		if not request_path.exists():
			continue
		try:
			request = load_json(request_path)
			state = load_json(state_path)
		except Exception:
			continue
		if request.get("lane") != lane:
			continue

		result_path = dispatch_dir / "result.json"
		decision_path = dispatch_dir / "governor_decision.json"
		result = load_json(result_path) if result_path.exists() else None
		decision = load_json(decision_path) if decision_path.exists() else None
		mtime = max(
			path.stat().st_mtime
			for path in [request_path, state_path, result_path, decision_path]
			if path.exists()
		)
		payload = {
			"dispatch_ref": request.get("dispatch_ref"),
			"objective": request.get("objective"),
			"state_status": state.get("status"),
			"state_ref": repo_relative(state_path, repo_root),
			"request_ref": repo_relative(request_path, repo_root),
			"result_status": result.get("status") if isinstance(result, dict) else None,
			"result_blocker": result.get("blocker") if isinstance(result, dict) else None,
			"result_ref": repo_relative(result_path, repo_root) if result_path.exists() else None,
			"decision": decision.get("decision") if isinstance(decision, dict) else None,
			"decision_reason": decision.get("reason") if isinstance(decision, dict) else None,
			"decision_ref": repo_relative(decision_path, repo_root) if decision_path.exists() else None,
		}
		if best is None or mtime > best[0]:
			best = (mtime, payload)

	return best[1] if best else None


def _transition_summary(lane: str | None, *, repo_root: str | Path | None = None) -> dict[str, Any] | None:
	if not isinstance(lane, str) or not lane.strip():
		return None
	try:
		payload = load_transition(resolve_paths(repo_root).repo_root, lane)
	except SystemExit:
		return None
	if not isinstance(payload, dict):
		return None
	return {
		"transition": payload.get("transition"),
		"requested_stop_reason": payload.get("requested_stop_reason"),
		"next_action_kind": (payload.get("next_action") or {}).get("kind")
		if isinstance(payload.get("next_action"), dict)
		else None,
		"next_action_ref": (payload.get("next_action") or {}).get("ref")
		if isinstance(payload.get("next_action"), dict)
		else None,
		"ref": repo_relative(
			resolve_paths(repo_root).repo_root / ".agent" / "governor" / lane / "proposed_transition.json",
			repo_root,
		),
	}


def _build_governor_dialogue(
	session: dict[str, Any], prompt: str, *, repo_root: str | Path | None = None
) -> tuple[str, list[str], str | None]:
	model = session["model"]
	snapshot = model["snapshot"]
	task = snapshot.get("task")
	stage = snapshot.get("currentStage") or "idle"
	actor = snapshot.get("currentActor") or "orchestration"
	lane = snapshot.get("lane")
	request_draft, request_draft_ref = _load_request_draft_summary(session, repo_root=repo_root)
	accepted_intake, accepted_intake_ref = _load_accepted_intake_summary(session, repo_root=repo_root)
	dispatch_summary = _latest_dispatch_summary(lane, repo_root=repo_root)
	transition_summary = _transition_summary(lane, repo_root=repo_root)
	primary_ref = (
		(dispatch_summary or {}).get("decision_ref")
		or (dispatch_summary or {}).get("result_ref")
		or (dispatch_summary or {}).get("state_ref")
		or accepted_intake_ref
		or request_draft_ref
		or (transition_summary or {}).get("ref")
	)

	if model.get("activeClarification"):
		body = (
			"Current progress: intake is waiting on one clarification before the request can continue. "
			"Answer the clarification or choose one of the suggested options to move forward."
		)
	elif snapshot.get("pendingApproval"):
		body = (
			"Current progress: orchestration is waiting for explicit acceptance before the request can move into Governor-led work. "
			"Use Approve or Full access when you want that request to continue."
		)
	elif dispatch_summary:
		body = (
			f"Current progress: the latest dispatch is {dispatch_summary['dispatch_ref']} "
			f"with state {dispatch_summary.get('state_status') or 'unknown'}."
		)
		if dispatch_summary.get("result_status"):
			body += f" Result status is {dispatch_summary['result_status']}."
		if dispatch_summary.get("decision"):
			body += f" Governor decision is {dispatch_summary['decision']}."
	elif accepted_intake:
		body = (
			f"Current progress: the accepted intake is bound to {accepted_intake.get('lane') or lane or 'the current lane'} "
			f"for {accepted_intake.get('task') or accepted_intake.get('goal') or task or 'the current task'}."
		)
	elif request_draft:
		body = (
			f"Current progress: intake has a draft for {request_draft.get('task_hint') or request_draft.get('normalized_goal') or task or 'the current request'}, "
			f"and it is currently {request_draft.get('shell_state') or stage}."
		)
	elif snapshot.get("runState") == "running":
		body = (
			f"Current progress: Governor-led work is running{f' for {task}' if task else ''}. "
			"Stop is available if you need to interrupt the current run."
		)
	elif model.get("acceptedIntakeSummary"):
		body = (
			f"The latest accepted intake is {task or 'ready'}, and the session is currently idle. "
			"Send a new governed request when you want the workflow to move again."
		)
	else:
		body = (
			"No governed work is active yet. Send a bounded request when you want to start, "
			"or ask a progress or idea question like this one anytime."
		)

	details = [
		f"Prompt: {summarize(prompt, 72)}",
		f"Current actor: {actor}",
		f"Current stage: {stage}",
	]
	if task:
		details.append(f"Current task: {task}")
	if request_draft_ref and request_draft:
		details.append(f"Request draft: {request_draft_ref} ({request_draft.get('shell_state')})")
	if accepted_intake_ref and accepted_intake:
		details.append(
			f"Accepted intake: {accepted_intake_ref} (lane={accepted_intake.get('lane')}, task={accepted_intake.get('task') or accepted_intake.get('goal')})"
		)
	if dispatch_summary:
		details.append(
			f"Latest dispatch: {dispatch_summary.get('dispatch_ref')} status={dispatch_summary.get('state_status')} ({dispatch_summary.get('state_ref')})"
		)
		if dispatch_summary.get("result_status") and dispatch_summary.get("result_ref"):
			details.append(
				f"Latest result: status={dispatch_summary['result_status']} ({dispatch_summary['result_ref']})"
			)
		if dispatch_summary.get("decision") and dispatch_summary.get("decision_ref"):
			details.append(
				f"Latest governor decision: {dispatch_summary['decision']} ({dispatch_summary['decision_ref']})"
			)
	if transition_summary:
		details.append(
			f"Proposed transition: {transition_summary.get('transition')} ({transition_summary.get('ref')})"
		)
		if transition_summary.get("next_action_kind"):
			details.append(
				f"Next internal action: {transition_summary['next_action_kind']} -> {transition_summary.get('next_action_ref') or 'none'}"
			)
	return body, details, primary_ref


def _initial_model(now: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	branch = git_branch_name(repo_root)
	return {
		"snapshot": {
			"lane": None,
			"branch": branch,
			"task": None,
			"currentActor": "intake_shell",
			"currentStage": "idle",
			"accessMode": "approval_required",
			"runState": "idle",
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
				"Ask Corgi to work on this repo.",
				authoritative=True,
				now=now,
			)
		],
		"activeClarification": None,
		"acceptedIntakeSummary": None,
	}


def _normalize_session(session: dict[str, Any], now: str, *, repo_root: str | Path | None = None) -> None:
	session.setdefault("meta", {})
	session["meta"].setdefault("activeIntakeRef", None)
	model = session.setdefault("model", _initial_model(now, repo_root=repo_root))
	snapshot = model.setdefault("snapshot", {})
	snapshot.setdefault("lane", None)
	snapshot.setdefault("branch", git_branch_name(repo_root))
	snapshot.setdefault("task", None)
	snapshot.setdefault("currentActor", "intake_shell")
	snapshot.setdefault("currentStage", "idle")
	snapshot.setdefault("accessMode", "approval_required")
	snapshot.setdefault("runState", "idle")
	snapshot.setdefault("transportState", "connected")
	snapshot.setdefault("pendingApproval", None)
	snapshot.setdefault("pendingInterrupt", None)
	snapshot.setdefault("recentArtifacts", [])
	snapshot.setdefault("snapshotFreshness", {"receivedAt": now})
	model.setdefault("feed", [])
	model.setdefault("activeClarification", None)
	model.setdefault("acceptedIntakeSummary", None)


def load_session(repo_root: str | Path | None = None) -> dict[str, Any]:
	now = utc_now()
	session_path = resolve_paths(repo_root).ui_session_path
	payload = load_json(session_path, default=None)
	if payload is None:
		return {"model": _initial_model(now, repo_root=repo_root), "meta": {"activeIntakeRef": None}}
	_normalize_session(payload, now, repo_root=repo_root)
	return payload


def save_session(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	write_json(resolve_paths(repo_root).ui_session_path, session)


def _refresh_snapshot(model: dict[str, Any], now: str, **overrides: Any) -> None:
	model["snapshot"].update(overrides)
	model["snapshot"]["snapshotFreshness"] = {"receivedAt": now}


def public_model(session: dict[str, Any]) -> dict[str, Any]:
	return session["model"]


def _current_access_mode(model: dict[str, Any]) -> str:
	return model["snapshot"].get("accessMode") or "approval_required"


def _append_error(model: dict[str, Any], title: str, body: str, now: str) -> None:
	model["feed"].append(
		_feed_item("error", title, body, authoritative=True, now=now)
	)
	_refresh_snapshot(model, now)


def _supersede_pending_approval(model: dict[str, Any], now: str) -> None:
	pending = model["snapshot"].get("pendingApproval")
	if not pending:
		return
	model["snapshot"]["pendingApproval"] = None
	model["feed"].append(
		_feed_item(
			"system_status",
			"Pending approval superseded",
			"A new request replaced the previous approval checkpoint.",
			authoritative=True,
			now=now,
		)
	)


def _accept_pending_intake(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	enable_full_access: bool = False,
	turn_type: str = "system",
) -> bool:
	model = session["model"]
	intake_ref = session["meta"].get("activeIntakeRef")
	pending_approval = model["snapshot"].get("pendingApproval")
	if not intake_ref or not pending_approval:
		_append_error(model, "No approval is active", "There is no approval to apply.", now)
		return False

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

	access_mode = "full_access" if enable_full_access else _current_access_mode(model)
	summary = envelope["accepted_summary"]
	if access_mode == "full_access":
		summary = f"{summary} Full access is enabled for this session."

	model["acceptedIntakeSummary"] = {
		"title": "Accepted intake summary",
		"body": summary,
	}
	model["snapshot"]["pendingApproval"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["lane"] = envelope["lane"]
	model["snapshot"]["branch"] = envelope["branch"]
	model["snapshot"]["task"] = envelope["task"]
	model["snapshot"]["recentArtifacts"] = artifacts
	model["snapshot"]["accessMode"] = access_mode
	model["feed"].append(
		_feed_item(
			"system_status",
			"Full access enabled" if access_mode == "full_access" else "Intake accepted",
			summary,
			authoritative=True,
			now=now,
			turn_type=turn_type,
		)
	)
	for artifact in artifacts:
		model["feed"].append(_artifact_feed_item(artifact, now))
	_refresh_snapshot(
		model,
		now,
		currentActor="governor" if access_mode == "full_access" else "orchestration",
		currentStage="running" if access_mode == "full_access" else "intake_accepted",
		runState="running" if access_mode == "full_access" else "idle",
		transportState="connected",
	)
	return True


def handle_submit_prompt(session: dict[str, Any], text: str, *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	model = session["model"]
	prompt = trim_text(text)
	if not prompt:
		_append_error(model, "Prompt required", "Enter a prompt before sending it.", now)
		return

	turn_type = _classify_turn(prompt)
	if turn_type == "governor_dialogue":
		body, details, primary_ref = _build_governor_dialogue(
			session,
			prompt,
			repo_root=repo_root,
		)
		model["feed"].append(
			_feed_item(
				"user_message",
				"Governor question",
				prompt,
				authoritative=False,
				now=now,
				turn_type=turn_type,
			)
		)
		model["feed"].append(
			_feed_item(
				"actor_event",
				"Governor response",
				body,
				authoritative=True,
				now=now,
				details=details,
				source_layer="governor",
				source_actor="governor",
				source_artifact_ref=primary_ref,
				turn_type=turn_type,
			)
		)
		_refresh_snapshot(model, now, transportState="connected")
		return

	_supersede_pending_approval(model, now)
	envelope = start_intake(prompt, repo_root=repo_root)
	session["meta"]["activeIntakeRef"] = envelope["intake_ref"]

	model["feed"].append(
		_feed_item(
			"user_message",
			"Prompt submitted",
			prompt,
			authoritative=False,
			now=now,
			turn_type=turn_type,
		)
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
			turn_type=turn_type,
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
				turn_type=turn_type,
			)
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="intake_shell",
			currentStage="clarification_needed",
			runState="idle",
			transportState="connected",
		)
		return

	model["activeClarification"] = None
	if _current_access_mode(model) == "full_access":
		model["snapshot"]["pendingApproval"] = _request_card(
			"Accept intake",
			"Approve this accepted intake draft or grant full access so orchestration can continue.",
			now,
		)
		_accept_pending_intake(
			session,
			now,
			repo_root=repo_root,
			turn_type=turn_type,
		)
		return

	model["snapshot"]["pendingApproval"] = _request_card(
		"Accept intake",
		"Approve this accepted intake draft or grant full access so orchestration can continue.",
		now,
	)
	model["feed"].append(
		_feed_item(
			"approval_request",
			"Accept intake",
			"Orchestration is waiting for approval or full access before canonical acceptance.",
			authoritative=True,
			now=now,
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="ready_for_acceptance",
		runState="idle",
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
		_feed_item(
			"user_message",
			"Clarification answered",
			answer,
			authoritative=False,
			now=now,
			turn_type="clarification_reply",
		)
	)
	model["feed"].append(
		_feed_item(
			"shell_event",
			"Draft is ready for acceptance",
			"Intake updated the draft and handed it back for orchestration acceptance.",
			authoritative=False,
			now=now,
			activity={"kind": "status", "state": "completed", "summary": "Ready for acceptance"},
			turn_type="clarification_reply",
		)
	)
	model["activeClarification"] = None
	model["snapshot"]["pendingApproval"] = _request_card(
		"Accept intake",
		"Approve this accepted intake draft or grant full access so orchestration can continue.",
		now,
	)
	if _current_access_mode(model) == "full_access":
		_accept_pending_intake(
			session,
			now,
			repo_root=repo_root,
			turn_type="clarification_reply",
		)
		return
	model["feed"].append(
		_feed_item(
			"approval_request",
			"Accept intake",
			"Orchestration is waiting for approval or full access before canonical acceptance.",
			authoritative=True,
			now=now,
			turn_type="clarification_reply",
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage=envelope["shell_state"],
		runState="idle",
		transportState="connected",
	)


def handle_approve(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	_accept_pending_intake(session, now, repo_root=repo_root, turn_type="approval_action")


def handle_full_access(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	_accept_pending_intake(
		session,
		now,
		repo_root=repo_root,
		enable_full_access=True,
		turn_type="approval_action",
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
		runState="idle",
		transportState="connected",
	)


def handle_interrupt(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	now = utc_now()
	model = session["model"]
	if model["snapshot"].get("runState") != "running":
		_append_error(
			model,
			"Nothing is running",
			"Stop is only available while governed work is actively running.",
			now,
		)
		return
	if model["snapshot"].get("pendingInterrupt"):
		_append_error(
			model,
			"Stop already requested",
			"A stop request is already waiting for orchestration handling.",
			now,
		)
		return
	model["snapshot"]["pendingInterrupt"] = _request_card(
		"Stop requested",
		"Stop has been requested and is waiting for orchestration handling.",
		now,
	)
	model["feed"].append(
		_feed_item(
			"interrupt_request",
			"Stop requested",
			"Stop has been requested and is waiting for orchestration handling.",
			authoritative=True,
			now=now,
			turn_type="stop_action",
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="interrupt_requested",
		runState="running",
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
	elif command == "full_access":
		handle_full_access(session, repo_root=repo_root)
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
	subparsers.add_parser("full_access")
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
