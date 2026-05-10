from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from orchestration.harness import session_guards
from orchestration.harness import session_permissions
from orchestration.harness.paths import trim_text, utc_now


AppendError = Callable[..., None]
AppendGovernorDialogueResponse = Callable[..., bool]
AppendUserTurn = Callable[..., None]
ArtifactList = Callable[..., list[dict[str, Any]]]
ConsumeDispatch = Callable[..., dict[str, Any]]
EmitDispatch = Callable[..., dict[str, Any] | None]
FeedItem = Callable[..., dict[str, Any]]
MaybeReplan = Callable[..., bool]
PostExecutionActorStage = Callable[..., tuple[str, str]]
RefreshSnapshot = Callable[..., None]


def handle_execute_plan(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
	return_runtime_request: bool = False,
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
	emit_plan_execution_dispatch: EmitDispatch,
	dispatch_artifacts: ArtifactList,
	feed_item: FeedItem,
	consume_executor_dispatch: ConsumeDispatch,
	consume_reviewer_dispatch: ConsumeDispatch,
	finalize_dispatch: ConsumeDispatch,
	maybe_replan_after_review: MaybeReplan,
	post_execution_actor_stage: PostExecutionActorStage,
) -> None:
	now = utc_now()
	model = session["model"]

	def block_plan_execution(
		title: str,
		body: str,
		*,
		presentation_key: str = "error.plan_not_ready",
		presentation_args: dict[str, Any] | None = None,
	) -> None:
		append_error(
			model,
			title,
			body,
			now,
			in_response_to_request_id=request_id,
			presentation_key=presentation_key,
			presentation_args=presentation_args,
		)

	if not request_id:
		append_error(
			model,
			"Request id required",
			"Execute plan requires a fresh controller request id.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		append_error(
			model,
			"Session changed",
			"The active session changed before this plan action was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
		)
		return
	plan_ready = model.get("planReadyRequest")
	if not isinstance(plan_ready, dict):
		block_plan_execution(
			"No plan is ready",
			"There is no current plan checkpoint to execute.",
			presentation_args={"reason": "missing_plan"},
		)
		return
	if not isinstance(model.get("acceptedIntakeSummary"), dict):
		block_plan_execution(
			"Accepted intake missing",
			"The current plan no longer has an accepted intake artifact. Refresh before executing.",
			presentation_args={"reason": "missing_intake"},
		)
		return
	if model["snapshot"].get("currentStage") != "plan_ready":
		block_plan_execution(
			"Plan changed",
			"The current session is no longer at a plan-ready checkpoint.",
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan", "reason": "stage_changed"},
		)
		return
	if not session_permissions.scope_satisfies(model["snapshot"].get("permissionScope"), "plan"):
		block_plan_execution(
			"Plan permission needed",
			"Return to Plan scope before executing this plan checkpoint.",
			presentation_key="error.permission_scope_too_low",
			presentation_args={
				"required": "plan",
				"current": model["snapshot"].get("permissionScope") or "unset",
			},
		)
		return
	if model["snapshot"].get("pendingPermissionRequest"):
		block_plan_execution(
			"Permission still pending",
			"Choose or decline the current permission request before executing the plan.",
			presentation_args={"reason": "pending_permission"},
		)
		return
	if model.get("activeClarification"):
		block_plan_execution(
			"Clarification still open",
			"Answer the current clarification before executing the plan.",
			presentation_args={"reason": "active_clarification"},
		)
		return
	if model["snapshot"].get("runState") == "running":
		block_plan_execution(
			"Work already running",
			"Wait for the current run to finish, or stop it before executing this plan.",
			presentation_args={"reason": "run_in_progress"},
		)
		return
	if not session_guards.context_matches(plan_ready.get("contextRef"), context_ref):
		append_error(
			model,
			"Plan changed",
			"The plan checkpoint changed before this action was applied. Refresh and use the current plan action.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	dispatch_refs = emit_plan_execution_dispatch(
		session,
		now,
		repo_root=repo_root,
		request_id=request_id,
	)
	if dispatch_refs is None:
		return
	existing_artifacts = list(model["snapshot"].get("recentArtifacts") or [])
	model["snapshot"]["pendingPermissionRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["permissionScope"] = "execute"
	model["activeForegroundRequestId"] = request_id or plan_ready.get("foregroundRequestId")
	model["planReadyRequest"] = None
	if auto_consume_executor:
		execution = consume_executor_dispatch(
			session,
			dispatch_refs,
			now,
			repo_root=repo_root,
			request_id=request_id,
		)
		review = (
			consume_reviewer_dispatch(
				session,
				dispatch_refs,
				now,
				repo_root=repo_root,
				request_id=request_id,
			)
			if execution.get("ok")
			else {"ok": False, "artifacts": []}
		)
		decision = (
			finalize_dispatch(
				session,
				dispatch_refs,
				now,
				repo_root=repo_root,
				request_id=request_id,
			)
			if review.get("ok")
			else {"ok": False, "artifacts": []}
		)
		replanned = maybe_replan_after_review(
			session,
			dispatch_refs,
			decision,
			now,
			repo_root=repo_root,
			request_id=request_id,
			governor_runtime=governor_runtime,
			auto_consume_executor=auto_consume_executor,
			return_runtime_request=return_runtime_request,
		)
		model["snapshot"]["recentArtifacts"] = (
			list(model["snapshot"].get("recentArtifacts") or [])
			+ decision["artifacts"]
			+ review["artifacts"]
			+ execution["artifacts"]
			+ existing_artifacts
			if replanned
			else decision["artifacts"] + review["artifacts"] + execution["artifacts"] + existing_artifacts
		)
		if not replanned:
			latest = model["feed"][-1] if model["feed"] else {}
			current_actor, current_stage = post_execution_actor_stage(execution, review, decision)
			refresh_snapshot(
				model,
				now,
				currentActor=current_actor,
				currentStage=current_stage,
				runState="idle",
				transportState="connected",
			)
			if latest.get("type") != "error":
				model["activeForegroundRequestId"] = None
	else:
		model["snapshot"]["recentArtifacts"] = dispatch_artifacts(dispatch_refs) + existing_artifacts
		model["feed"].append(
			feed_item(
				"system_status",
				"Dispatch queued",
				f"Execute plan was confirmed and dispatch truth was created at {dispatch_refs['request_ref']}.",
				authoritative=True,
				now=now,
				source_artifact_ref=dispatch_refs["request_ref"],
				turn_type="permission_action",
				in_response_to_request_id=request_id,
			)
		)
		refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="dispatch_queued",
			runState="queued",
			transportState="connected",
		)


def handle_revise_plan(
	session: dict[str, Any],
	text: str,
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	governor_runtime: str = "exec",
	append_error: AppendError,
	append_user_turn: AppendUserTurn,
	append_governor_dialogue_response: AppendGovernorDialogueResponse,
) -> None:
	now = utc_now()
	model = session["model"]
	if not request_id:
		append_error(
			model,
			"Request id required",
			"Plan revisions require a fresh controller request id.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		append_error(
			model,
			"Session changed",
			"The active session changed before this plan revision was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
		)
		return
	plan_ready = model.get("planReadyRequest")
	if not isinstance(plan_ready, dict):
		append_error(
			model,
			"No plan is ready",
			"There is no current plan checkpoint to revise.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	if model["snapshot"].get("currentStage") != "plan_ready":
		append_error(
			model,
			"Plan changed",
			"The current session is no longer at a plan-ready checkpoint.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	if not session_guards.context_matches(plan_ready.get("contextRef"), context_ref):
		append_error(
			model,
			"Plan changed",
			"The plan checkpoint changed before this action was applied. Refresh and use the current plan action.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	prompt = trim_text(text)
	if not prompt:
		append_error(
			model,
			"Revision details required",
			"Add the details you want the Governor to include in the plan.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	append_user_turn(
		model,
		now,
		title="Plan revision",
		body=prompt,
		turn_type="governor_dialogue",
		in_response_to_request_id=request_id,
	)
	model["activeForegroundRequestId"] = request_id or plan_ready.get("foregroundRequestId")
	append_governor_dialogue_response(
		session,
		f"Revise Plan version {plan_ready.get('planVersion') or 1}. User guidance: {prompt}",
		now,
		repo_root=repo_root,
		request_id=request_id,
		turn_type="governor_dialogue",
		semantic_normalized_text=prompt,
		result_stage="plan_ready",
		runtime_kind="plan",
		governor_runtime=governor_runtime,
	)
