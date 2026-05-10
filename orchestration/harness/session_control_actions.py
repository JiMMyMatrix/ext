from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration.harness import session_context
from orchestration.harness import session_guards
from orchestration.harness import session_model
from orchestration.harness import session_surfaces
from orchestration.harness import session_work_lifecycle
from orchestration.harness.paths import trim_text, utc_now
from orchestration.harness.session_feed import _feed_item, _next_id, _request_card


def _append_error(
	model: dict[str, Any],
	title: str,
	body: str,
	now: str,
	*,
	in_response_to_request_id: str | None = None,
	presentation_key: str = "error.generic",
	presentation_args: dict[str, Any] | None = None,
) -> None:
	session_surfaces.append_error(
		model,
		title,
		body,
		now,
		refresh_snapshot=session_model.refresh_snapshot,
		in_response_to_request_id=in_response_to_request_id,
		presentation_key=presentation_key,
		presentation_args=presentation_args,
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
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this permission request was declined. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
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
	if not session_guards.context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Permission changed",
			"The permission request changed before this action was applied. Refresh and confirm the current permission surface.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "permission"},
		)
		return

	pending_permission = model["snapshot"].get("pendingPermissionRequest")
	declined_plan_execution = (
		isinstance(pending_permission, dict)
		and pending_permission.get("continuationKind") == "plan_execution"
		and isinstance(model.get("planReadyRequest"), dict)
	)
	model["snapshot"]["pendingPermissionRequest"] = None
	model["activeForegroundRequestId"] = None
	model["feed"].append(
		_feed_item(
			"system_status",
			"Permission request declined",
			"Permission scope stayed unchanged, and this request will not continue.",
			authoritative=True,
			now=now,
			in_response_to_request_id=request_id,
			presentation_key="permission.declined",
		)
	)
	session_model.refresh_snapshot(
		model,
		now,
		currentActor="governor" if declined_plan_execution else "orchestration",
		currentStage="plan_ready" if declined_plan_execution else "permission_declined",
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
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this stop request was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
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
	expected_context_ref = session_guards.current_interrupt_context_ref(model)
	if not session_guards.context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Interrupt state changed",
			"The interruptible run state changed before this stop request was applied. Refresh and try again if stop is still available.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "interrupt"},
		)
		return
	model["snapshot"]["pendingInterrupt"] = _request_card(
		"Stop requested",
		"Stop has been requested and is waiting for orchestration handling.",
		now,
	)
	if raw_text:
		session_surfaces.append_user_turn(
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
			**session_surfaces.semantic_provenance(
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
	session_model.refresh_snapshot(
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
		model["planReadyRequest"] = None
		session_work_lifecycle.reset_work_loop_state(session)
		model["snapshot"]["pendingInterrupt"] = None
		model["snapshot"]["recentArtifacts"] = []
		session_context.governor_dialogue_meta(session).clear()
		model["feed"].append(
			_feed_item(
				"system_status",
				"Switched session",
				"Reconnect attached to a different session snapshot.",
				authoritative=True,
				now=now,
				in_response_to_request_id=request_id,
				presentation_key="session.switched",
			)
		)
		session_model.refresh_snapshot(model, now, transportState="connected")
		return
	if (
		model["snapshot"].get("transportState") == "connected"
		and not session_guards.is_snapshot_stale(model["snapshot"], now)
	):
		_append_error(
			model,
			"Nothing to reconnect",
			"The current session is already connected and fresh.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="reconnect.not_needed",
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
	session_model.refresh_snapshot(model, now, transportState="connected")
