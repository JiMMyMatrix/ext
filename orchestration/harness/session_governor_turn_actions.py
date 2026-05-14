from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from orchestration.harness.paths import resolve_paths, trim_text, utc_now


AppendCompletedGovernorDialogueResponse = Callable[..., bool]
AppendError = Callable[..., None]
CompleteGovernorGoalPlan = Callable[..., bool]
CompleteGovernorSemanticIntake = Callable[..., None]
GovernorDialogueMeta = Callable[[dict[str, Any]], dict[str, Any]]
GovernorRuntimeSettings = Callable[..., tuple[str, str]]
PendingGovernorRuntimeRequest = Callable[[dict[str, Any]], dict[str, Any] | None]
RefreshSnapshot = Callable[..., None]
RunGovernorExec = Callable[..., tuple[str, str]]


def handle_complete_governor_turn(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	runtime_request_id: str | None = None,
	body: str | None = None,
	thread_id: str | None = None,
	turn_id: str | None = None,
	item_id: str | None = None,
	runtime_source: str = "app-server",
	pending_governor_runtime_request: PendingGovernorRuntimeRequest,
	append_error: AppendError,
	complete_governor_goal_plan: CompleteGovernorGoalPlan,
	complete_governor_semantic_intake: CompleteGovernorSemanticIntake,
	append_completed_governor_dialogue_response: AppendCompletedGovernorDialogueResponse,
) -> None:
	now = utc_now()
	model = session["model"]
	pending = pending_governor_runtime_request(session)
	if not pending or not runtime_request_id or pending.get("runtimeRequestId") != runtime_request_id:
		append_error(
			model,
			"Governor runtime request changed",
			"The pending Governor runtime request changed before completion was applied.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "governor_runtime"},
		)
		return
	if pending.get("runtimeKind") == "semantic_intake":
		complete_governor_semantic_intake(
			session,
			pending,
			body or "",
			now,
			repo_root=repo_root,
			app_server_thread_id=thread_id,
			app_server_turn_id=turn_id,
			app_server_item_id=item_id,
			runtime_source=runtime_source,
		)
		session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None
		return
	if pending.get("runtimeKind") == "goal_plan":
		complete_governor_goal_plan(
			session,
			pending,
			body or "",
			now,
			repo_root=repo_root,
			app_server_thread_id=thread_id,
			app_server_turn_id=turn_id,
			app_server_item_id=item_id,
			runtime_source=runtime_source,
		)
		current_pending = pending_governor_runtime_request(session)
		if not current_pending or current_pending.get("runtimeRequestId") == runtime_request_id:
			session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None
		return
	append_completed_governor_dialogue_response(
		session,
		pending,
		body or "",
		now,
		repo_root=repo_root,
		app_server_thread_id=thread_id,
		app_server_turn_id=turn_id,
		app_server_item_id=item_id,
		runtime_source=runtime_source,
	)
	current_pending = pending_governor_runtime_request(session)
	if not current_pending or current_pending.get("runtimeRequestId") == runtime_request_id:
		session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None


def handle_fallback_governor_turn(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	runtime_request_id: str | None = None,
	reason: str | None = None,
	pending_governor_runtime_request: PendingGovernorRuntimeRequest,
	governor_dialogue_meta: GovernorDialogueMeta,
	governor_runtime_settings: GovernorRuntimeSettings,
	run_governor_exec: RunGovernorExec,
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
	complete_governor_goal_plan: CompleteGovernorGoalPlan,
	complete_governor_semantic_intake: CompleteGovernorSemanticIntake,
	append_completed_governor_dialogue_response: AppendCompletedGovernorDialogueResponse,
) -> None:
	now = utc_now()
	model = session["model"]
	pending = pending_governor_runtime_request(session)
	if not pending or not runtime_request_id or pending.get("runtimeRequestId") != runtime_request_id:
		append_error(
			model,
			"Governor runtime request changed",
			"The pending Governor runtime request changed before fallback was applied.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "governor_runtime"},
		)
		return
	governor_meta = governor_dialogue_meta(session)
	governor_meta["lastAppServerFallbackReason"] = trim_text(reason or "app-server unavailable")
	thread_id = governor_meta.get("threadId") if isinstance(governor_meta.get("threadId"), str) else None
	model_name = pending.get("model") or governor_runtime_settings(repo_root)[0]
	reasoning = pending.get("reasoning") or governor_runtime_settings(repo_root)[1]

	def create_session() -> tuple[str, str]:
		return run_governor_exec(
			[
				"codex",
				"exec",
				"--skip-git-repo-check",
				"--cd",
				str(resolve_paths(repo_root).repo_root),
				"--sandbox",
				"read-only",
				"--model",
				str(model_name),
				"-c",
				f'model_reasoning_effort="{reasoning}"',
				str(pending.get("initialPrompt") or pending.get("prompt") or ""),
			],
			repo_root=repo_root,
		)

	try:
		if thread_id:
			try:
				thread_id, body = run_governor_exec(
					[
						"codex",
						"exec",
						"resume",
						thread_id,
						str(pending.get("resumePrompt") or pending.get("prompt") or ""),
						"--model",
						str(model_name),
						"-c",
						f'model_reasoning_effort="{reasoning}"',
					],
					repo_root=repo_root,
				)
			except RuntimeError:
				governor_meta["threadId"] = None
				thread_id, body = create_session()
		else:
			thread_id, body = create_session()
	except RuntimeError:
		append_error(
			model,
			"Governor unavailable",
			"Corgi couldn't get a Governor reply right now. Please try again.",
			now,
			in_response_to_request_id=pending.get("requestId"),
		)
		refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="dialogue_failed",
			runState="idle",
			transportState="connected",
		)
		model["activeForegroundRequestId"] = None
		session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None
		return

	governor_meta["threadId"] = thread_id
	if pending.get("runtimeKind") == "semantic_intake":
		complete_governor_semantic_intake(
			session,
			pending,
			body,
			now,
			repo_root=repo_root,
			runtime_source="exec-fallback",
		)
		session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None
		return
	if pending.get("runtimeKind") == "goal_plan":
		complete_governor_goal_plan(
			session,
			pending,
			body,
			now,
			repo_root=repo_root,
			runtime_source="exec-fallback",
		)
		current_pending = pending_governor_runtime_request(session)
		if not current_pending or current_pending.get("runtimeRequestId") == runtime_request_id:
			session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None
		return
	append_completed_governor_dialogue_response(
		session,
		pending,
		body,
		now,
		repo_root=repo_root,
		runtime_source="exec-fallback",
	)
	session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None


def handle_fail_governor_turn(
	session: dict[str, Any],
	*,
	runtime_request_id: str | None = None,
	reason: str | None = None,
	pending_governor_runtime_request: PendingGovernorRuntimeRequest,
	governor_dialogue_meta: GovernorDialogueMeta,
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
) -> None:
	now = utc_now()
	model = session["model"]
	pending = pending_governor_runtime_request(session)
	if not pending or not runtime_request_id or pending.get("runtimeRequestId") != runtime_request_id:
		append_error(
			model,
			"Governor runtime request changed",
			"The pending Governor runtime request changed before the failure was applied.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "governor_runtime"},
		)
		return
	governor_meta = governor_dialogue_meta(session)
	governor_meta["lastAppServerFailureReason"] = trim_text(reason or "app-server unavailable")
	append_error(
		model,
		"Governor unavailable",
		"Corgi couldn't get a Governor reply right now. Please try again.",
		now,
		in_response_to_request_id=pending.get("requestId"),
	)
	refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="dialogue_failed",
		runState="idle",
		transportState="connected",
	)
	model["activeForegroundRequestId"] = None
	session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None
