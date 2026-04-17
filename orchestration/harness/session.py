from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime
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
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	in_response_to_request_id: str | None = None,
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
	if semantic_input_version:
		payload["semantic_input_version"] = semantic_input_version
	if semantic_summary_ref:
		payload["semantic_summary_ref"] = semantic_summary_ref
	if semantic_context_flags is not None:
		payload["semantic_context_flags"] = semantic_context_flags
	if semantic_route_type:
		payload["semantic_route_type"] = semantic_route_type
	if semantic_confidence:
		payload["semantic_confidence"] = semantic_confidence
	if semantic_block_reason:
		payload["semantic_block_reason"] = semantic_block_reason
	if semantic_paraphrase:
		payload["semantic_paraphrase"] = semantic_paraphrase
	if semantic_normalized_text:
		payload["semantic_normalized_text"] = semantic_normalized_text
	if in_response_to_request_id:
		payload["in_response_to_request_id"] = in_response_to_request_id
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


def _artifact_feed_item(
	artifact: dict[str, Any], now: str, *, in_response_to_request_id: str | None = None
) -> dict[str, Any]:
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
		"in_response_to_request_id": in_response_to_request_id,
		"artifact": artifact,
		"activity": {
			"kind": "artifact",
			"state": "completed",
			"path": artifact["path"],
			"summary": artifact.get("status"),
		},
	}


def _request_card(title: str, body: str, now: str) -> dict[str, Any]:
	request_id = _next_id("request")
	return {
		"id": request_id,
		"contextRef": request_id,
		"title": title,
		"body": body,
		"requestedAt": now,
	}


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
		"what happened",
		"what happen",
		"what's happening",
		"what is happening",
		"what's going on",
		"what is going on",
		"how is it going",
		"how's it going",
		"any update",
		"update me",
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
			"Current progress: one clarification is still open. "
			"Answer it or choose one of the suggested options to keep moving."
		)
	elif snapshot.get("pendingPermissionRequest"):
		body = (
			f"Current progress: this request is ready, but it is waiting for a {snapshot['pendingPermissionRequest'].get('recommendedScope') or 'plan'} permission choice before Corgi can continue."
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
			f"Current progress: Corgi is actively working{f' on {task}' if task else ''}. "
			"Stop is available if you need it."
		)
	elif model.get("acceptedIntakeSummary"):
		body = (
			f"The latest accepted intake is {task or 'ready'}, and the session is currently idle. "
			"Send a new governed request when you want the workflow to move again."
		)
	else:
		body = (
			"Nothing is running right now. Start with a bounded request, "
			"or ask a progress question anytime."
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
			"sessionRef": _next_id("session"),
			"lane": None,
			"branch": branch,
			"task": None,
			"currentActor": "intake_shell",
			"currentStage": "idle",
			"permissionScope": "unset",
			"runState": "idle",
			"transportState": "connected",
			"pendingPermissionRequest": None,
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
	session["meta"].setdefault("processedRequestIds", {})
	model = session.setdefault("model", _initial_model(now, repo_root=repo_root))
	snapshot = model.setdefault("snapshot", {})
	snapshot.setdefault("sessionRef", _next_id("session"))
	snapshot.setdefault("lane", None)
	snapshot.setdefault("branch", git_branch_name(repo_root))
	snapshot.setdefault("task", None)
	snapshot.setdefault("currentActor", "intake_shell")
	snapshot.setdefault("currentStage", "idle")
	if "permissionScope" not in snapshot:
		legacy_access_mode = snapshot.get("accessMode")
		snapshot["permissionScope"] = (
			"execute" if legacy_access_mode == "full_access" else "unset"
		)
	snapshot.setdefault("runState", "idle")
	snapshot.setdefault("transportState", "connected")
	if "pendingPermissionRequest" not in snapshot:
		legacy_pending = snapshot.get("pendingApproval")
		if isinstance(legacy_pending, dict):
			snapshot["pendingPermissionRequest"] = {
				**legacy_pending,
				"recommendedScope": "plan",
				"allowedScopes": ["observe", "plan", "execute"],
			}
		else:
			snapshot["pendingPermissionRequest"] = None
	snapshot.setdefault("pendingInterrupt", None)
	snapshot.setdefault("recentArtifacts", [])
	snapshot.setdefault("snapshotFreshness", {"receivedAt": now})
	model.setdefault("feed", [])
	model.setdefault("activeClarification", None)
	model.setdefault("acceptedIntakeSummary", None)
	if isinstance(model.get("activeClarification"), dict):
		model["activeClarification"].setdefault(
			"contextRef", model["activeClarification"].get("id")
		)
	if isinstance(snapshot.get("pendingPermissionRequest"), dict):
		snapshot["pendingPermissionRequest"].setdefault(
			"contextRef", snapshot["pendingPermissionRequest"].get("id")
		)
		snapshot["pendingPermissionRequest"].setdefault("recommendedScope", "plan")
		snapshot["pendingPermissionRequest"].setdefault(
			"allowedScopes", ["observe", "plan", "execute"]
		)
	if isinstance(snapshot.get("pendingInterrupt"), dict):
		snapshot["pendingInterrupt"].setdefault(
			"contextRef",
			f"interrupt:{snapshot['snapshotFreshness'].get('receivedAt', now)}",
		)


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


def _semantic_provenance(
	*,
	turn_type: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	in_response_to_request_id: str | None = None,
) -> dict[str, Any]:
	return {
		"turn_type": turn_type,
		"semantic_input_version": semantic_input_version,
		"semantic_summary_ref": semantic_summary_ref,
		"semantic_context_flags": semantic_context_flags,
		"semantic_route_type": semantic_route_type,
		"semantic_confidence": semantic_confidence,
		"semantic_block_reason": semantic_block_reason,
		"semantic_paraphrase": semantic_paraphrase,
		"semantic_normalized_text": semantic_normalized_text,
		"in_response_to_request_id": in_response_to_request_id,
	}


def _append_user_turn(
	model: dict[str, Any],
	now: str,
	*,
	title: str,
	body: str,
	turn_type: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	in_response_to_request_id: str | None = None,
) -> None:
	model["feed"].append(
		_feed_item(
			"user_message",
			title,
			body,
			authoritative=False,
			now=now,
			**_semantic_provenance(
				turn_type=turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=semantic_paraphrase,
				semantic_normalized_text=semantic_normalized_text,
				in_response_to_request_id=in_response_to_request_id,
			),
		)
	)


def _current_permission_scope(model: dict[str, Any]) -> str:
	return model["snapshot"].get("permissionScope") or "unset"


def _append_error(
	model: dict[str, Any],
	title: str,
	body: str,
	now: str,
	*,
	in_response_to_request_id: str | None = None,
) -> None:
	model["feed"].append(
		_feed_item(
			"error",
			title,
			body,
			authoritative=True,
			now=now,
			in_response_to_request_id=in_response_to_request_id,
		)
	)
	_refresh_snapshot(model, now)


def _processed_request_ids(session: dict[str, Any]) -> dict[str, Any]:
	meta = session.setdefault("meta", {})
	processed = meta.setdefault("processedRequestIds", {})
	if isinstance(processed, dict):
		return processed
	meta["processedRequestIds"] = {}
	return meta["processedRequestIds"]


def _is_duplicate_request(session: dict[str, Any], request_id: str | None) -> bool:
	if not request_id:
		return False
	return request_id in _processed_request_ids(session)


def _remember_request(session: dict[str, Any], request_id: str | None, command: str, now: str) -> None:
	if not request_id:
		return
	_processed_request_ids(session)[request_id] = {"command": command, "handledAt": now}


def _parse_received_at(value: str | None) -> datetime | None:
	if not value:
		return None
	try:
		return datetime.fromisoformat(value.replace("Z", "+00:00"))
	except ValueError:
		return None


def _is_snapshot_stale(snapshot: dict[str, Any], now: str) -> bool:
	freshness = snapshot.get("snapshotFreshness") or {}
	if freshness.get("stale") is True:
		return True
	received_at = _parse_received_at(freshness.get("receivedAt"))
	current = _parse_received_at(now)
	if received_at is None or current is None:
		return False
	return (current - received_at).total_seconds() > 45


def _current_interrupt_context_ref(model: dict[str, Any]) -> str:
	return f"interrupt:{model['snapshot']['snapshotFreshness'].get('receivedAt') or utc_now()}"


def _context_matches(expected_context_ref: str | None, provided_context_ref: str | None) -> bool:
	if expected_context_ref is None:
		return True
	return provided_context_ref == expected_context_ref


def _session_ref_matches(model: dict[str, Any], provided_session_ref: str | None) -> bool:
	expected = model["snapshot"].get("sessionRef")
	if not expected:
		return True
	return provided_session_ref == expected


def _permission_rank(scope: str | None) -> int:
	if scope == "observe":
		return 1
	if scope == "plan":
		return 2
	if scope == "execute":
		return 3
	return 0


def _scope_satisfies(current_scope: str | None, required_scope: str | None) -> bool:
	return _permission_rank(current_scope) >= _permission_rank(required_scope)


def _permission_request(recommended_scope: str, now: str) -> dict[str, Any]:
	request_id = _next_id("permission")
	return {
		"id": request_id,
		"contextRef": request_id,
		"title": "Permission needed",
		"body": f"Choose {recommended_scope} if you want Corgi to continue this request.",
		"recommendedScope": recommended_scope,
		"allowedScopes": ["observe", "plan", "execute"],
		"requestedAt": now,
	}


def _recommended_permission_scope(prompt: str) -> str:
	lower = prompt.lower().strip()
	if any(
		lower == token or lower.startswith(f"{token} ")
		for token in (
			"implement",
			"build",
			"create",
			"refactor",
			"fix",
			"debug",
			"update",
			"change",
			"write",
		)
	):
		return "execute"
	return "plan"


def _supersede_pending_permission_request(
	model: dict[str, Any], now: str, *, request_id: str | None = None
) -> None:
	pending = model["snapshot"].get("pendingPermissionRequest")
	if not pending:
		return
	model["snapshot"]["pendingPermissionRequest"] = None
	model["feed"].append(
		_feed_item(
			"system_status",
			"Pending permission request superseded",
			"A new request replaced the previous permission checkpoint.",
			authoritative=True,
			now=now,
			in_response_to_request_id=request_id,
		)
	)


def _accept_pending_intake(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	permission_scope: str,
	request_id: str | None = None,
	turn_type: str = "system",
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
) -> bool:
	model = session["model"]
	intake_ref = session["meta"].get("activeIntakeRef")
	pending_permission = model["snapshot"].get("pendingPermissionRequest")
	if not intake_ref or not pending_permission:
		_append_error(
			model,
			"No permission request is active",
			"There is no permission request to apply.",
			now,
			in_response_to_request_id=request_id,
		)
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

	summary = envelope["accepted_summary"]
	if permission_scope == "execute":
		summary = f"{summary} Execute permission is active for this session."

	model["acceptedIntakeSummary"] = {
		"title": "Accepted intake summary",
		"body": summary,
	}
	model["snapshot"]["pendingPermissionRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["lane"] = envelope["lane"]
	model["snapshot"]["branch"] = envelope["branch"]
	model["snapshot"]["task"] = envelope["task"]
	model["snapshot"]["recentArtifacts"] = artifacts
	model["snapshot"]["permissionScope"] = permission_scope
	model["feed"].append(
		_feed_item(
			"system_status",
			"Permission confirmed: Execute"
			if permission_scope == "execute"
			else "Accepted and ready",
			summary,
			authoritative=True,
			now=now,
			**_semantic_provenance(
				turn_type=turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=semantic_paraphrase,
				semantic_normalized_text=semantic_normalized_text,
				in_response_to_request_id=request_id,
			),
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="governor" if permission_scope == "execute" else "orchestration",
		currentStage="running" if permission_scope == "execute" else "intake_accepted",
		runState="running" if permission_scope == "execute" else "idle",
		transportState="connected",
	)
	return True


def handle_submit_prompt(
	session: dict[str, Any],
	text: str,
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	turn_type: str | None = None,
	normalized_text: str | None = None,
	paraphrase: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not _session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this request was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	prompt = trim_text(text)
	if not prompt:
		_append_error(
			model,
			"Prompt required",
			"Enter a prompt before sending it.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	semantic_prompt = trim_text(normalized_text) or prompt
	resolved_turn_type = turn_type or _classify_turn(semantic_prompt)
	if resolved_turn_type == "governor_dialogue":
		if not _scope_satisfies(_current_permission_scope(model), "observe"):
			_append_user_turn(
				model,
				now,
				title="Governor question",
				body=prompt,
				turn_type=resolved_turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_prompt,
				in_response_to_request_id=request_id,
			)
			permission_request = _permission_request("observe", now)
			model["snapshot"]["pendingPermissionRequest"] = permission_request
			model["feed"].append(
				_feed_item(
					"permission_request",
					permission_request["title"],
					permission_request["body"],
					authoritative=True,
					now=now,
					**_semantic_provenance(
						turn_type=resolved_turn_type,
						semantic_input_version=semantic_input_version,
						semantic_summary_ref=semantic_summary_ref,
						semantic_context_flags=semantic_context_flags,
						semantic_route_type=semantic_route_type,
						semantic_confidence=semantic_confidence,
						semantic_block_reason=semantic_block_reason,
						semantic_paraphrase=paraphrase,
						semantic_normalized_text=semantic_prompt,
						in_response_to_request_id=request_id,
					),
				)
			)
			_refresh_snapshot(
				model,
				now,
				currentActor="orchestration",
				currentStage="permission_needed",
				runState="idle",
				transportState="connected",
			)
			return

		body, details, primary_ref = _build_governor_dialogue(
			session,
			semantic_prompt,
			repo_root=repo_root,
		)
		_append_user_turn(
			model,
			now,
			title="Governor question",
			body=prompt,
			turn_type=resolved_turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_prompt,
			in_response_to_request_id=request_id,
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
				**_semantic_provenance(
					turn_type=resolved_turn_type,
					semantic_input_version=semantic_input_version,
					semantic_summary_ref=semantic_summary_ref,
					semantic_context_flags=semantic_context_flags,
					semantic_route_type=semantic_route_type,
					semantic_confidence=semantic_confidence,
					semantic_block_reason=semantic_block_reason,
					semantic_paraphrase=paraphrase,
					semantic_normalized_text=semantic_prompt,
					in_response_to_request_id=request_id,
				),
			)
		)
		_refresh_snapshot(model, now, transportState="connected")
		return

	_supersede_pending_permission_request(model, now, request_id=request_id)
	envelope = start_intake(prompt, normalized_text=semantic_prompt, repo_root=repo_root)
	session["meta"]["activeIntakeRef"] = envelope["intake_ref"]

	_append_user_turn(
		model,
		now,
		title="Prompt submitted",
		body=prompt,
		turn_type=resolved_turn_type,
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=paraphrase,
		semantic_normalized_text=semantic_prompt,
		in_response_to_request_id=request_id,
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
			**_semantic_provenance(
				turn_type=resolved_turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_prompt,
				in_response_to_request_id=request_id,
			),
		)
	)
	model["acceptedIntakeSummary"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["recentArtifacts"] = []
	model["snapshot"]["task"] = envelope.get("task_hint") or summarize(semantic_prompt, 60)
	model["snapshot"]["branch"] = model["snapshot"].get("branch") or git_branch_name(repo_root)

	if envelope["shell_state"] == "clarification_needed":
		clarification = {
			**envelope["clarification_request"],
			"contextRef": envelope["clarification_request"].get("contextRef")
			or envelope["clarification_request"]["id"],
		}
		model["activeClarification"] = clarification
		model["snapshot"]["pendingPermissionRequest"] = None
		model["feed"].append(
			_feed_item(
				"clarification_request",
				clarification["title"],
				clarification["body"],
				authoritative=True,
				now=now,
				**_semantic_provenance(
					turn_type=resolved_turn_type,
					semantic_input_version=semantic_input_version,
					semantic_summary_ref=semantic_summary_ref,
					semantic_context_flags=semantic_context_flags,
					semantic_route_type=semantic_route_type,
					semantic_confidence=semantic_confidence,
					semantic_block_reason=semantic_block_reason,
					semantic_paraphrase=paraphrase,
					semantic_normalized_text=semantic_prompt,
					in_response_to_request_id=request_id,
				),
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
	required_scope = _recommended_permission_scope(semantic_prompt)
	if _scope_satisfies(_current_permission_scope(model), required_scope):
		model["snapshot"]["pendingPermissionRequest"] = _permission_request(required_scope, now)
		_accept_pending_intake(
			session,
			now,
			repo_root=repo_root,
			permission_scope=_current_permission_scope(model),
			request_id=request_id,
			turn_type=resolved_turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_prompt,
		)
		return

	model["snapshot"]["pendingPermissionRequest"] = _permission_request(required_scope, now)
	model["feed"].append(
		_feed_item(
			"permission_request",
			"Permission needed",
			model["snapshot"]["pendingPermissionRequest"]["body"],
			authoritative=True,
			now=now,
			**_semantic_provenance(
				turn_type=resolved_turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_prompt,
				in_response_to_request_id=request_id,
			),
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="permission_needed",
		runState="idle",
		transportState="connected",
	)


def handle_answer_clarification(
	session: dict[str, Any],
	text: str,
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	normalized_text: str | None = None,
	paraphrase: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not _session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this clarification was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	intake_ref = session["meta"].get("activeIntakeRef")
	if not intake_ref or not model.get("activeClarification"):
		_append_error(
			model,
			"No clarification is active",
			"There is no active clarification request to answer.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	expected_context_ref = model["activeClarification"].get("contextRef") or model["activeClarification"].get("id")
	if not _context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Clarification changed",
			"The clarification changed before this answer was applied. Refresh and answer the current clarification instead.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	answer = trim_text(text)
	if not answer:
		_append_error(
			model,
			"Clarification answer required",
			"Enter a clarification answer before sending it.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	semantic_answer = trim_text(normalized_text) or answer
	envelope = answer_intake_clarification(
		intake_ref,
		answer,
		normalized_text=semantic_answer,
		repo_root=repo_root,
	)
	_append_user_turn(
		model,
		now,
		title="Clarification answered",
		body=answer,
		turn_type="clarification_reply",
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=paraphrase,
		semantic_normalized_text=semantic_answer,
		in_response_to_request_id=request_id,
	)
	model["feed"].append(
		_feed_item(
			"shell_event",
			"Draft is ready for permission review",
			"Intake updated the draft and handed it back for permission selection.",
			authoritative=False,
			now=now,
			activity={"kind": "status", "state": "completed", "summary": "Ready for permission"},
			**_semantic_provenance(
				turn_type="clarification_reply",
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_answer,
				in_response_to_request_id=request_id,
			),
		)
	)
	model["activeClarification"] = None
	required_scope = _recommended_permission_scope(semantic_answer)
	if _scope_satisfies(_current_permission_scope(model), required_scope):
		model["snapshot"]["pendingPermissionRequest"] = _permission_request(required_scope, now)
		_accept_pending_intake(
			session,
			now,
			repo_root=repo_root,
			permission_scope=_current_permission_scope(model),
			request_id=request_id,
			turn_type="clarification_reply",
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_answer,
		)
		return
	model["snapshot"]["pendingPermissionRequest"] = _permission_request(required_scope, now)
	model["feed"].append(
		_feed_item(
			"permission_request",
			"Permission needed",
			model["snapshot"]["pendingPermissionRequest"]["body"],
			authoritative=True,
			now=now,
			**_semantic_provenance(
				turn_type="clarification_reply",
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_answer,
				in_response_to_request_id=request_id,
			),
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="permission_needed",
		runState="idle",
		transportState="connected",
	)


def handle_set_permission_scope(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	permission_scope: str | None = None,
	text: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not _session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this permission choice was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	raw_text = trim_text(text or "")
	if raw_text:
		_append_user_turn(
			model,
			now,
			title="Permission selected",
			body=raw_text,
			turn_type="permission_action",
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=semantic_paraphrase,
			semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text,
			in_response_to_request_id=request_id,
		)
	expected_context_ref = (
		model["snapshot"]["pendingPermissionRequest"].get("contextRef")
		if isinstance(model["snapshot"].get("pendingPermissionRequest"), dict)
		else None
	)
	if not _context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Permission changed",
			"The permission request changed before this action was applied. Refresh and confirm the current permission surface.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	if permission_scope not in {"observe", "plan", "execute"}:
		_append_error(
			model,
			"Permission scope required",
			"Choose Observe, Plan, or Execute to continue.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	_accept_pending_intake(
		session,
		now,
		repo_root=repo_root,
		permission_scope=permission_scope,
		request_id=request_id,
		turn_type="permission_action",
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=semantic_paraphrase,
		semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text or None,
	)


def handle_decline_permission(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not _session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this permission request was declined. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	if not model["snapshot"].get("pendingPermissionRequest"):
		_append_error(
			model,
			"Nothing to decline",
			"There is no permission request to decline.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	expected_context_ref = (
		model["snapshot"]["pendingPermissionRequest"].get("contextRef")
		if isinstance(model["snapshot"].get("pendingPermissionRequest"), dict)
		else None
	)
	if not _context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Permission changed",
			"The permission request changed before this action was applied. Refresh and confirm the current permission surface.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	model["snapshot"]["pendingPermissionRequest"] = None
	model["feed"].append(
		_feed_item(
			"system_status",
			"Permission request declined",
			"Permission scope stayed unchanged, and this request will not continue.",
			authoritative=True,
			now=now,
			in_response_to_request_id=request_id,
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="permission_declined",
		runState="idle",
		transportState="connected",
	)


def handle_interrupt(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	text: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not _session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this stop request was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	raw_text = trim_text(text or "")
	if model["snapshot"].get("runState") != "running":
		_append_error(
			model,
			"Nothing is running",
			"Stop is only available while governed work is actively running.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	if model["snapshot"].get("pendingInterrupt"):
		_append_error(
			model,
			"Stop already requested",
			"A stop request is already waiting for orchestration handling.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	expected_context_ref = _current_interrupt_context_ref(model)
	if not _context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Interrupt state changed",
			"The interruptible run state changed before this stop request was applied. Refresh and try again if stop is still available.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	model["snapshot"]["pendingInterrupt"] = _request_card(
		"Stop requested",
		"Stop has been requested and is waiting for orchestration handling.",
		now,
	)
	if raw_text:
		_append_user_turn(
			model,
			now,
			title="Stop requested",
			body=raw_text,
			turn_type="stop_action",
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=semantic_paraphrase,
			semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text,
			in_response_to_request_id=request_id,
		)
	model["feed"].append(
		_feed_item(
			"interrupt_request",
			"Stop requested",
			"Stop has been requested and is waiting for orchestration handling.",
			authoritative=True,
			now=now,
			**_semantic_provenance(
				turn_type="stop_action",
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=semantic_paraphrase,
				semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text or None,
				in_response_to_request_id=request_id,
			),
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


def handle_reconnect(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and model["snapshot"].get("sessionRef") and session_ref != model["snapshot"].get("sessionRef"):
		model["snapshot"]["sessionRef"] = _next_id("session")
		model["snapshot"]["permissionScope"] = "unset"
		model["snapshot"]["pendingPermissionRequest"] = None
		model["activeClarification"] = None
		model["acceptedIntakeSummary"] = None
		model["snapshot"]["pendingInterrupt"] = None
		model["snapshot"]["recentArtifacts"] = []
		model["feed"].append(
			_feed_item(
				"system_status",
				"Switched session",
				"Reconnect attached to a different session snapshot.",
				authoritative=True,
				now=now,
				in_response_to_request_id=request_id,
			)
		)
		_refresh_snapshot(model, now, transportState="connected")
		return
	if (
		model["snapshot"].get("transportState") == "connected"
		and not _is_snapshot_stale(model["snapshot"], now)
	):
		_append_error(
			model,
			"Nothing to reconnect",
			"The current session is already connected and fresh.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	model["feed"].append(
		_feed_item(
			"system_status",
			"Reconnected",
			"Reloaded the latest orchestration-backed session snapshot.",
			authoritative=True,
			now=now,
			in_response_to_request_id=request_id,
		)
	)
	_refresh_snapshot(model, now, transportState="connected")


def dispatch_session_action(
	command: str,
	*,
	text: str | None = None,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	permission_scope: str | None = None,
	turn_type: str | None = None,
	normalized_text: str | None = None,
	paraphrase: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
) -> dict[str, Any]:
	session = load_session(repo_root)
	now = utc_now()
	if command != "state" and _is_duplicate_request(session, request_id):
		_append_error(
			session["model"],
			"Duplicate request",
			"The same controller request was already handled. Refresh and send a new action if you still want to proceed.",
			now,
			in_response_to_request_id=request_id,
		)
		save_session(session, repo_root=repo_root)
		return public_model(session)
	if command == "submit_prompt":
		handle_submit_prompt(
			session,
			text or "",
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			turn_type=turn_type,
			normalized_text=normalized_text,
			paraphrase=paraphrase,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
		)
	elif command == "answer_clarification":
		handle_answer_clarification(
			session,
			text or "",
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			normalized_text=normalized_text,
			paraphrase=paraphrase,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
		)
	elif command == "set_permission_scope":
		handle_set_permission_scope(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			permission_scope=permission_scope,
			text=text,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=normalized_text,
		)
	elif command == "decline_permission":
		handle_decline_permission(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
		)
	elif command == "interrupt_run":
		handle_interrupt(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			text=text,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=normalized_text,
		)
	elif command == "reconnect":
		handle_reconnect(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
		)
	elif command != "state":
		raise ValueError(f"unsupported session command: {command}")

	if command != "state":
		_remember_request(session, request_id, command, now)
	save_session(session, repo_root=repo_root)
	return public_model(session)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="UI session bridge for orchestration-backed extension state")
	subparsers = parser.add_subparsers(dest="command", required=True)

	subparsers.add_parser("state")

	submit = subparsers.add_parser("submit_prompt")
	submit.add_argument("--text", required=True)
	submit.add_argument("--request-id")
	submit.add_argument("--session-ref")
	submit.add_argument("--context-ref")
	submit.add_argument("--turn-type")
	submit.add_argument("--normalized-text")
	submit.add_argument("--paraphrase")
	submit.add_argument("--semantic-input-version")
	submit.add_argument("--semantic-summary-ref")
	submit.add_argument("--semantic-context-flags-json")
	submit.add_argument("--semantic-route-type")
	submit.add_argument("--semantic-confidence")
	submit.add_argument("--semantic-block-reason")

	answer = subparsers.add_parser("answer_clarification")
	answer.add_argument("--text", required=True)
	answer.add_argument("--request-id")
	answer.add_argument("--session-ref")
	answer.add_argument("--context-ref")
	answer.add_argument("--turn-type")
	answer.add_argument("--normalized-text")
	answer.add_argument("--paraphrase")
	answer.add_argument("--semantic-input-version")
	answer.add_argument("--semantic-summary-ref")
	answer.add_argument("--semantic-context-flags-json")
	answer.add_argument("--semantic-route-type")
	answer.add_argument("--semantic-confidence")
	answer.add_argument("--semantic-block-reason")

	set_scope = subparsers.add_parser("set_permission_scope")
	set_scope.add_argument("--text")
	set_scope.add_argument("--request-id")
	set_scope.add_argument("--session-ref")
	set_scope.add_argument("--context-ref")
	set_scope.add_argument("--permission-scope", required=True)
	set_scope.add_argument("--turn-type")
	set_scope.add_argument("--normalized-text")
	set_scope.add_argument("--paraphrase")
	set_scope.add_argument("--semantic-input-version")
	set_scope.add_argument("--semantic-summary-ref")
	set_scope.add_argument("--semantic-context-flags-json")
	set_scope.add_argument("--semantic-route-type")
	set_scope.add_argument("--semantic-confidence")
	set_scope.add_argument("--semantic-block-reason")
	decline = subparsers.add_parser("decline_permission")
	decline.add_argument("--request-id")
	decline.add_argument("--session-ref")
	decline.add_argument("--context-ref")
	interrupt = subparsers.add_parser("interrupt_run")
	interrupt.add_argument("--text")
	interrupt.add_argument("--request-id")
	interrupt.add_argument("--session-ref")
	interrupt.add_argument("--context-ref")
	interrupt.add_argument("--turn-type")
	interrupt.add_argument("--normalized-text")
	interrupt.add_argument("--paraphrase")
	interrupt.add_argument("--semantic-input-version")
	interrupt.add_argument("--semantic-summary-ref")
	interrupt.add_argument("--semantic-context-flags-json")
	interrupt.add_argument("--semantic-route-type")
	interrupt.add_argument("--semantic-confidence")
	interrupt.add_argument("--semantic-block-reason")
	reconnect = subparsers.add_parser("reconnect")
	reconnect.add_argument("--request-id")
	reconnect.add_argument("--session-ref")
	return parser


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	args = build_parser().parse_args(argv)
	try:
		semantic_context_flags = None
		if getattr(args, "semantic_context_flags_json", None):
			semantic_context_flags = json.loads(args.semantic_context_flags_json)
		model = dispatch_session_action(
			args.command,
			text=getattr(args, "text", None),
			repo_root=repo_root,
			session_ref=getattr(args, "session_ref", None),
			request_id=getattr(args, "request_id", None),
			context_ref=getattr(args, "context_ref", None),
			permission_scope=getattr(args, "permission_scope", None),
			turn_type=getattr(args, "turn_type", None),
			normalized_text=getattr(args, "normalized_text", None),
			paraphrase=getattr(args, "paraphrase", None),
			semantic_input_version=getattr(args, "semantic_input_version", None),
			semantic_summary_ref=getattr(args, "semantic_summary_ref", None),
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=getattr(args, "semantic_route_type", None),
			semantic_confidence=getattr(args, "semantic_confidence", None),
			semantic_block_reason=getattr(args, "semantic_block_reason", None),
		)
	except (ValueError, json.JSONDecodeError) as exc:
		raise SystemExit(str(exc))
	print(json.dumps(model, indent=2, sort_keys=True))
	return 0
