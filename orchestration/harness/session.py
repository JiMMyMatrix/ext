from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestration.harness.intake import (
	accept_intake,
	answer_intake_clarification,
	raw_request_path,
	request_draft_path,
	start_intake,
)
from orchestration.harness import governor_runtime
from orchestration.harness import governor_semantic
from orchestration.harness import session_cli_args
from orchestration.harness import session_context
from orchestration.harness import session_execution
from orchestration.harness import session_guards
from orchestration.harness import session_governor_requests
from orchestration.harness import session_model
from orchestration.harness import session_permissions
from orchestration.harness import session_surfaces
from orchestration.harness import session_work_lifecycle
from orchestration.harness.paths import (
	default_lane,
	git_branch_name,
	repo_relative,
	resolve_paths,
	summarize,
	trim_text,
	utc_now,
)
from orchestration.harness.session_feed import (
	_artifact,
	_artifact_feed_item,
	_feed_item,
	_next_id,
	_request_card,
)


def _load_request_draft_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	return session_context.load_request_draft_summary(session, repo_root=repo_root)


def _load_accepted_intake_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	return session_context.load_accepted_intake_summary(session, repo_root=repo_root)


def _latest_dispatch_summary(
	lane: str | None, *, repo_root: str | Path | None = None
) -> dict[str, Any] | None:
	return session_context.latest_dispatch_summary(lane, repo_root=repo_root)


def _transition_summary(lane: str | None, *, repo_root: str | Path | None = None) -> dict[str, Any] | None:
	return session_context.transition_summary(lane, repo_root=repo_root)


def _governor_dialogue_context(
	session: dict[str, Any],
	prompt: str,
	*,
	repo_root: str | Path | None = None,
	semantic_intake: bool = False,
) -> dict[str, Any]:
	return session_context.governor_dialogue_context(
		session,
		prompt,
		repo_root=repo_root,
		semantic_intake=semantic_intake,
	)


def _governor_dialogue_meta(session: dict[str, Any]) -> dict[str, Any]:
	return session_context.governor_dialogue_meta(session)


def _governor_runtime_settings(repo_root: str | Path | None = None) -> tuple[str, str]:
	return governor_runtime.governor_runtime_settings(repo_root)


def _initial_governor_dialogue_prompt(
	context_prompt: str, *, repo_root: str | Path | None = None
) -> str:
	return governor_runtime.initial_governor_dialogue_prompt(context_prompt, repo_root=repo_root)


def _resume_governor_dialogue_prompt(context_prompt: str) -> str:
	return governor_runtime.resume_governor_dialogue_prompt(context_prompt)


def _initial_governor_plan_prompt(context_prompt: str) -> str:
	return governor_runtime.initial_governor_plan_prompt(context_prompt)


def _resume_governor_plan_prompt(context_prompt: str) -> str:
	return governor_runtime.resume_governor_plan_prompt(context_prompt)


def _run_governor_exec(
	command: list[str], *, repo_root: str | Path | None = None
) -> tuple[str, str]:
	return governor_runtime.run_governor_exec(command, repo_root=repo_root)


def _continue_governor_dialogue(
	session: dict[str, Any],
	prompt: str,
	*,
	repo_root: str | Path | None = None,
	runtime_kind: str = "dialogue",
) -> tuple[str, list[str], str | None]:
	context = _governor_dialogue_context(session, prompt, repo_root=repo_root)
	governor_meta = _governor_dialogue_meta(session)
	thread_id = governor_meta.get("threadId") if isinstance(governor_meta.get("threadId"), str) else None
	model_name, reasoning = _governor_runtime_settings(repo_root)

	def create_session() -> tuple[str, str]:
		initial_prompt = (
			_initial_governor_plan_prompt(context["prompt"])
			if runtime_kind == "plan"
			else _initial_governor_dialogue_prompt(context["prompt"], repo_root=repo_root)
		)
		return _run_governor_exec(
			[
				"codex",
				"exec",
				"--skip-git-repo-check",
				"--cd",
				str(resolve_paths(repo_root).repo_root),
				"--sandbox",
				"read-only",
				"--model",
				model_name,
				"-c",
				f'model_reasoning_effort="{reasoning}"',
				initial_prompt,
			],
			repo_root=repo_root,
		)

	if thread_id:
		try:
			resume_prompt = (
				_resume_governor_plan_prompt(context["prompt"])
				if runtime_kind == "plan"
				else _resume_governor_dialogue_prompt(context["prompt"])
			)
			thread_id, body = _run_governor_exec(
				[
					"codex",
					"exec",
					"resume",
					thread_id,
					resume_prompt,
					"--model",
					model_name,
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

	governor_meta["threadId"] = thread_id
	governor_meta["lastUsedAt"] = utc_now()
	return body, context["details"], context["primary_ref"]


def _pending_governor_runtime_request(session: dict[str, Any]) -> dict[str, Any] | None:
	return session_governor_requests.pending_governor_runtime_request(session)


def _build_governor_runtime_request_envelope(pending: dict[str, Any]) -> dict[str, Any]:
	return session_governor_requests.build_governor_runtime_request_envelope(pending)


def _prepare_governor_dialogue_runtime_request(
	session: dict[str, Any],
	prompt: str,
	now: str,
	*,
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
	return session_governor_requests.prepare_governor_dialogue_runtime_request(
		session,
		prompt,
		now,
		refresh_snapshot=_refresh_snapshot,
		repo_root=repo_root,
		request_id=request_id,
		turn_type=turn_type,
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=semantic_paraphrase,
		semantic_normalized_text=semantic_normalized_text,
		result_stage=result_stage,
		runtime_kind=runtime_kind,
		auto_execute_revised_plan=auto_execute_revised_plan,
		auto_consume_executor_after_plan=auto_consume_executor_after_plan,
		auto_governor_runtime_after_plan=auto_governor_runtime_after_plan,
		return_runtime_request=return_runtime_request,
	)


def _prepare_governor_semantic_intake_runtime_request(
	session: dict[str, Any],
	prompt: str,
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
) -> dict[str, Any]:
	return session_governor_requests.prepare_governor_semantic_intake_runtime_request(
		session,
		prompt,
		now,
		refresh_snapshot=_refresh_snapshot,
		repo_root=repo_root,
		request_id=request_id,
	)


def _append_completed_governor_dialogue_response(
	session: dict[str, Any],
	pending: dict[str, Any],
	body: str,
	now: str,
	*,
	repo_root: str | Path | None = None,
	app_server_thread_id: str | None = None,
	app_server_turn_id: str | None = None,
	app_server_item_id: str | None = None,
	runtime_source: str = "app-server",
) -> bool:
	model = session["model"]
	reply = trim_text(body)
	if not reply:
		_append_error(
			model,
			"Governor unavailable",
			"Corgi couldn't get a Governor reply right now. Please try again.",
			now,
			in_response_to_request_id=pending.get("requestId"),
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="dialogue_failed",
			runState="idle",
			transportState="connected",
		)
		model["activeForegroundRequestId"] = None
		return False

	governor_meta = _governor_dialogue_meta(session)
	if app_server_thread_id:
		governor_meta["appServerThreadId"] = app_server_thread_id
	if app_server_turn_id:
		governor_meta["lastAppServerTurnId"] = app_server_turn_id
	if app_server_item_id:
		governor_meta["lastAppServerItemId"] = app_server_item_id
	governor_meta["lastRuntimeSource"] = runtime_source
	governor_meta["lastUsedAt"] = utc_now()
	model["feed"].append(
		_feed_item(
			"actor_event",
			"Governor response",
			reply,
			authoritative=True,
			now=now,
			details=pending.get("details") if isinstance(pending.get("details"), list) else [],
			source_layer="governor",
			source_actor="governor",
			source_artifact_ref=pending.get("primaryRef"),
			**_semantic_provenance(
				turn_type=pending.get("turnType") or "governor_dialogue",
				semantic_input_version=pending.get("semanticInputVersion"),
				semantic_summary_ref=pending.get("semanticSummaryRef"),
				semantic_context_flags=pending.get("semanticContextFlags")
				if isinstance(pending.get("semanticContextFlags"), dict)
				else None,
				semantic_route_type=pending.get("semanticRouteType"),
				semantic_confidence=pending.get("semanticConfidence"),
				semantic_block_reason=pending.get("semanticBlockReason"),
				semantic_paraphrase=pending.get("semanticParaphrase"),
				semantic_normalized_text=pending.get("semanticNormalizedText") or pending.get("prompt"),
				in_response_to_request_id=pending.get("requestId"),
			),
		)
	)
	result_stage = pending.get("resultStage") or "dialogue_ready"
	_refresh_snapshot(
		model,
		now,
		currentActor="governor",
		currentStage=result_stage,
		runState="idle",
		transportState="connected",
	)
	if result_stage == "plan_ready":
		_set_plan_ready_request(
			session,
			now,
			foreground_request_id=pending.get("requestId"),
			repo_root=repo_root,
			plan_body=reply,
			revision_reason=pending.get("revisionReason"),
			latest_review_ref=pending.get("latestReviewRef"),
		)
		if pending.get("autoExecuteRevisedPlan"):
			if _auto_execute_revised_plan(
				session,
				now,
				repo_root=repo_root,
				request_id=f"{pending.get('requestId')}:auto-reexecute",
				governor_runtime=str(pending.get("autoGovernorRuntimeAfterPlan") or "exec"),
				auto_consume_executor=bool(pending.get("autoConsumeExecutorAfterPlan")),
				return_runtime_request=True,
			):
				return True
	else:
		model["planReadyRequest"] = None
	model["activeForegroundRequestId"] = None
	return True


def _parse_governor_semantic_intake_payload(body: str) -> dict[str, Any] | None:
	return governor_semantic.parse_governor_semantic_intake_payload(body)


def _governor_semantic_proposal(payload: dict[str, Any]) -> dict[str, Any]:
	return governor_semantic.semantic_proposal(payload)


def _governor_semantic_user_copy(payload: dict[str, Any], fallback: str) -> str:
	return governor_semantic.semantic_user_copy(payload, fallback)


def _record_rejected_governor_semantic_proposal(
	session: dict[str, Any], pending: dict[str, Any], reason: str, proposal: Any
) -> None:
	governor_semantic.record_rejected_proposal(session, pending, reason, proposal)


def _reject_governor_semantic_proposal(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reason: str,
	*,
	body: str | None = None,
	proposal: Any = None,
) -> None:
	model = session["model"]
	_record_rejected_governor_semantic_proposal(session, pending, reason, proposal)
	_append_error(
		model,
		"Request needs review",
		trim_text(body or "") or "Corgi could not safely apply the Governor proposal. Please restate the request.",
		now,
		in_response_to_request_id=pending.get("requestId"),
		presentation_key="governor_semantic.blocked",
		presentation_args={"body": trim_text(body or "") or "Corgi could not safely apply the Governor proposal."},
	)
	model["snapshot"]["pendingPermissionRequest"] = None
	model["activeClarification"] = None
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="blocked",
		runState="idle",
		transportState="connected",
	)
	model["activeForegroundRequestId"] = None


def _proposal_permission(proposal: dict[str, Any]) -> str:
	return governor_semantic.proposal_permission(proposal)


def _proposal_route(proposal: dict[str, Any]) -> str | None:
	return governor_semantic.proposal_route(proposal)


def _proposal_confidence(proposal: dict[str, Any]) -> str:
	return governor_semantic.proposal_confidence(proposal)


def _proposal_normalized_intent(proposal: dict[str, Any], fallback: str) -> str:
	return governor_semantic.proposal_normalized_intent(proposal, fallback)


def _governor_semantic_clarification_options(proposal: dict[str, Any]) -> list[dict[str, Any]]:
	return governor_semantic.clarification_options(proposal)


def _governor_semantic_initial_rejection_reason(proposal: dict[str, Any]) -> str | None:
	return governor_semantic.initial_rejection_reason(proposal)


def _apply_governor_semantic_dialogue(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reply: str,
	proposal: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	runtime_source: str,
	app_server_thread_id: str | None = None,
	app_server_turn_id: str | None = None,
	app_server_item_id: str | None = None,
) -> None:
	model = session["model"]
	if _proposal_permission(proposal) != "none" or proposal.get("needs_clarification") or proposal.get("plan_intent"):
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"governor_dialogue_proposed_state_change",
			body=reply,
			proposal=proposal,
		)
		return
	if not session_permissions.scope_satisfies(
		session_permissions.current_permission_scope(model), "observe"
	):
		permission_request = _permission_request(
			"observe",
			now,
			continuation_kind="governor_dialogue",
			pending_prompt=pending.get("prompt"),
			pending_normalized_text=_proposal_normalized_intent(proposal, pending.get("prompt") or ""),
			foreground_request_id=pending.get("requestId"),
		)
		model["snapshot"]["pendingPermissionRequest"] = permission_request
		model["feed"].append(
			_feed_item(
				"permission_request",
				permission_request["title"],
				reply or permission_request["body"],
				authoritative=True,
				now=now,
				in_response_to_request_id=pending.get("requestId"),
				presentation_key="permission.needed",
				presentation_args={
					"scope": "observe",
					"contextRef": permission_request["contextRef"],
				},
			)
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="permission_needed",
			runState="idle",
			transportState="connected",
		)
		return
	_append_completed_governor_dialogue_response(
		session,
		{
			**pending,
			"resultStage": "dialogue_ready",
			"turnType": "governor_dialogue",
			"semanticRouteType": "governor_dialogue",
			"semanticConfidence": _proposal_confidence(proposal),
			"semanticNormalizedText": _proposal_normalized_intent(proposal, pending.get("prompt") or ""),
		},
		reply,
		now,
		repo_root=repo_root,
		app_server_thread_id=app_server_thread_id,
		app_server_turn_id=app_server_turn_id,
		app_server_item_id=app_server_item_id,
		runtime_source=runtime_source,
	)


def _apply_governor_semantic_work_intent(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reply: str,
	proposal: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> None:
	model = session["model"]
	prompt = trim_text(pending.get("prompt")) or _proposal_normalized_intent(proposal, "")
	normalized = _proposal_normalized_intent(proposal, prompt)
	initial_scope = _proposal_permission(proposal)
	if initial_scope == "none":
		initial_scope = session_permissions.recommended_permission_scope(normalized)
	if initial_scope == "execute":
		# Free-text governed work still starts at planning. The Governor may
		# recommend execute for an obvious build request, but orchestration must
		# create a plan checkpoint before any execute permission can be requested.
		initial_scope = "plan"
	_supersede_pending_permission_request(model, now, request_id=pending.get("requestId"))
	envelope = start_intake(prompt, normalized_text=normalized, repo_root=repo_root)
	_reset_work_loop_state(session)
	session["meta"]["activeIntakeRef"] = envelope["intake_ref"]
	model["acceptedIntakeSummary"] = None
	model["planReadyRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["recentArtifacts"] = []
	model["snapshot"]["task"] = envelope.get("task_hint") or summarize(normalized, 60)
	model["snapshot"]["branch"] = model["snapshot"].get("branch") or git_branch_name(repo_root)
	if envelope["shell_state"] == "clarification_needed":
		clarification = {
			**envelope["clarification_request"],
			"contextRef": envelope["clarification_request"].get("contextRef")
			or envelope["clarification_request"]["id"],
		}
		model["activeClarification"] = clarification
		model["snapshot"]["pendingPermissionRequest"] = None
		model["feed"].append(
			_feed_item(
				"clarification_request",
				clarification["title"],
				reply or clarification["body"],
				authoritative=True,
				now=now,
				in_response_to_request_id=pending.get("requestId"),
				presentation_key="clarification.requested",
				presentation_args={"contextRef": clarification["contextRef"]},
			)
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="intake_shell",
			currentStage="clarification_needed",
			runState="idle",
			transportState="connected",
		)
		return
	model["activeClarification"] = None
	required_scope = initial_scope
	if required_scope == "observe":
		required_scope = "plan"
	permission_request = _permission_request(
		required_scope,
		now,
		continuation_kind="intake_acceptance",
		pending_prompt=prompt,
		pending_normalized_text=normalized,
		foreground_request_id=pending.get("requestId"),
	)
	model["snapshot"]["pendingPermissionRequest"] = permission_request
	model["feed"].append(
		_feed_item(
			"permission_request",
			permission_request["title"],
			reply or permission_request["body"],
			authoritative=True,
			now=now,
			in_response_to_request_id=pending.get("requestId"),
			presentation_key="permission.needed",
			presentation_args={
				"scope": required_scope,
				"contextRef": permission_request["contextRef"],
			},
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="permission_needed",
		runState="idle",
		transportState="connected",
	)


def _apply_governor_semantic_clarification(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reply: str,
	proposal: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> None:
	model = session["model"]
	prompt = trim_text(pending.get("prompt")) or _proposal_normalized_intent(proposal, "")
	normalized = _proposal_normalized_intent(proposal, prompt)
	envelope = start_intake(prompt, normalized_text=normalized, repo_root=repo_root)
	_reset_work_loop_state(session)
	session["meta"]["activeIntakeRef"] = envelope["intake_ref"]
	question = trim_text(proposal.get("clarification_question") if isinstance(proposal.get("clarification_question"), str) else "")
	if not question:
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"clarification_proposal_missing_question",
			body=reply,
			proposal=proposal,
		)
		return
	clarification_id = _next_id("clarification")
	clarification = {
		"id": clarification_id,
		"contextRef": clarification_id,
		"title": "Clarification needed",
		"body": question,
		"kind": "governor_semantic_intake",
		"options": _governor_semantic_clarification_options(proposal),
		"allowFreeText": True,
		"placeholder": "Add the detail the Governor needs...",
		"requestedAt": now,
	}
	model["activeClarification"] = clarification
	model["snapshot"]["pendingPermissionRequest"] = None
	model["acceptedIntakeSummary"] = None
	model["planReadyRequest"] = None
	model["feed"].append(
		_feed_item(
			"clarification_request",
			clarification["title"],
			reply or clarification["body"],
			authoritative=True,
			now=now,
			in_response_to_request_id=pending.get("requestId"),
			presentation_key="clarification.requested",
			presentation_args={"contextRef": clarification["contextRef"]},
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="governor",
		currentStage="clarification_needed",
		runState="idle",
		transportState="connected",
	)


def _apply_governor_semantic_plan_ready(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reply: str,
	proposal: dict[str, Any],
	*,
	runtime_source: str,
	app_server_thread_id: str | None = None,
	app_server_turn_id: str | None = None,
	app_server_item_id: str | None = None,
) -> None:
	model = session["model"]
	if not isinstance(model.get("acceptedIntakeSummary"), dict):
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"plan_ready_without_accepted_intake",
			body=reply,
			proposal=proposal,
		)
		return
	_append_completed_governor_dialogue_response(
		session,
		{
			**pending,
			"resultStage": "plan_ready",
			"turnType": "governed_work_intent",
			"semanticRouteType": "governed_work_intent",
			"semanticConfidence": _proposal_confidence(proposal),
			"semanticNormalizedText": _proposal_normalized_intent(proposal, pending.get("prompt") or ""),
		},
		reply,
		now,
		app_server_thread_id=app_server_thread_id,
		app_server_turn_id=app_server_turn_id,
		app_server_item_id=app_server_item_id,
		runtime_source=runtime_source,
	)


def _complete_governor_semantic_intake(
	session: dict[str, Any],
	pending: dict[str, Any],
	body: str,
	now: str,
	*,
	repo_root: str | Path | None = None,
	app_server_thread_id: str | None = None,
	app_server_turn_id: str | None = None,
	app_server_item_id: str | None = None,
	runtime_source: str = "app-server",
) -> None:
	model = session["model"]
	governor_meta = _governor_dialogue_meta(session)
	if app_server_thread_id:
		governor_meta["appServerThreadId"] = app_server_thread_id
	if app_server_turn_id:
		governor_meta["lastAppServerTurnId"] = app_server_turn_id
	if app_server_item_id:
		governor_meta["lastAppServerItemId"] = app_server_item_id
	governor_meta["lastRuntimeSource"] = runtime_source
	governor_meta["lastUsedAt"] = utc_now()
	payload = _parse_governor_semantic_intake_payload(body)
	if payload is None:
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_payload_not_json",
			body="Corgi could not read the Governor intake proposal. Please try again.",
		)
		return
	proposal = _governor_semantic_proposal(payload)
	reply = _governor_semantic_user_copy(payload, "Corgi needs a clearer request before continuing.")
	route = _proposal_route(proposal)
	rejection_reason = _governor_semantic_initial_rejection_reason(proposal)
	if rejection_reason:
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			rejection_reason,
			body=reply,
			proposal=proposal,
		)
		return
	if route == "governor_dialogue":
		_apply_governor_semantic_dialogue(
			session,
			pending,
			now,
			reply,
			proposal,
			repo_root=repo_root,
			runtime_source=runtime_source,
			app_server_thread_id=app_server_thread_id,
			app_server_turn_id=app_server_turn_id,
			app_server_item_id=app_server_item_id,
		)
	elif route == "governed_work_intent":
		_apply_governor_semantic_work_intent(
			session,
			pending,
			now,
			reply,
			proposal,
			repo_root=repo_root,
		)
	elif route == "clarification_needed":
		_apply_governor_semantic_clarification(
			session,
			pending,
			now,
			reply,
			proposal,
			repo_root=repo_root,
		)
	elif route == "permission_needed":
		recommended = _proposal_permission(proposal)
		if recommended not in {"observe", "plan", "execute"}:
			_reject_governor_semantic_proposal(
				session,
				pending,
				now,
				"semantic_intake_permission_missing_scope",
				body=reply,
				proposal=proposal,
			)
			return
		if recommended == "observe":
			_apply_governor_semantic_dialogue(
				session,
				pending,
				now,
				reply,
				{**proposal, "route_type": "governor_dialogue", "recommended_permission": "none"},
				runtime_source=runtime_source,
				app_server_thread_id=app_server_thread_id,
				app_server_turn_id=app_server_turn_id,
				app_server_item_id=app_server_item_id,
			)
		elif recommended == "execute":
			_reject_governor_semantic_proposal(
				session,
				pending,
				now,
				"semantic_intake_execute_without_plan_context",
				body=reply,
				proposal=proposal,
			)
		else:
			_apply_governor_semantic_work_intent(
				session,
				pending,
				now,
				reply,
				proposal,
				repo_root=repo_root,
			)
	elif route == "plan_ready":
		_apply_governor_semantic_plan_ready(
			session,
			pending,
			now,
			reply,
			proposal,
			runtime_source=runtime_source,
			app_server_thread_id=app_server_thread_id,
			app_server_turn_id=app_server_turn_id,
			app_server_item_id=app_server_item_id,
		)
	elif route == "block":
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_block",
			body=reply,
			proposal=proposal,
		)
	else:
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_unknown_route",
			body=reply,
			proposal=proposal,
		)


def _append_governor_dialogue_response(
	session: dict[str, Any],
	prompt: str,
	now: str,
	*,
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
	governor_runtime: str = "exec",
	auto_execute_revised_plan: bool = False,
	auto_consume_executor_after_plan: bool = False,
	auto_governor_runtime_after_plan: str = "exec",
	return_runtime_request: bool = False,
) -> bool:
	model = session["model"]
	if governor_runtime == "external":
		_prepare_governor_dialogue_runtime_request(
			session,
			prompt,
			now,
			repo_root=repo_root,
			request_id=request_id,
			turn_type=turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=semantic_paraphrase,
			semantic_normalized_text=semantic_normalized_text,
			result_stage=result_stage,
			runtime_kind=runtime_kind,
			auto_execute_revised_plan=auto_execute_revised_plan,
			auto_consume_executor_after_plan=auto_consume_executor_after_plan,
			auto_governor_runtime_after_plan=auto_governor_runtime_after_plan,
			return_runtime_request=return_runtime_request,
		)
		return True
	try:
		body, details, primary_ref = _continue_governor_dialogue(
			session,
			prompt,
			repo_root=repo_root,
			runtime_kind=runtime_kind,
		)
	except RuntimeError:
		_append_error(
			model,
			"Governor unavailable",
			"Corgi couldn't get a Governor reply right now. Please try again.",
			now,
			in_response_to_request_id=request_id,
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="dialogue_failed",
			runState="idle",
			transportState="connected",
		)
		model["activeForegroundRequestId"] = None
		return False

	model["feed"].append(
		_feed_item(
			"actor_event",
			"Governor response",
			body,
			authoritative=True,
			now=now,
			details=details,
			source_layer="governor",
			source_actor="governor",
			source_artifact_ref=primary_ref,
			**_semantic_provenance(
				turn_type=turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=semantic_paraphrase,
				semantic_normalized_text=semantic_normalized_text or prompt,
				in_response_to_request_id=request_id,
			),
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="governor",
		currentStage=result_stage,
		runState="idle",
		transportState="connected",
	)
	if result_stage == "plan_ready":
		_set_plan_ready_request(
			session,
			now,
			foreground_request_id=request_id,
			repo_root=repo_root,
			plan_body=body,
			revision_reason=model.get("currentPlanRevisionReason"),
			latest_review_ref=model.get("latestReviewRef"),
		)
		if auto_execute_revised_plan:
			if _auto_execute_revised_plan(
				session,
				now,
				repo_root=repo_root,
				request_id=f"{request_id}:auto-reexecute",
				governor_runtime=auto_governor_runtime_after_plan,
				auto_consume_executor=auto_consume_executor_after_plan,
				return_runtime_request=return_runtime_request,
			):
				return True
	else:
		model["planReadyRequest"] = None
	model["activeForegroundRequestId"] = None
	return True


def _initial_model(now: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	return session_model.initial_model(now, repo_root=repo_root)


def _normalize_session(session: dict[str, Any], now: str, *, repo_root: str | Path | None = None) -> None:
	session_model.normalize_session(session, now, repo_root=repo_root)


def load_session(repo_root: str | Path | None = None) -> dict[str, Any]:
	return session_model.load_session(repo_root)


def save_session(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	session_model.save_session(session, repo_root=repo_root)


def _refresh_snapshot(model: dict[str, Any], now: str, **overrides: Any) -> None:
	session_model.refresh_snapshot(model, now, **overrides)


def public_model(session: dict[str, Any]) -> dict[str, Any]:
	return session_model.public_model(session)


_semantic_provenance = session_surfaces.semantic_provenance
_append_user_turn = session_surfaces.append_user_turn


def _append_error(
	model: dict[str, Any],
	title: str,
	body: str,
	now: str,
	*,
	in_response_to_request_id: str | None = None,
	presentation_key: str = "error.generic",
	presentation_args: dict[str, Any] | None = None,
	source_artifact_ref: str | None = None,
) -> None:
	session_surfaces.append_error(
		model,
		title,
		body,
		now,
		refresh_snapshot=_refresh_snapshot,
		in_response_to_request_id=in_response_to_request_id,
		presentation_key=presentation_key,
		presentation_args=presentation_args,
		source_artifact_ref=source_artifact_ref,
	)


def _permission_request(
	recommended_scope: str,
	now: str,
	*,
	continuation_kind: str = "intake_acceptance",
	pending_prompt: str | None = None,
	pending_normalized_text: str | None = None,
	foreground_request_id: str | None = None,
) -> dict[str, Any]:
	return session_permissions.permission_request(
		recommended_scope,
		now,
		next_id=_next_id,
		continuation_kind=continuation_kind,
		pending_prompt=pending_prompt,
		pending_normalized_text=pending_normalized_text,
		foreground_request_id=foreground_request_id,
	)


def _build_plan_ready_request(
	model: dict[str, Any], now: str, *, foreground_request_id: str | None = None
) -> dict[str, Any] | None:
	return session_work_lifecycle.build_plan_ready_request(
		model,
		now,
		next_id=_next_id,
		foreground_request_id=foreground_request_id,
	)


def _accepted_intake_ref(session: dict[str, Any], repo_root: str | Path | None = None) -> str | None:
	return session_execution.accepted_intake_ref(session, repo_root)


def _reset_work_loop_state(session: dict[str, Any]) -> None:
	session_work_lifecycle.reset_work_loop_state(session)


def _work_index_path(work_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return session_work_lifecycle.work_index_path(work_ref, repo_root=repo_root)


def _load_work_index(work_ref: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	return session_work_lifecycle.load_work_index(work_ref, repo_root=repo_root)


def _save_work_index(work_ref: str, payload: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	session_work_lifecycle.save_work_index(work_ref, payload, repo_root=repo_root)


def _ensure_work_bundle(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
	return session_work_lifecycle.ensure_work_bundle(
		session,
		now,
		next_id=_next_id,
		repo_root=repo_root,
	)


def _write_plan_artifact(
	session: dict[str, Any],
	now: str,
	body: str,
	*,
	repo_root: str | Path | None = None,
	revision_reason: str | None = None,
	latest_review_ref: str | None = None,
) -> tuple[str, int]:
	return session_work_lifecycle.write_plan_artifact(
		session,
		now,
		body,
		next_id=_next_id,
		artifact_factory=_artifact,
		repo_root=repo_root,
		revision_reason=revision_reason,
		latest_review_ref=latest_review_ref,
	)


def _record_work_dispatch_attempt(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any] | None,
	now: str,
	*,
	repo_root: str | Path | None = None,
) -> None:
	session_work_lifecycle.record_work_dispatch_attempt(
		session,
		dispatch_refs,
		now,
		repo_root=repo_root,
	)


def _normalize_legacy_work_refs(
	items: Any,
	*,
	ref_key: str,
	migrated_at: str,
) -> list[dict[str, Any]]:
	return session_work_lifecycle.normalize_legacy_work_refs(
		items,
		ref_key=ref_key,
		migrated_at=migrated_at,
	)


def _record_work_review_and_decision(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any] | None,
	decision: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
) -> dict[str, Any] | None:
	return session_work_lifecycle.record_work_review_and_decision(
		session,
		dispatch_refs,
		decision,
		now,
		repo_root=repo_root,
	)


def _decision_needs_replan(decision_payload: dict[str, Any] | None) -> bool:
	return session_work_lifecycle.decision_needs_replan(decision_payload)


def _auto_execute_revised_plan(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
	return_runtime_request: bool = False,
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
		request_id=request_id or _next_id("request"),
		context_ref=context_ref,
		governor_runtime=governor_runtime,
		auto_consume_executor=auto_consume_executor,
		return_runtime_request=return_runtime_request,
	)
	return True


def _maybe_replan_after_review(
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
) -> bool:
	decision_payload = _record_work_review_and_decision(
		session,
		dispatch_refs,
		decision,
		now,
		repo_root=repo_root,
	)
	if not _decision_needs_replan(decision_payload):
		return False
	model = session["model"]
	work_ref = dispatch_refs.get("work_ref") if isinstance(dispatch_refs, dict) else None
	if not isinstance(work_ref, str) or not work_ref.strip():
		return False
	index = _load_work_index(work_ref, repo_root=repo_root)
	if int(index.get("revision_count") or 0) >= 2:
		index["status"] = "blocked"
		index["blocked_reason"] = "revision_limit_reached"
		index["updated_at"] = now
		_save_work_index(work_ref, index, repo_root=repo_root)
		_append_error(
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
		_refresh_snapshot(
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
	replanned = _append_governor_dialogue_response(
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
	return replanned


def _plan_execution_objective(model: dict[str, Any]) -> str:
	return session_execution.plan_execution_objective(model)


def _executor_run_ref(dispatch_ref: str) -> str:
	return session_execution.executor_run_ref(dispatch_ref)


def _plan_execution_summary(model: dict[str, Any], dispatch_ref: str) -> str:
	return session_execution.plan_execution_summary(model, dispatch_ref)


def _command_arg(value: str) -> str:
	return session_execution.command_arg(value)


def _emit_plan_execution_dispatch(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
) -> dict[str, Any] | None:
	dispatch_refs = session_execution.emit_plan_execution_dispatch(
		session,
		now,
		repo_root=repo_root,
		request_id=request_id,
		next_id=_next_id,
		append_error=_append_error,
	)
	_record_work_dispatch_attempt(session, dispatch_refs, now, repo_root=repo_root)
	return dispatch_refs


def _dispatch_artifacts(dispatch_refs: dict[str, Any], *, status: str = "queued") -> list[dict[str, Any]]:
	return session_execution.dispatch_artifacts(dispatch_refs, artifact=_artifact, status=status)


def _executor_result_artifacts(
	dispatch_refs: dict[str, Any],
	state: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
	return session_execution.executor_result_artifacts(
		dispatch_refs,
		state,
		artifact=_artifact,
		repo_root=repo_root,
	)


def _executor_report_payload(
	state: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> dict[str, Any]:
	return session_execution.executor_report_payload(state, repo_root=repo_root)


def _executor_primary_output_ref(report: dict[str, Any]) -> str | None:
	return session_execution.executor_primary_output_ref(report)


def _executor_output_body(
	output_ref: str | None,
	*,
	repo_root: str | Path | None = None,
) -> str | None:
	return session_execution.executor_output_body(output_ref, repo_root=repo_root)


def _executor_completion_body(report: dict[str, Any], output_body: str | None = None) -> str:
	return session_execution.executor_completion_body(report, output_body)


def _reviewer_completion_body(review: dict[str, Any]) -> str:
	return session_execution.reviewer_completion_body(review)


def _governor_decision_body(decision: dict[str, Any]) -> str:
	return session_execution.governor_decision_body(decision)


def _consume_executor_dispatch(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
) -> dict[str, Any]:
	return session_execution.consume_executor_dispatch(
		session,
		dispatch_refs,
		now,
		feed_item=_feed_item,
		artifact=_artifact,
		append_error=_append_error,
		repo_root=repo_root,
		request_id=request_id,
	)


def _consume_reviewer_dispatch(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
) -> dict[str, Any]:
	return session_execution.consume_reviewer_dispatch(
		session,
		dispatch_refs,
		now,
		feed_item=_feed_item,
		artifact=_artifact,
		append_error=_append_error,
		repo_root=repo_root,
		request_id=request_id,
	)


def _finalize_dispatch(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
) -> dict[str, Any]:
	return session_execution.finalize_dispatch(
		session,
		dispatch_refs,
		now,
		feed_item=_feed_item,
		artifact=_artifact,
		append_error=_append_error,
		repo_root=repo_root,
		request_id=request_id,
	)


def _post_execution_actor_stage(*results: dict[str, Any]) -> tuple[str, str]:
	return session_execution.post_execution_actor_stage(*results)


def _set_plan_ready_request(
	session: dict[str, Any],
	now: str,
	*,
	foreground_request_id: str | None = None,
	advance_version: bool = True,
	repo_root: str | Path | None = None,
	plan_body: str | None = None,
	revision_reason: str | None = None,
	latest_review_ref: str | None = None,
) -> None:
	model = session["model"]
	if advance_version:
		model["planVersion"] = int(model.get("planVersion") or 0) + 1
	else:
		model["planVersion"] = int(model.get("planVersion") or 1)
	if plan_body is not None:
		plan_ref, _ = _write_plan_artifact(
			session,
			now,
			plan_body,
			repo_root=repo_root,
			revision_reason=revision_reason,
			latest_review_ref=latest_review_ref,
		)
		model["currentPlanRef"] = plan_ref
		model["currentPlanRevisionReason"] = revision_reason
		model["latestReviewRef"] = latest_review_ref
	model["planReadyRequest"] = _build_plan_ready_request(
		model, now, foreground_request_id=foreground_request_id
	)


def _supersede_pending_permission_request(
	model: dict[str, Any], now: str, *, request_id: str | None = None
) -> None:
	pending = model["snapshot"].get("pendingPermissionRequest")
	if not pending:
		return
	model["snapshot"]["pendingPermissionRequest"] = None
	model["feed"].append(
		_feed_item(
			"system_status",
			"Pending permission request superseded",
			"A new request replaced the previous permission checkpoint.",
			authoritative=True,
			now=now,
			in_response_to_request_id=request_id,
			presentation_key="permission.superseded",
		)
	)


def _accept_pending_intake(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	permission_scope: str,
	request_id: str | None = None,
	turn_type: str = "system",
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
) -> bool:
	model = session["model"]
	current_foreground_request_id = model.get("activeForegroundRequestId") or request_id
	intake_ref = session["meta"].get("activeIntakeRef")
	pending_permission = model["snapshot"].get("pendingPermissionRequest")
	previous_permission_scope = model["snapshot"].get("permissionScope") or "unset"
	if not intake_ref or not pending_permission:
		_append_error(
			model,
			"No permission request is active",
			"There is no permission request to apply.",
			now,
			in_response_to_request_id=request_id,
		)
		return False

	branch = model["snapshot"].get("branch") or git_branch_name(repo_root)
	lane = model["snapshot"].get("lane") or default_lane(branch)
	task = model["snapshot"].get("task")
	envelope = accept_intake(intake_ref, lane=lane, branch=branch, task=task, repo_root=repo_root)

	artifacts = [
		_artifact(
			repo_relative(raw_request_path(intake_ref, repo_root=repo_root), repo_root),
			summary="Canonical raw human input.",
			authoritative=True,
			status="recorded",
		),
		_artifact(
			repo_relative(request_draft_path(intake_ref, repo_root=repo_root), repo_root),
			summary="Intake shell draft. Informational only.",
			authoritative=False,
			status="draft",
		),
		_artifact(
			envelope["accepted_intake_ref"],
			summary="Canonical accepted intake for downstream governor consumption.",
			authoritative=True,
			status="accepted",
		),
	]

	summary = envelope["accepted_summary"]
	if permission_scope == "execute":
		summary = f"{summary} Execute permission is active for this session."

	model["acceptedIntakeSummary"] = {
		"title": "Accepted intake summary",
		"body": summary,
	}
	model["snapshot"]["pendingPermissionRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["lane"] = envelope["lane"]
	model["snapshot"]["branch"] = envelope["branch"]
	model["snapshot"]["task"] = envelope["task"]
	model["snapshot"]["recentArtifacts"] = artifacts
	model["snapshot"]["permissionScope"] = permission_scope
	if permission_scope != "plan":
		model["planReadyRequest"] = None
	model["activeForegroundRequestId"] = (
		current_foreground_request_id if permission_scope == "execute" else None
	)
	dispatch_refs = None
	replanned = False
	if permission_scope == "execute":
		dispatch_refs = _emit_plan_execution_dispatch(
			session,
			now,
			repo_root=repo_root,
			request_id=request_id,
		)
		if dispatch_refs is None:
			model["snapshot"]["pendingPermissionRequest"] = pending_permission
			model["snapshot"]["permissionScope"] = previous_permission_scope
			_refresh_snapshot(
				model,
				now,
				currentActor="orchestration",
				currentStage="permission_needed",
				runState="idle",
				transportState="connected",
			)
			return False
		if auto_consume_executor:
			execution = _consume_executor_dispatch(
				session,
				dispatch_refs,
				now,
				repo_root=repo_root,
				request_id=request_id,
			)
			review = (
				_consume_reviewer_dispatch(
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
				_finalize_dispatch(
					session,
					dispatch_refs,
					now,
					repo_root=repo_root,
					request_id=request_id,
				)
				if review.get("ok")
				else {"ok": False, "artifacts": []}
			)
			replanned = _maybe_replan_after_review(
				session,
				dispatch_refs,
				decision,
				now,
				repo_root=repo_root,
				request_id=request_id,
				governor_runtime=governor_runtime,
			)
			model["snapshot"]["recentArtifacts"] = (
				list(model["snapshot"].get("recentArtifacts") or [])
				+ decision["artifacts"]
				+ review["artifacts"]
				+ execution["artifacts"]
				+ artifacts
				if replanned
				else decision["artifacts"] + review["artifacts"] + execution["artifacts"] + artifacts
			)
		else:
			model["snapshot"]["recentArtifacts"] = _dispatch_artifacts(dispatch_refs) + artifacts
	if permission_scope != "execute" or not auto_consume_executor:
		model["feed"].append(
			_feed_item(
				"system_status",
				"Dispatch queued"
				if permission_scope == "execute"
				else "Accepted and ready",
				f"Execute permission is active and dispatch truth was created at {dispatch_refs['request_ref']}."
				if permission_scope == "execute" and dispatch_refs
				else summary,
				authoritative=True,
				now=now,
				source_artifact_ref=dispatch_refs["request_ref"]
				if permission_scope == "execute" and dispatch_refs
				else None,
				**_semantic_provenance(
					turn_type=turn_type,
					semantic_input_version=semantic_input_version,
					semantic_summary_ref=semantic_summary_ref,
					semantic_context_flags=semantic_context_flags,
					semantic_route_type=semantic_route_type,
					semantic_confidence=semantic_confidence,
					semantic_block_reason=semantic_block_reason,
					semantic_paraphrase=semantic_paraphrase,
					semantic_normalized_text=semantic_normalized_text,
					in_response_to_request_id=request_id,
				),
			)
		)
	if not replanned:
		_refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="dispatch_queued" if permission_scope == "execute" else "intake_accepted",
			runState="queued" if permission_scope == "execute" else "idle",
			transportState="connected",
		)
	if permission_scope == "execute" and auto_consume_executor and not replanned:
		latest = model["feed"][-1] if model["feed"] else {}
		current_actor, current_stage = _post_execution_actor_stage(execution, review, decision)
		_refresh_snapshot(
			model,
			now,
			currentActor=current_actor,
			currentStage=current_stage,
			runState="idle",
			transportState="connected",
		)
		if latest.get("type") != "error":
			model["activeForegroundRequestId"] = None
	if permission_scope == "plan":
		return _append_governor_dialogue_response(
			session,
			(
				"Produce the bounded Plan-ready checkpoint for the accepted request. "
				"Do not execute or deeply analyze yet. "
				f"Accepted request: {summary}"
			),
			now,
			repo_root=repo_root,
			request_id=request_id,
			turn_type=turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=semantic_paraphrase,
			semantic_normalized_text=semantic_normalized_text or summary,
			result_stage="plan_ready",
			runtime_kind="plan",
			governor_runtime=governor_runtime,
		)
	return True


def _apply_governor_dialogue_permission(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
	permission_scope: str,
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
	governor_runtime: str = "exec",
) -> bool:
	model = session["model"]
	pending_permission = model["snapshot"].get("pendingPermissionRequest")
	if not pending_permission:
		_append_error(
			model,
			"No permission request is active",
			"There is no permission request to apply.",
			now,
			in_response_to_request_id=request_id,
		)
		return False

	prompt = trim_text(
		pending_permission.get("pendingNormalizedText")
		or pending_permission.get("pendingPrompt")
	)
	if not prompt:
		_append_error(
			model,
			"Pending dialogue request unavailable",
			"Corgi lost the pending Governor request before this permission choice was applied. Send the request again.",
			now,
			in_response_to_request_id=request_id,
		)
		return False

	model["snapshot"]["permissionScope"] = permission_scope
	model["snapshot"]["pendingPermissionRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	continuation_request_id = (
		pending_permission.get("foregroundRequestId")
		or model.get("activeForegroundRequestId")
		or request_id
	)
	model["activeForegroundRequestId"] = continuation_request_id
	return _append_governor_dialogue_response(
		session,
		prompt,
		now,
		repo_root=repo_root,
		request_id=continuation_request_id,
		turn_type=turn_type,
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=semantic_paraphrase,
		semantic_normalized_text=semantic_normalized_text,
		governor_runtime=governor_runtime,
	)


def handle_submit_prompt(
	session: dict[str, Any],
	text: str,
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	semantic_mode: str | None = None,
	turn_type: str | None = None,
	normalized_text: str | None = None,
	paraphrase: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this request was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
		)
		return
	prompt = trim_text(text)
	if not prompt:
		_append_error(
			model,
			"Prompt required",
			"Enter a prompt before sending it.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	if semantic_mode == "governor-first":
		if request_id is not None:
			model["activeForegroundRequestId"] = request_id
		_append_user_turn(
			model,
			now,
			title="Prompt submitted",
			body=prompt,
			turn_type="governor_dialogue",
			in_response_to_request_id=request_id,
		)
		_prepare_governor_semantic_intake_runtime_request(
			session,
			prompt,
			now,
			repo_root=repo_root,
			request_id=request_id,
		)
		return

	semantic_prompt = trim_text(normalized_text) or prompt
	resolved_turn_type = turn_type or (
		semantic_route_type
		if semantic_route_type in ("governor_dialogue", "governed_work_intent")
		else None
	)
	if resolved_turn_type not in ("governor_dialogue", "governed_work_intent"):
		_append_error(
			model,
			"Semantic route required",
			"The controller must classify this prompt before dispatch.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.semantic_route_required",
		)
		return
	if request_id is not None:
		model["activeForegroundRequestId"] = request_id
	if resolved_turn_type == "governor_dialogue":
		if not session_permissions.scope_satisfies(
			session_permissions.current_permission_scope(model), "observe"
		):
			_append_user_turn(
				model,
				now,
				title="Governor question",
				body=prompt,
				turn_type=resolved_turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_prompt,
				in_response_to_request_id=request_id,
			)
			permission_request = _permission_request(
				"observe",
				now,
				continuation_kind="governor_dialogue",
				pending_prompt=prompt,
				pending_normalized_text=semantic_prompt,
				foreground_request_id=request_id,
			)
			model["snapshot"]["pendingPermissionRequest"] = permission_request
			model["feed"].append(
				_feed_item(
					"permission_request",
					permission_request["title"],
					permission_request["body"],
					authoritative=True,
					now=now,
					**_semantic_provenance(
						turn_type=resolved_turn_type,
						semantic_input_version=semantic_input_version,
						semantic_summary_ref=semantic_summary_ref,
						semantic_context_flags=semantic_context_flags,
						semantic_route_type=semantic_route_type,
						semantic_confidence=semantic_confidence,
						semantic_block_reason=semantic_block_reason,
						semantic_paraphrase=paraphrase,
						semantic_normalized_text=semantic_prompt,
						in_response_to_request_id=request_id,
					),
					presentation_key="permission.needed",
					presentation_args={
						"scope": "observe",
						"contextRef": permission_request["contextRef"],
					},
				)
			)
			_refresh_snapshot(
				model,
				now,
				currentActor="orchestration",
				currentStage="permission_needed",
				runState="idle",
				transportState="connected",
			)
			return

		_append_user_turn(
			model,
			now,
			title="Governor question",
			body=prompt,
			turn_type=resolved_turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_prompt,
			in_response_to_request_id=request_id,
		)
		dialogue_result_stage = (
			"plan_ready"
			if model["snapshot"].get("currentStage") == "plan_ready"
			and model.get("acceptedIntakeSummary")
			else "dialogue_ready"
		)
		_append_governor_dialogue_response(
			session,
			semantic_prompt,
			now,
			repo_root=repo_root,
			request_id=request_id,
			turn_type=resolved_turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_prompt,
			result_stage=dialogue_result_stage,
			runtime_kind="plan" if dialogue_result_stage == "plan_ready" else "dialogue",
			governor_runtime=governor_runtime,
		)
		return

	if session_permissions.should_request_execute_for_accepted_continuation(model, semantic_context_flags):
		_append_user_turn(
			model,
			now,
			title="Prompt submitted",
			body=prompt,
			turn_type=resolved_turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_prompt,
			in_response_to_request_id=request_id,
		)
		permission_request = _permission_request(
			"execute",
			now,
			continuation_kind="intake_acceptance",
			pending_prompt=prompt,
			pending_normalized_text=semantic_prompt,
			foreground_request_id=request_id,
		)
		model["activeClarification"] = None
		model["snapshot"]["pendingPermissionRequest"] = permission_request
		model["snapshot"]["pendingInterrupt"] = None
		model["feed"].append(
			_feed_item(
				"permission_request",
				permission_request["title"],
				permission_request["body"],
				authoritative=True,
				now=now,
				**_semantic_provenance(
					turn_type=resolved_turn_type,
					semantic_input_version=semantic_input_version,
					semantic_summary_ref=semantic_summary_ref,
					semantic_context_flags=semantic_context_flags,
					semantic_route_type=semantic_route_type,
					semantic_confidence=semantic_confidence,
					semantic_block_reason=semantic_block_reason,
					semantic_paraphrase=paraphrase,
					semantic_normalized_text=semantic_prompt,
					in_response_to_request_id=request_id,
				),
				presentation_key="permission.needed",
				presentation_args={
					"scope": "execute",
					"contextRef": permission_request["contextRef"],
				},
			)
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="permission_needed",
			runState="idle",
			transportState="connected",
		)
		return

	_supersede_pending_permission_request(model, now, request_id=request_id)
	envelope = start_intake(prompt, normalized_text=semantic_prompt, repo_root=repo_root)
	_reset_work_loop_state(session)
	session["meta"]["activeIntakeRef"] = envelope["intake_ref"]

	_append_user_turn(
		model,
		now,
		title="Prompt submitted",
		body=prompt,
		turn_type=resolved_turn_type,
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=paraphrase,
		semantic_normalized_text=semantic_prompt,
		in_response_to_request_id=request_id,
	)
	model["feed"].append(
		_feed_item(
			"shell_event",
			"Intake shell normalized the request",
			envelope["draft_summary"],
			authoritative=False,
			now=now,
			details=[
				"Request drafts are informational only.",
				"Intake acceptance remains orchestration-owned.",
			],
			activity={"kind": "status", "state": "completed", "summary": "Draft updated"},
			**_semantic_provenance(
				turn_type=resolved_turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_prompt,
				in_response_to_request_id=request_id,
			),
		)
	)
	model["acceptedIntakeSummary"] = None
	model["planReadyRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["recentArtifacts"] = []
	model["snapshot"]["task"] = envelope.get("task_hint") or summarize(semantic_prompt, 60)
	model["snapshot"]["branch"] = model["snapshot"].get("branch") or git_branch_name(repo_root)

	if envelope["shell_state"] == "clarification_needed":
		clarification = {
			**envelope["clarification_request"],
			"contextRef": envelope["clarification_request"].get("contextRef")
			or envelope["clarification_request"]["id"],
		}
		model["activeClarification"] = clarification
		model["snapshot"]["pendingPermissionRequest"] = None
		model["feed"].append(
			_feed_item(
				"clarification_request",
				clarification["title"],
				clarification["body"],
				authoritative=True,
				now=now,
				**_semantic_provenance(
					turn_type=resolved_turn_type,
					semantic_input_version=semantic_input_version,
					semantic_summary_ref=semantic_summary_ref,
					semantic_context_flags=semantic_context_flags,
					semantic_route_type=semantic_route_type,
					semantic_confidence=semantic_confidence,
					semantic_block_reason=semantic_block_reason,
					semantic_paraphrase=paraphrase,
					semantic_normalized_text=semantic_prompt,
					in_response_to_request_id=request_id,
				),
				presentation_key="clarification.requested",
				presentation_args={"contextRef": clarification["contextRef"]},
			)
		)
		_refresh_snapshot(
			model,
			now,
			currentActor="intake_shell",
			currentStage="clarification_needed",
			runState="idle",
			transportState="connected",
		)
		return

	model["activeClarification"] = None
	required_scope = session_permissions.recommended_permission_scope(semantic_prompt)
	if session_permissions.scope_satisfies(
		session_permissions.current_permission_scope(model), required_scope
	):
		model["snapshot"]["pendingPermissionRequest"] = _permission_request(
			required_scope,
			now,
			continuation_kind="intake_acceptance",
			pending_prompt=prompt,
			pending_normalized_text=semantic_prompt,
			foreground_request_id=model.get("activeForegroundRequestId") or request_id,
		)
		_accept_pending_intake(
			session,
			now,
			repo_root=repo_root,
			permission_scope=session_permissions.current_permission_scope(model),
			request_id=request_id,
			turn_type=resolved_turn_type,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_prompt,
			governor_runtime=governor_runtime,
			auto_consume_executor=auto_consume_executor,
		)
		return

	model["snapshot"]["pendingPermissionRequest"] = _permission_request(
		required_scope,
		now,
		continuation_kind="intake_acceptance",
		pending_prompt=prompt,
		pending_normalized_text=semantic_prompt,
		foreground_request_id=model.get("activeForegroundRequestId") or request_id,
	)
	model["feed"].append(
		_feed_item(
			"permission_request",
			"Permission needed",
			model["snapshot"]["pendingPermissionRequest"]["body"],
			authoritative=True,
			now=now,
			**_semantic_provenance(
				turn_type=resolved_turn_type,
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_prompt,
				in_response_to_request_id=request_id,
			),
			presentation_key="permission.needed",
			presentation_args={
				"scope": required_scope,
				"contextRef": model["snapshot"]["pendingPermissionRequest"]["contextRef"],
			},
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="permission_needed",
		runState="idle",
		transportState="connected",
	)


def handle_answer_clarification(
	session: dict[str, Any],
	text: str,
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	normalized_text: str | None = None,
	paraphrase: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
) -> None:
	now = utc_now()
	model = session["model"]
	if model.get("activeForegroundRequestId") is None and request_id is not None:
		model["activeForegroundRequestId"] = request_id
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this clarification was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
		)
		return
	intake_ref = session["meta"].get("activeIntakeRef")
	if not intake_ref or not model.get("activeClarification"):
		_append_error(
			model,
			"No clarification is active",
			"There is no active clarification request to answer.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	expected_context_ref = model["activeClarification"].get("contextRef") or model["activeClarification"].get("id")
	if not session_guards.context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Clarification changed",
			"The clarification changed before this answer was applied. Refresh and answer the current clarification instead.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "clarification"},
		)
		return

	answer = trim_text(text)
	if not answer:
		_append_error(
			model,
			"Clarification answer required",
			"Enter a clarification answer before sending it.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	semantic_answer = trim_text(normalized_text) or answer
	envelope = answer_intake_clarification(
		intake_ref,
		answer,
		normalized_text=semantic_answer,
		repo_root=repo_root,
	)
	_append_user_turn(
		model,
		now,
		title="Clarification answered",
		body=answer,
		turn_type="clarification_reply",
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=paraphrase,
		semantic_normalized_text=semantic_answer,
		in_response_to_request_id=request_id,
	)
	model["feed"].append(
		_feed_item(
			"shell_event",
			"Draft is ready for permission review",
			"Intake updated the draft and handed it back for permission selection.",
			authoritative=False,
			now=now,
			activity={"kind": "status", "state": "completed", "summary": "Ready for permission"},
			**_semantic_provenance(
				turn_type="clarification_reply",
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_answer,
				in_response_to_request_id=request_id,
			),
		)
	)
	model["activeClarification"] = None
	required_scope = session_permissions.recommended_permission_scope(semantic_answer)
	if session_permissions.scope_satisfies(
		session_permissions.current_permission_scope(model), required_scope
	):
		model["snapshot"]["pendingPermissionRequest"] = _permission_request(
			required_scope,
			now,
			continuation_kind="intake_acceptance",
			pending_prompt=text,
			pending_normalized_text=semantic_answer,
			foreground_request_id=model.get("activeForegroundRequestId") or request_id,
		)
		_accept_pending_intake(
			session,
			now,
			repo_root=repo_root,
			permission_scope=session_permissions.current_permission_scope(model),
			request_id=request_id,
			turn_type="clarification_reply",
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=semantic_answer,
			governor_runtime=governor_runtime,
			auto_consume_executor=auto_consume_executor,
		)
		return
	model["snapshot"]["pendingPermissionRequest"] = _permission_request(
		required_scope,
		now,
		continuation_kind="intake_acceptance",
		pending_prompt=text,
		pending_normalized_text=semantic_answer,
		foreground_request_id=model.get("activeForegroundRequestId") or request_id,
	)
	model["feed"].append(
		_feed_item(
			"permission_request",
			"Permission needed",
			model["snapshot"]["pendingPermissionRequest"]["body"],
			authoritative=True,
			now=now,
			**_semantic_provenance(
				turn_type="clarification_reply",
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=paraphrase,
				semantic_normalized_text=semantic_answer,
				in_response_to_request_id=request_id,
			),
			presentation_key="permission.needed",
			presentation_args={
				"scope": required_scope,
				"contextRef": model["snapshot"]["pendingPermissionRequest"]["contextRef"],
			},
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="permission_needed",
		runState="idle",
		transportState="connected",
	)


def handle_set_permission_scope(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	permission_scope: str | None = None,
	text: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	governor_runtime: str = "exec",
	auto_consume_executor: bool = False,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this permission choice was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
		)
		return
	raw_text = trim_text(text or "")
	if raw_text:
		_append_user_turn(
			model,
			now,
			title="Permission selected",
			body=raw_text,
			turn_type="permission_action",
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=semantic_paraphrase,
			semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text,
			in_response_to_request_id=request_id,
		)
	expected_context_ref = (
		model["snapshot"]["pendingPermissionRequest"].get("contextRef")
		if isinstance(model["snapshot"].get("pendingPermissionRequest"), dict)
		else None
	)
	if not session_guards.context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Permission changed",
			"The permission request changed before this action was applied. Refresh and confirm the current permission surface.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "permission"},
		)
		return
	if permission_scope not in {"observe", "plan", "execute"}:
		_append_error(
			model,
			"Permission scope required",
			"Choose Observe, Plan, or Execute to continue.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	pending_permission = (
		model["snapshot"].get("pendingPermissionRequest")
		if isinstance(model["snapshot"].get("pendingPermissionRequest"), dict)
		else {}
	)
	recommended_scope = pending_permission.get("recommendedScope") or "plan"
	if not session_permissions.scope_satisfies(permission_scope, recommended_scope):
		_append_error(
			model,
			"Permission scope too low",
			f"Choose {session_permissions.format_permission_scope(recommended_scope)} or higher to continue this request.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.permission_scope_too_low",
			presentation_args={
				"requiredScope": recommended_scope,
				"selectedScope": permission_scope,
			},
		)
		return
	continuation_kind = (
		model["snapshot"]["pendingPermissionRequest"].get("continuationKind")
		if isinstance(model["snapshot"].get("pendingPermissionRequest"), dict)
		else None
	)
	continuation_request_id = (
		model["snapshot"]["pendingPermissionRequest"].get("foregroundRequestId")
		if isinstance(model["snapshot"].get("pendingPermissionRequest"), dict)
		else None
	) or model.get("activeForegroundRequestId") or request_id
	if continuation_kind == "governor_dialogue":
		_apply_governor_dialogue_permission(
			session,
			now,
			repo_root=repo_root,
			permission_scope=permission_scope,
			request_id=request_id,
			turn_type="governor_dialogue",
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=semantic_paraphrase,
			semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text or None,
			governor_runtime=governor_runtime,
		)
		return
	if continuation_kind == "plan_execution":
		dispatch_refs = _emit_plan_execution_dispatch(
			session,
			now,
			repo_root=repo_root,
			request_id=continuation_request_id,
		)
		if dispatch_refs is None:
			return
		existing_artifacts = list(model["snapshot"].get("recentArtifacts") or [])
		model["snapshot"]["permissionScope"] = permission_scope
		model["snapshot"]["pendingPermissionRequest"] = None
		model["snapshot"]["pendingInterrupt"] = None
		model["snapshot"]["currentActor"] = "orchestration"
		model["snapshot"]["currentStage"] = "dispatch_queued"
		model["snapshot"]["runState"] = "queued"
		model["snapshot"]["transportState"] = "connected"
		model["snapshot"]["snapshotFreshness"] = {"receivedAt": now}
		model["activeClarification"] = None
		model["activeForegroundRequestId"] = continuation_request_id
		model["planReadyRequest"] = None
		if auto_consume_executor:
			execution = _consume_executor_dispatch(
				session,
				dispatch_refs,
				now,
				repo_root=repo_root,
				request_id=continuation_request_id,
			)
			review = (
				_consume_reviewer_dispatch(
					session,
					dispatch_refs,
					now,
					repo_root=repo_root,
					request_id=continuation_request_id,
				)
				if execution.get("ok")
				else {"ok": False, "artifacts": []}
			)
			decision = (
				_finalize_dispatch(
					session,
					dispatch_refs,
					now,
					repo_root=repo_root,
					request_id=continuation_request_id,
				)
				if review.get("ok")
				else {"ok": False, "artifacts": []}
			)
			replanned = _maybe_replan_after_review(
				session,
				dispatch_refs,
				decision,
				now,
				repo_root=repo_root,
				request_id=continuation_request_id,
				governor_runtime=governor_runtime,
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
				current_actor, current_stage = _post_execution_actor_stage(execution, review, decision)
				_refresh_snapshot(
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
			model["snapshot"]["recentArtifacts"] = _dispatch_artifacts(dispatch_refs) + existing_artifacts
			model["feed"].append(
				_feed_item(
					"system_status",
					"Dispatch queued",
					f"Execute permission is active and dispatch truth was created at {dispatch_refs['request_ref']}.",
					authoritative=True,
					now=now,
					source_artifact_ref=dispatch_refs["request_ref"],
					**_semantic_provenance(
						turn_type="permission_action",
						semantic_input_version=semantic_input_version,
						semantic_summary_ref=semantic_summary_ref,
						semantic_context_flags=semantic_context_flags,
						semantic_route_type=semantic_route_type,
						semantic_confidence=semantic_confidence,
						semantic_block_reason=semantic_block_reason,
						semantic_paraphrase=semantic_paraphrase,
						semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text or None,
						in_response_to_request_id=continuation_request_id,
					),
				)
			)
		return
	_accept_pending_intake(
		session,
		now,
		repo_root=repo_root,
		permission_scope=permission_scope,
		request_id=continuation_request_id,
		turn_type="permission_action",
		semantic_input_version=semantic_input_version,
		semantic_summary_ref=semantic_summary_ref,
		semantic_context_flags=semantic_context_flags,
		semantic_route_type=semantic_route_type,
		semantic_confidence=semantic_confidence,
		semantic_block_reason=semantic_block_reason,
		semantic_paraphrase=semantic_paraphrase,
		semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text or None,
		governor_runtime=governor_runtime,
		auto_consume_executor=auto_consume_executor,
	)


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
		_append_error(
			model,
			title,
			body,
			now,
			in_response_to_request_id=request_id,
			presentation_key=presentation_key,
			presentation_args=presentation_args,
		)

	if not request_id:
		_append_error(
			model,
			"Request id required",
			"Execute plan requires a fresh controller request id.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
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
		_append_error(
			model,
			"Plan changed",
			"The plan checkpoint changed before this action was applied. Refresh and use the current plan action.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	dispatch_refs = _emit_plan_execution_dispatch(
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
		execution = _consume_executor_dispatch(
			session,
			dispatch_refs,
			now,
			repo_root=repo_root,
			request_id=request_id,
		)
		review = (
			_consume_reviewer_dispatch(
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
			_finalize_dispatch(
				session,
				dispatch_refs,
				now,
				repo_root=repo_root,
				request_id=request_id,
			)
			if review.get("ok")
			else {"ok": False, "artifacts": []}
		)
		replanned = _maybe_replan_after_review(
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
			current_actor, current_stage = _post_execution_actor_stage(execution, review, decision)
			_refresh_snapshot(
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
		model["snapshot"]["recentArtifacts"] = _dispatch_artifacts(dispatch_refs) + existing_artifacts
		model["feed"].append(
			_feed_item(
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
		_refresh_snapshot(
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
) -> None:
	now = utc_now()
	model = session["model"]
	if not request_id:
		_append_error(
			model,
			"Request id required",
			"Plan revisions require a fresh controller request id.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "plan"},
		)
		return
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
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
		_append_error(
			model,
			"No plan is ready",
			"There is no current plan checkpoint to revise.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	if model["snapshot"].get("currentStage") != "plan_ready":
		_append_error(
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
		_append_error(
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
		_append_error(
			model,
			"Revision details required",
			"Add the details you want the Governor to include in the plan.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	_append_user_turn(
		model,
		now,
		title="Plan revision",
		body=prompt,
		turn_type="governor_dialogue",
		in_response_to_request_id=request_id,
	)
	model["activeForegroundRequestId"] = request_id or plan_ready.get("foregroundRequestId")
	_append_governor_dialogue_response(
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
) -> None:
	now = utc_now()
	model = session["model"]
	pending = _pending_governor_runtime_request(session)
	if not pending or not runtime_request_id or pending.get("runtimeRequestId") != runtime_request_id:
		_append_error(
			model,
			"Governor runtime request changed",
			"The pending Governor runtime request changed before completion was applied.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "governor_runtime"},
		)
		return
	if pending.get("runtimeKind") == "semantic_intake":
		_complete_governor_semantic_intake(
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
	_append_completed_governor_dialogue_response(
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
	current_pending = _pending_governor_runtime_request(session)
	if not current_pending or current_pending.get("runtimeRequestId") == runtime_request_id:
		session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None


def handle_fallback_governor_turn(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	runtime_request_id: str | None = None,
	reason: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	pending = _pending_governor_runtime_request(session)
	if not pending or not runtime_request_id or pending.get("runtimeRequestId") != runtime_request_id:
		_append_error(
			model,
			"Governor runtime request changed",
			"The pending Governor runtime request changed before fallback was applied.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "governor_runtime"},
		)
		return
	governor_meta = _governor_dialogue_meta(session)
	governor_meta["lastAppServerFallbackReason"] = trim_text(reason or "app-server unavailable")
	thread_id = governor_meta.get("threadId") if isinstance(governor_meta.get("threadId"), str) else None
	model_name = pending.get("model") or _governor_runtime_settings(repo_root)[0]
	reasoning = pending.get("reasoning") or _governor_runtime_settings(repo_root)[1]

	def create_session() -> tuple[str, str]:
		return _run_governor_exec(
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
				thread_id, body = _run_governor_exec(
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
		_append_error(
			model,
			"Governor unavailable",
			"Corgi couldn't get a Governor reply right now. Please try again.",
			now,
			in_response_to_request_id=pending.get("requestId"),
		)
		_refresh_snapshot(
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
		_complete_governor_semantic_intake(
			session,
			pending,
			body,
			now,
			repo_root=repo_root,
			runtime_source="exec-fallback",
		)
		session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None
		return
	_append_completed_governor_dialogue_response(
		session,
		pending,
		body,
		now,
		runtime_source="exec-fallback",
	)
	session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None


def handle_fail_governor_turn(
	session: dict[str, Any],
	*,
	runtime_request_id: str | None = None,
	reason: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	pending = _pending_governor_runtime_request(session)
	if not pending or not runtime_request_id or pending.get("runtimeRequestId") != runtime_request_id:
		_append_error(
			model,
			"Governor runtime request changed",
			"The pending Governor runtime request changed before the failure was applied.",
			now,
			presentation_key="error.stale_context",
			presentation_args={"kind": "governor_runtime"},
		)
		return
	governor_meta = _governor_dialogue_meta(session)
	governor_meta["lastAppServerFailureReason"] = trim_text(reason or "app-server unavailable")
	_append_error(
		model,
		"Governor unavailable",
		"Corgi couldn't get a Governor reply right now. Please try again.",
		now,
		in_response_to_request_id=pending.get("requestId"),
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="dialogue_failed",
		runState="idle",
		transportState="connected",
	)
	model["activeForegroundRequestId"] = None
	session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = None


def handle_decline_permission(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this permission request was declined. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
		)
		return
	if not model["snapshot"].get("pendingPermissionRequest"):
		_append_error(
			model,
			"Nothing to decline",
			"There is no permission request to decline.",
			now,
			in_response_to_request_id=request_id,
		)
		return

	expected_context_ref = (
		model["snapshot"]["pendingPermissionRequest"].get("contextRef")
		if isinstance(model["snapshot"].get("pendingPermissionRequest"), dict)
		else None
	)
	if not session_guards.context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Permission changed",
			"The permission request changed before this action was applied. Refresh and confirm the current permission surface.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "permission"},
		)
		return

	pending_permission = model["snapshot"].get("pendingPermissionRequest")
	declined_plan_execution = (
		isinstance(pending_permission, dict)
		and pending_permission.get("continuationKind") == "plan_execution"
		and isinstance(model.get("planReadyRequest"), dict)
	)
	model["snapshot"]["pendingPermissionRequest"] = None
	model["activeForegroundRequestId"] = None
	model["feed"].append(
		_feed_item(
			"system_status",
			"Permission request declined",
			"Permission scope stayed unchanged, and this request will not continue.",
			authoritative=True,
			now=now,
			in_response_to_request_id=request_id,
			presentation_key="permission.declined",
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="governor" if declined_plan_execution else "orchestration",
		currentStage="plan_ready" if declined_plan_execution else "permission_declined",
		runState="idle",
		transportState="connected",
	)


def handle_interrupt(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	text: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and not session_guards.session_ref_matches(model, session_ref):
		_append_error(
			model,
			"Session changed",
			"The active session changed before this stop request was applied. Refresh and try again.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.session_changed",
		)
		return
	raw_text = trim_text(text or "")
	if model["snapshot"].get("runState") != "running":
		_append_error(
			model,
			"Nothing is running",
			"Stop is only available while governed work is actively running.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	if model["snapshot"].get("pendingInterrupt"):
		_append_error(
			model,
			"Stop already requested",
			"A stop request is already waiting for orchestration handling.",
			now,
			in_response_to_request_id=request_id,
		)
		return
	expected_context_ref = session_guards.current_interrupt_context_ref(model)
	if not session_guards.context_matches(expected_context_ref, context_ref):
		_append_error(
			model,
			"Interrupt state changed",
			"The interruptible run state changed before this stop request was applied. Refresh and try again if stop is still available.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.stale_context",
			presentation_args={"kind": "interrupt"},
		)
		return
	model["snapshot"]["pendingInterrupt"] = _request_card(
		"Stop requested",
		"Stop has been requested and is waiting for orchestration handling.",
		now,
	)
	if raw_text:
		_append_user_turn(
			model,
			now,
			title="Stop requested",
			body=raw_text,
			turn_type="stop_action",
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=semantic_paraphrase,
			semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text,
			in_response_to_request_id=request_id,
		)
	model["feed"].append(
		_feed_item(
			"interrupt_request",
			"Stop requested",
			"Stop has been requested and is waiting for orchestration handling.",
			authoritative=True,
			now=now,
			**_semantic_provenance(
				turn_type="stop_action",
				semantic_input_version=semantic_input_version,
				semantic_summary_ref=semantic_summary_ref,
				semantic_context_flags=semantic_context_flags,
				semantic_route_type=semantic_route_type,
				semantic_confidence=semantic_confidence,
				semantic_block_reason=semantic_block_reason,
				semantic_paraphrase=semantic_paraphrase,
				semantic_normalized_text=trim_text(semantic_normalized_text) or raw_text or None,
				in_response_to_request_id=request_id,
			),
		)
	)
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="interrupt_requested",
		runState="running",
		transportState="connected",
	)


def handle_reconnect(
	session: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
) -> None:
	now = utc_now()
	model = session["model"]
	if session_ref is not None and model["snapshot"].get("sessionRef") and session_ref != model["snapshot"].get("sessionRef"):
		model["snapshot"]["sessionRef"] = _next_id("session")
		model["snapshot"]["permissionScope"] = "unset"
		model["snapshot"]["pendingPermissionRequest"] = None
		model["activeClarification"] = None
		model["acceptedIntakeSummary"] = None
		model["planReadyRequest"] = None
		_reset_work_loop_state(session)
		model["snapshot"]["pendingInterrupt"] = None
		model["snapshot"]["recentArtifacts"] = []
		_governor_dialogue_meta(session).clear()
		model["feed"].append(
			_feed_item(
				"system_status",
				"Switched session",
				"Reconnect attached to a different session snapshot.",
				authoritative=True,
				now=now,
				in_response_to_request_id=request_id,
				presentation_key="session.switched",
			)
		)
		_refresh_snapshot(model, now, transportState="connected")
		return
	if (
		model["snapshot"].get("transportState") == "connected"
		and not session_guards.is_snapshot_stale(model["snapshot"], now)
	):
		_append_error(
			model,
			"Nothing to reconnect",
			"The current session is already connected and fresh.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="reconnect.not_needed",
		)
		return
	model["feed"].append(
		_feed_item(
			"system_status",
			"Reconnected",
			"Reloaded the latest orchestration-backed session snapshot.",
			authoritative=True,
			now=now,
			in_response_to_request_id=request_id,
		)
	)
	_refresh_snapshot(model, now, transportState="connected")


def dispatch_session_action(
	command: str,
	*,
	text: str | None = None,
	repo_root: str | Path | None = None,
	session_ref: str | None = None,
	request_id: str | None = None,
	context_ref: str | None = None,
	permission_scope: str | None = None,
	semantic_mode: str | None = None,
	turn_type: str | None = None,
	normalized_text: str | None = None,
	paraphrase: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	governor_runtime: str = "exec",
	runtime_request_id: str | None = None,
	runtime_body: str | None = None,
	runtime_thread_id: str | None = None,
	runtime_turn_id: str | None = None,
	runtime_item_id: str | None = None,
	runtime_source: str = "app-server",
	fallback_reason: str | None = None,
	auto_consume_executor: bool = False,
) -> dict[str, Any]:
	session = load_session(repo_root)
	now = utc_now()
	if (
		command
		not in {"state", "complete_governor_turn", "fallback_governor_turn", "fail_governor_turn"}
		and session_guards.is_duplicate_request(session, request_id)
	):
		_append_error(
			session["model"],
			"Duplicate request",
			"The same controller request was already handled. Refresh and send a new action if you still want to proceed.",
			now,
			in_response_to_request_id=request_id,
			presentation_key="error.duplicate_request",
		)
		save_session(session, repo_root=repo_root)
		return public_model(session)
	if command == "submit_prompt":
		handle_submit_prompt(
			session,
			text or "",
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			semantic_mode=semantic_mode,
			turn_type=turn_type,
			normalized_text=normalized_text,
			paraphrase=paraphrase,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			governor_runtime=governor_runtime,
			auto_consume_executor=auto_consume_executor,
		)
	elif command == "answer_clarification":
		handle_answer_clarification(
			session,
			text or "",
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			normalized_text=normalized_text,
			paraphrase=paraphrase,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			governor_runtime=governor_runtime,
			auto_consume_executor=auto_consume_executor,
		)
	elif command == "set_permission_scope":
		handle_set_permission_scope(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			permission_scope=permission_scope,
			text=text,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=normalized_text,
			governor_runtime=governor_runtime,
			auto_consume_executor=auto_consume_executor,
		)
	elif command == "decline_permission":
		handle_decline_permission(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
		)
	elif command == "execute_plan":
		handle_execute_plan(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			governor_runtime=governor_runtime,
			auto_consume_executor=auto_consume_executor,
		)
	elif command == "revise_plan":
		handle_revise_plan(
			session,
			text or "",
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			governor_runtime=governor_runtime,
		)
	elif command == "complete_governor_turn":
		handle_complete_governor_turn(
			session,
			repo_root=repo_root,
			runtime_request_id=runtime_request_id,
			body=runtime_body,
			thread_id=runtime_thread_id,
			turn_id=runtime_turn_id,
			item_id=runtime_item_id,
			runtime_source=runtime_source,
		)
	elif command == "fallback_governor_turn":
		handle_fallback_governor_turn(
			session,
			repo_root=repo_root,
			runtime_request_id=runtime_request_id,
			reason=fallback_reason,
		)
	elif command == "fail_governor_turn":
		handle_fail_governor_turn(
			session,
			runtime_request_id=runtime_request_id,
			reason=fallback_reason,
		)
	elif command == "interrupt_run":
		handle_interrupt(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
			context_ref=context_ref,
			text=text,
			semantic_input_version=semantic_input_version,
			semantic_summary_ref=semantic_summary_ref,
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=semantic_route_type,
			semantic_confidence=semantic_confidence,
			semantic_block_reason=semantic_block_reason,
			semantic_paraphrase=paraphrase,
			semantic_normalized_text=normalized_text,
		)
	elif command == "reconnect":
		handle_reconnect(
			session,
			repo_root=repo_root,
			session_ref=session_ref,
			request_id=request_id,
		)
	elif command != "state":
		raise ValueError(f"unsupported session command: {command}")

	if command not in {"state", "complete_governor_turn", "fallback_governor_turn", "fail_governor_turn"}:
		session_guards.remember_request(session, request_id, command, now)
	save_session(session, repo_root=repo_root)
	pending = _pending_governor_runtime_request(session)
	if pending and (
		governor_runtime == "external"
		or (command == "complete_governor_turn" and pending.get("returnAsRuntimeRequest"))
	):
		return {
			"kind": "governor_runtime_request",
			"model": public_model(session),
			"request": _build_governor_runtime_request_envelope(pending),
		}
	return public_model(session)


def build_parser():
	return session_cli_args.build_parser()


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	args = build_parser().parse_args(argv)
	try:
		model = dispatch_session_action(
			**session_cli_args.dispatch_kwargs_from_args(args, repo_root=repo_root)
		)
	except (ValueError, json.JSONDecodeError) as exc:
		raise SystemExit(str(exc))
	print(json.dumps(model, indent=2, sort_keys=True))
	return 0
