from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from orchestration.harness.paths import trim_text
from orchestration.harness.session_feed import _feed_item


AppendError = Callable[..., None]
AppendGovernorDialogueResponse = Callable[..., bool]


def supersede_pending_permission_request(
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
			presentation_key="permission.superseded",
		)
	)


def apply_governor_dialogue_permission(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	permission_scope: str,
	request_id: str | None = None,
	turn_type: str = "governor_dialogue",
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	governor_runtime: str = "exec",
	append_error: AppendError,
	append_governor_dialogue_response: AppendGovernorDialogueResponse,
) -> bool:
	model = session["model"]
	pending_permission = model["snapshot"].get("pendingPermissionRequest")
	if not pending_permission:
		append_error(
			model,
			"No permission request is active",
			"There is no permission request to apply.",
			now,
			in_response_to_request_id=request_id,
		)
		return False

	prompt = trim_text(
		pending_permission.get("pendingNormalizedText")
		or pending_permission.get("pendingPrompt")
	)
	if not prompt:
		append_error(
			model,
			"Pending dialogue request unavailable",
			"Corgi lost the pending Governor request before this permission choice was applied. Send the request again.",
			now,
			in_response_to_request_id=request_id,
		)
		return False

	model["snapshot"]["permissionScope"] = permission_scope
	model["snapshot"]["pendingPermissionRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	continuation_request_id = (
		pending_permission.get("foregroundRequestId")
		or model.get("activeForegroundRequestId")
		or request_id
	)
	model["activeForegroundRequestId"] = continuation_request_id
	return append_governor_dialogue_response(
		session,
		prompt,
		now,
		repo_root=repo_root,
		request_id=continuation_request_id,
		turn_type=turn_type,
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=semantic_paraphrase,
		semantic_normalized_text=semantic_normalized_text,
		governor_runtime=governor_runtime,
	)
