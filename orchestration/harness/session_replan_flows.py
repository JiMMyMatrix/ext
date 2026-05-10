from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from orchestration.harness import session_permissions
from orchestration.harness import session_work_lifecycle
from orchestration.harness.paths import trim_text


AppendError = Callable[..., None]
AppendGovernorDialogueResponse = Callable[..., bool]
HandleExecutePlan = Callable[..., None]
NextId = Callable[[str], str]
RefreshSnapshot = Callable[..., None]


def auto_execute_revised_plan(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
	return_runtime_request: bool = False,
	next_id: NextId,
	handle_execute_plan: HandleExecutePlan,
) -> bool:
	model = session["model"]
	plan_ready = model.get("planReadyRequest")
	if not isinstance(plan_ready, dict):
		return False
	if model["snapshot"].get("currentStage") != "plan_ready":
		return False
	if model.get("currentPlanRevisionReason") not in {
		"review_requested_changes",
		"review_inconclusive",
	}:
		return False
	if not session_permissions.scope_satisfies(model["snapshot"].get("permissionScope"), "execute"):
		return False
	context_ref = plan_ready.get("contextRef")
	if not isinstance(context_ref, str) or not context_ref.strip():
		return False
	handle_execute_plan(
		session,
		repo_root=repo_root,
		session_ref=model["snapshot"].get("sessionRef"),
		request_id=request_id or next_id("request"),
		context_ref=context_ref,
		governor_runtime=governor_runtime,
		auto_consume_executor=auto_consume_executor,
		return_runtime_request=return_runtime_request,
	)
	return True


def maybe_replan_after_review(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any] | None,
	decision: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
	return_runtime_request: bool = False,
	record_work_review_and_decision: Callable[..., dict[str, Any] | None],
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
	append_governor_dialogue_response: AppendGovernorDialogueResponse,
) -> bool:
	decision_payload = record_work_review_and_decision(
		session,
		dispatch_refs,
		decision,
		now,
		repo_root=repo_root,
	)
	if not session_work_lifecycle.decision_needs_replan(decision_payload):
		return False
	model = session["model"]
	work_ref = dispatch_refs.get("work_ref") if isinstance(dispatch_refs, dict) else None
	if not isinstance(work_ref, str) or not work_ref.strip():
		return False
	index = session_work_lifecycle.load_work_index(work_ref, repo_root=repo_root)
	if int(index.get("revision_count") or 0) >= 2:
		index["status"] = "blocked"
		index["blocked_reason"] = "revision_limit_reached"
		index["updated_at"] = now
		session_work_lifecycle.save_work_index(work_ref, index, repo_root=repo_root)
		append_error(
			model,
			"Revision limit reached",
			"Reviewer feedback still requires changes after the bounded revision loop. Review the source artifacts before continuing.",
			now,
			in_response_to_request_id=request_id,
			source_artifact_ref=decision.get("artifacts", [{}])[0].get("path")
			if decision.get("artifacts")
			else None,
			presentation_key="error.revision_limit",
		)
		refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="blocked",
			runState="idle",
			transportState="connected",
		)
		model["activeForegroundRequestId"] = None
		return True
	review_ref = dispatch_refs.get("review_ref") if isinstance(dispatch_refs, dict) else None
	decision_value = trim_text(decision_payload.get("decision"))
	revision_reason = (
		"review_inconclusive"
		if decision_value == "needs_verification"
		else "review_requested_changes"
	)
	model["currentWorkRef"] = work_ref
	model["snapshot"]["currentWorkRef"] = work_ref
	model["latestReviewRef"] = review_ref
	model["currentPlanRevisionReason"] = revision_reason
	model["revisionOfDispatchRef"] = dispatch_refs.get("dispatch_ref") if isinstance(dispatch_refs, dict) else None
	prompt = (
		"Revise the current plan for the same accepted intake. "
		"Use the Reviewer feedback and Governor decision as advisory evidence. "
		"Keep the revised plan in scope and do not create dispatch truth. "
		f"Previous dispatch: {dispatch_refs.get('dispatch_ref')}. "
		f"Reviewer artifact: {review_ref}. "
		f"Governor decision: {decision_payload.get('decision')} - {decision_payload.get('reason')}."
	)
	return append_governor_dialogue_response(
		session,
		prompt,
		now,
		repo_root=repo_root,
		request_id=request_id,
		turn_type="governed_work_intent",
		semantic_route_type="governed_work_intent",
		semantic_confidence="high",
		semantic_normalized_text="revise current plan from reviewer feedback",
		result_stage="plan_ready",
		runtime_kind="plan",
		governor_runtime=governor_runtime,
		auto_execute_revised_plan=auto_consume_executor
		and session_permissions.scope_satisfies(model["snapshot"].get("permissionScope"), "execute"),
		auto_consume_executor_after_plan=auto_consume_executor,
		auto_governor_runtime_after_plan=governor_runtime,
		return_runtime_request=return_runtime_request,
	)
