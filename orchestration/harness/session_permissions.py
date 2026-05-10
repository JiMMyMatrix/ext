from __future__ import annotations

from typing import Any, Callable

from orchestration.harness import session_state


NextId = Callable[[str], str]


def current_permission_scope(model: dict[str, Any]) -> str:
	return model["snapshot"].get("permissionScope") or "unset"


def scope_satisfies(current_scope: str | None, required_scope: str | None) -> bool:
	return session_state.scope_satisfies(current_scope, required_scope)


def allowed_permission_scopes(required_scope: str | None) -> list[str]:
	return session_state.allowed_permission_scopes(required_scope)


def format_permission_scope(scope: str | None) -> str:
	return session_state.format_permission_scope(scope)


def should_request_execute_for_accepted_continuation(
	model: dict[str, Any], semantic_context_flags: dict[str, Any] | None
) -> bool:
	return bool(
		model.get("acceptedIntakeSummary")
		and model["snapshot"].get("permissionScope") == "plan"
		and model["snapshot"].get("currentStage") == "plan_ready"
		and isinstance(semantic_context_flags, dict)
		and semantic_context_flags.get("used_accepted_intake_summary")
	)


def permission_request(
	recommended_scope: str,
	now: str,
	*,
	next_id: NextId,
	continuation_kind: str = "intake_acceptance",
	pending_prompt: str | None = None,
	pending_normalized_text: str | None = None,
	foreground_request_id: str | None = None,
) -> dict[str, Any]:
	request_id = next_id("permission")
	return {
		"id": request_id,
		"contextRef": request_id,
		"title": "Permission needed",
		"body": f"Choose {recommended_scope} if you want Corgi to continue this request.",
		"recommendedScope": recommended_scope,
		"allowedScopes": allowed_permission_scopes(recommended_scope),
		"continuationKind": continuation_kind,
		"pendingPrompt": pending_prompt,
		"pendingNormalizedText": pending_normalized_text,
		"foregroundRequestId": foreground_request_id,
		"requestedAt": now,
	}


def recommended_permission_scope(prompt: str) -> str:
	del prompt
	return "plan"
