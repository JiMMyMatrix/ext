from __future__ import annotations

import json
from typing import Any

from orchestration.harness.paths import trim_text, utc_now


def parse_governor_semantic_intake_payload(body: str) -> dict[str, Any] | None:
	raw = trim_text(body)
	if not raw:
		return None
	try:
		payload = json.loads(raw)
	except json.JSONDecodeError:
		start = raw.find("{")
		end = raw.rfind("}")
		if start < 0 or end <= start:
			return None
		try:
			payload = json.loads(raw[start : end + 1])
		except json.JSONDecodeError:
			return None
	return payload if isinstance(payload, dict) else None


def semantic_proposal(payload: dict[str, Any]) -> dict[str, Any]:
	proposal = payload.get("proposal")
	if not isinstance(proposal, dict):
		proposal = payload
	return proposal


def semantic_user_copy(payload: dict[str, Any], fallback: str) -> str:
	return trim_text(payload.get("user_visible_reply") if isinstance(payload.get("user_visible_reply"), str) else "") or fallback


def record_rejected_proposal(
	session: dict[str, Any], pending: dict[str, Any], reason: str, proposal: Any
) -> None:
	session.setdefault("meta", {})["lastRejectedGovernorSemanticProposal"] = {
		"runtimeRequestId": pending.get("runtimeRequestId"),
		"requestId": pending.get("requestId"),
		"reason": reason,
		"proposal": proposal if isinstance(proposal, dict) else None,
		"rejectedAt": utc_now(),
	}


def proposal_permission(proposal: dict[str, Any]) -> str:
	permission = proposal.get("recommended_permission")
	return permission if permission in {"observe", "plan", "execute", "none"} else "none"


def proposal_route(proposal: dict[str, Any]) -> str | None:
	route = proposal.get("route_type")
	return route if isinstance(route, str) else None


def proposal_confidence(proposal: dict[str, Any]) -> str:
	confidence = proposal.get("confidence")
	return confidence if confidence in {"high", "low"} else "low"


def proposal_normalized_intent(proposal: dict[str, Any], fallback: str) -> str:
	return trim_text(proposal.get("normalized_intent") if isinstance(proposal.get("normalized_intent"), str) else "") or fallback


def clarification_options(proposal: dict[str, Any]) -> list[dict[str, Any]]:
	options = proposal.get("clarification_options")
	if not isinstance(options, list):
		return []
	normalized: list[dict[str, Any]] = []
	for index, option in enumerate(options):
		if not isinstance(option, dict):
			continue
		label = trim_text(option.get("label") if isinstance(option.get("label"), str) else "")
		value = trim_text(option.get("value") if isinstance(option.get("value"), str) else "")
		if not label or not value:
			continue
		normalized.append({"id": f"option-{index + 1}", "label": label, "answer": value})
	return normalized


def initial_rejection_reason(proposal: dict[str, Any]) -> str | None:
	route = proposal_route(proposal)
	confidence = proposal_confidence(proposal)
	if confidence != "high" and route != "block":
		return "semantic_intake_low_confidence"
	if "permission_scope" in proposal:
		return "semantic_intake_direct_permission_mutation"
	if route in {"clarification_reply", "execute", "dispatch"}:
		return "semantic_intake_unsupported_state_claim"
	return None
