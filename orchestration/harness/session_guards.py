from __future__ import annotations

from typing import Any

from orchestration.harness import session_state
from orchestration.harness.paths import utc_now


def processed_request_ids(session: dict[str, Any]) -> dict[str, Any]:
	meta = session.setdefault("meta", {})
	processed = meta.setdefault("processedRequestIds", {})
	if isinstance(processed, dict):
		return processed
	meta["processedRequestIds"] = {}
	return meta["processedRequestIds"]


def is_duplicate_request(session: dict[str, Any], request_id: str | None) -> bool:
	if not request_id:
		return False
	return request_id in processed_request_ids(session)


def remember_request(session: dict[str, Any], request_id: str | None, command: str, now: str) -> None:
	if not request_id:
		return
	processed_request_ids(session)[request_id] = {"command": command, "handledAt": now}


def is_snapshot_stale(snapshot: dict[str, Any], now: str) -> bool:
	return session_state.is_snapshot_stale(snapshot, now)


def current_interrupt_context_ref(model: dict[str, Any]) -> str:
	return f"interrupt:{model['snapshot']['snapshotFreshness'].get('receivedAt') or utc_now()}"


def context_matches(expected_context_ref: str | None, provided_context_ref: str | None) -> bool:
	return session_state.context_matches(expected_context_ref, provided_context_ref)


def session_ref_matches(model: dict[str, Any], provided_session_ref: str | None) -> bool:
	return session_state.session_ref_matches(model, provided_session_ref)
