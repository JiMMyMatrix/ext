from __future__ import annotations

from typing import Any, Callable

from orchestration.harness.session_feed import _feed_item


RefreshSnapshot = Callable[..., None]


def semantic_provenance(
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


def append_user_turn(
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
			**semantic_provenance(
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


def append_error(
	model: dict[str, Any],
	title: str,
	body: str,
	now: str,
	*,
	refresh_snapshot: RefreshSnapshot,
	in_response_to_request_id: str | None = None,
	presentation_key: str = "error.generic",
	presentation_args: dict[str, Any] | None = None,
	activity: dict[str, Any] | None = None,
	source_artifact_ref: str | None = None,
) -> None:
	model["feed"].append(
		_feed_item(
			"error",
			title,
			body,
			authoritative=True,
			now=now,
			activity=activity,
			source_artifact_ref=source_artifact_ref,
			in_response_to_request_id=in_response_to_request_id,
			presentation_key=presentation_key,
			presentation_args=presentation_args or {"title": title, "body": body},
		)
	)
	refresh_snapshot(model, now)
