from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from orchestration.harness import governor_runtime
from orchestration.harness import session_context
from orchestration.harness.session_feed import _next_id

RefreshSnapshot = Callable[..., None]


def pending_governor_runtime_request(session: dict[str, Any]) -> dict[str, Any] | None:
	pending = session.setdefault("meta", {}).get("pendingGovernorRuntimeRequest")
	return pending if isinstance(pending, dict) else None


def build_governor_runtime_request_envelope(pending: dict[str, Any]) -> dict[str, Any]:
	return {
		"runtimeKind": pending.get("runtimeKind") or "dialogue",
		"runtimeRequestId": pending["runtimeRequestId"],
		"requestId": pending.get("requestId"),
		"preferredAppServerThreadId": pending.get("preferredAppServerThreadId"),
		"initialPrompt": pending["initialPrompt"],
		"resumePrompt": pending["resumePrompt"],
		"model": pending["model"],
		"reasoning": pending["reasoning"],
		"resultStage": pending["resultStage"],
		"context": pending.get("context") or {},
	}


def prepare_governor_dialogue_runtime_request(
	session: dict[str, Any],
	prompt: str,
	now: str,
	*,
	refresh_snapshot: RefreshSnapshot,
	repo_root: str | Path | None = None,
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
	result_stage: str = "dialogue_ready",
	runtime_kind: str = "dialogue",
	auto_execute_revised_plan: bool = False,
	auto_consume_executor_after_plan: bool = False,
	auto_governor_runtime_after_plan: str = "exec",
	return_runtime_request: bool = False,
) -> dict[str, Any]:
	context = session_context.governor_dialogue_context(
		session,
		prompt,
		repo_root=repo_root,
	)
	governor_meta = session_context.governor_dialogue_meta(session)
	model_name, reasoning = governor_runtime.governor_runtime_settings(repo_root)
	runtime_request_id = _next_id("governor-runtime")
	initial_prompt = (
		governor_runtime.initial_governor_plan_prompt(context["prompt"])
		if runtime_kind == "plan"
		else governor_runtime.initial_governor_dialogue_prompt(context["prompt"], repo_root=repo_root)
	)
	resume_prompt = (
		governor_runtime.resume_governor_plan_prompt(context["prompt"])
		if runtime_kind == "plan"
		else governor_runtime.resume_governor_dialogue_prompt(context["prompt"])
	)
	pending = {
		"runtimeKind": runtime_kind,
		"runtimeRequestId": runtime_request_id,
		"requestId": request_id,
		"preferredAppServerThreadId": governor_meta.get("appServerThreadId")
		if isinstance(governor_meta.get("appServerThreadId"), str)
		else None,
		"initialPrompt": initial_prompt,
		"resumePrompt": resume_prompt,
		"model": model_name,
		"reasoning": reasoning,
		"resultStage": result_stage,
		"createdAt": now,
		"prompt": prompt,
		"details": context["details"],
		"primaryRef": context["primary_ref"],
		"turnType": turn_type,
		"semanticInputVersion": semantic_input_version,
		"semanticSummaryRef": semantic_summary_ref,
		"semanticContextFlags": semantic_context_flags,
		"semanticRouteType": semantic_route_type,
		"semanticConfidence": semantic_confidence,
		"semanticBlockReason": semantic_block_reason,
		"semanticParaphrase": semantic_paraphrase,
		"semanticNormalizedText": semantic_normalized_text or prompt,
		"revisionReason": session["model"].get("currentPlanRevisionReason"),
		"latestReviewRef": session["model"].get("latestReviewRef"),
		"autoExecuteRevisedPlan": auto_execute_revised_plan,
		"autoConsumeExecutorAfterPlan": auto_consume_executor_after_plan,
		"autoGovernorRuntimeAfterPlan": auto_governor_runtime_after_plan,
		"returnAsRuntimeRequest": return_runtime_request,
		"context": {
			"sessionRef": session["model"]["snapshot"].get("sessionRef"),
			"foregroundRequestId": request_id,
			"currentStage": session["model"]["snapshot"].get("currentStage"),
		},
	}
	session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = pending
	refresh_snapshot(
		session["model"],
		now,
		currentActor="governor",
		currentStage="waiting_for_governor",
		runState="running",
		transportState="connected",
	)
	return pending


def prepare_governor_semantic_intake_runtime_request(
	session: dict[str, Any],
	prompt: str,
	now: str,
	*,
	refresh_snapshot: RefreshSnapshot,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
) -> dict[str, Any]:
	context = session_context.governor_dialogue_context(
		session,
		prompt,
		repo_root=repo_root,
		semantic_intake=True,
	)
	governor_meta = session_context.governor_dialogue_meta(session)
	model_name, _reasoning = governor_runtime.governor_runtime_settings(repo_root)
	reasoning = "low"
	runtime_request_id = _next_id("governor-runtime")
	pending = {
		"runtimeKind": "semantic_intake",
		"runtimeRequestId": runtime_request_id,
		"requestId": request_id,
		"preferredAppServerThreadId": governor_meta.get("appServerThreadId")
		if isinstance(governor_meta.get("appServerThreadId"), str)
		else None,
		"initialPrompt": governor_runtime.initial_governor_semantic_intake_prompt(
			context["prompt"],
			repo_root=repo_root,
		),
		"resumePrompt": governor_runtime.resume_governor_semantic_intake_prompt(context["prompt"]),
		"model": model_name,
		"reasoning": reasoning,
		"resultStage": "semantic_intake",
		"createdAt": now,
		"prompt": prompt,
		"details": context["details"],
		"primaryRef": context["primary_ref"],
		"context": {
			"sessionRef": session["model"]["snapshot"].get("sessionRef"),
			"foregroundRequestId": request_id,
			"currentStage": session["model"]["snapshot"].get("currentStage"),
			"permissionScope": session["model"]["snapshot"].get("permissionScope"),
		},
	}
	session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = pending
	refresh_snapshot(
		session["model"],
		now,
		currentActor="governor",
		currentStage="semantic_intake",
		runState="running",
		transportState="connected",
	)
	return pending
