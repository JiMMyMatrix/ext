from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any


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
	presentation_key: str | None = None,
	presentation_args: dict[str, Any] | None = None,
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
	if presentation_key:
		payload["presentation_key"] = presentation_key
	if presentation_args is not None:
		payload["presentation_args"] = presentation_args
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
