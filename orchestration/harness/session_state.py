from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_received_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_snapshot_stale(snapshot: dict[str, Any], now: str) -> bool:
    freshness = snapshot.get("snapshotFreshness") or {}
    if freshness.get("stale") is True:
        return True
    received_at = parse_received_at(freshness.get("receivedAt"))
    current = parse_received_at(now)
    if received_at is None or current is None:
        return False
    return (current - received_at).total_seconds() > 45


def context_matches(expected_context_ref: str | None, provided_context_ref: str | None) -> bool:
    if expected_context_ref is None:
        return True
    return provided_context_ref == expected_context_ref


def session_ref_matches(model: dict[str, Any], provided_session_ref: str | None) -> bool:
    expected = model["snapshot"].get("sessionRef")
    if not expected:
        return True
    return provided_session_ref == expected


def permission_rank(scope: str | None) -> int:
    if scope == "observe":
        return 1
    if scope == "plan":
        return 2
    if scope == "execute":
        return 3
    return 0


def scope_satisfies(current_scope: str | None, required_scope: str | None) -> bool:
    return permission_rank(current_scope) >= permission_rank(required_scope)


def allowed_permission_scopes(required_scope: str | None) -> list[str]:
    return [
        scope
        for scope in ("observe", "plan", "execute")
        if scope_satisfies(scope, required_scope)
    ]


def format_permission_scope(scope: str | None) -> str:
    return (scope or "unset").capitalize()
