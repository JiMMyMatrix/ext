from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from orchestration.harness import governor_semantic
from orchestration.harness import session_permissions
from orchestration.harness.intake import start_intake
from orchestration.harness.paths import git_branch_name, summarize, trim_text, utc_now


AppendCompletedGovernorDialogueResponse = Callable[..., bool]
AppendError = Callable[..., None]
FeedItem = Callable[..., dict[str, Any]]
NextId = Callable[[str], str]
PermissionRequest = Callable[..., dict[str, Any]]
RefreshSnapshot = Callable[..., None]
ResetWorkLoopState = Callable[[dict[str, Any]], None]
SupersedePendingPermissionRequest = Callable[..., None]


def reject_governor_semantic_proposal(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reason: str,
	*,
	body: str | None = None,
	proposal: Any = None,
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
) -> None:
	model = session["model"]
	governor_semantic.record_rejected_proposal(session, pending, reason, proposal)
	append_error(
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
	refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="blocked",
		runState="idle",
		transportState="connected",
	)
	model["activeForegroundRequestId"] = None


def apply_governor_semantic_dialogue(
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
	permission_request: PermissionRequest,
	feed_item: FeedItem,
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
	append_completed_governor_dialogue_response: AppendCompletedGovernorDialogueResponse,
) -> None:
	model = session["model"]
	if (
		governor_semantic.proposal_permission(proposal) != "none"
		or proposal.get("needs_clarification")
		or proposal.get("plan_intent")
	):
		reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"governor_dialogue_proposed_state_change",
			body=reply,
			proposal=proposal,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
		)
		return
	if not session_permissions.scope_satisfies(
		session_permissions.current_permission_scope(model), "observe"
	):
		request = permission_request(
			"observe",
			now,
			continuation_kind="governor_dialogue",
			pending_prompt=pending.get("prompt"),
			pending_normalized_text=governor_semantic.proposal_normalized_intent(
				proposal, pending.get("prompt") or ""
			),
			foreground_request_id=pending.get("requestId"),
		)
		model["snapshot"]["pendingPermissionRequest"] = request
		model["feed"].append(
			feed_item(
				"permission_request",
				request["title"],
				reply or request["body"],
				authoritative=True,
				now=now,
				in_response_to_request_id=pending.get("requestId"),
				presentation_key="permission.needed",
				presentation_args={
					"scope": "observe",
					"contextRef": request["contextRef"],
				},
			)
		)
		refresh_snapshot(
			model,
			now,
			currentActor="orchestration",
			currentStage="permission_needed",
			runState="idle",
			transportState="connected",
		)
		return
	append_completed_governor_dialogue_response(
		session,
		{
			**pending,
			"resultStage": "dialogue_ready",
			"turnType": "governor_dialogue",
			"semanticRouteType": "governor_dialogue",
			"semanticConfidence": governor_semantic.proposal_confidence(proposal),
			"semanticNormalizedText": governor_semantic.proposal_normalized_intent(
				proposal, pending.get("prompt") or ""
			),
		},
		reply,
		now,
		repo_root=repo_root,
		app_server_thread_id=app_server_thread_id,
		app_server_turn_id=app_server_turn_id,
		app_server_item_id=app_server_item_id,
		runtime_source=runtime_source,
	)


def apply_governor_semantic_work_intent(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reply: str,
	proposal: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	permission_request: PermissionRequest,
	feed_item: FeedItem,
	refresh_snapshot: RefreshSnapshot,
	supersede_pending_permission_request: SupersedePendingPermissionRequest,
	reset_work_loop_state: ResetWorkLoopState,
) -> None:
	model = session["model"]
	prompt = trim_text(pending.get("prompt")) or governor_semantic.proposal_normalized_intent(proposal, "")
	normalized = governor_semantic.proposal_normalized_intent(proposal, prompt)
	initial_scope = governor_semantic.proposal_permission(proposal)
	if initial_scope == "none":
		initial_scope = session_permissions.recommended_permission_scope(normalized)
	if initial_scope == "execute":
		# Free-text governed work still starts at planning. The Governor may
		# recommend execute for an obvious build request, but orchestration must
		# create a plan checkpoint before any execute permission can be requested.
		initial_scope = "plan"
	supersede_pending_permission_request(model, now, request_id=pending.get("requestId"))
	envelope = start_intake(prompt, normalized_text=normalized, repo_root=repo_root)
	reset_work_loop_state(session)
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
			feed_item(
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
		refresh_snapshot(
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
	request = permission_request(
		required_scope,
		now,
		continuation_kind="intake_acceptance",
		pending_prompt=prompt,
		pending_normalized_text=normalized,
		foreground_request_id=pending.get("requestId"),
	)
	model["snapshot"]["pendingPermissionRequest"] = request
	model["feed"].append(
		feed_item(
			"permission_request",
			request["title"],
			reply or request["body"],
			authoritative=True,
			now=now,
			in_response_to_request_id=pending.get("requestId"),
			presentation_key="permission.needed",
			presentation_args={
				"scope": required_scope,
				"contextRef": request["contextRef"],
			},
		)
	)
	refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="permission_needed",
		runState="idle",
		transportState="connected",
	)


def apply_governor_semantic_clarification(
	session: dict[str, Any],
	pending: dict[str, Any],
	now: str,
	reply: str,
	proposal: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	next_id: NextId,
	feed_item: FeedItem,
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
	reset_work_loop_state: ResetWorkLoopState,
) -> None:
	model = session["model"]
	prompt = trim_text(pending.get("prompt")) or governor_semantic.proposal_normalized_intent(proposal, "")
	normalized = governor_semantic.proposal_normalized_intent(proposal, prompt)
	envelope = start_intake(prompt, normalized_text=normalized, repo_root=repo_root)
	reset_work_loop_state(session)
	session["meta"]["activeIntakeRef"] = envelope["intake_ref"]
	question = trim_text(proposal.get("clarification_question") if isinstance(proposal.get("clarification_question"), str) else "")
	if not question:
		reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"clarification_proposal_missing_question",
			body=reply,
			proposal=proposal,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
		)
		return
	clarification_id = next_id("clarification")
	clarification = {
		"id": clarification_id,
		"contextRef": clarification_id,
		"title": "Clarification needed",
		"body": question,
		"kind": "governor_semantic_intake",
		"options": governor_semantic.clarification_options(proposal),
		"allowFreeText": True,
		"placeholder": "Add the detail the Governor needs...",
		"requestedAt": now,
	}
	model["activeClarification"] = clarification
	model["snapshot"]["pendingPermissionRequest"] = None
	model["acceptedIntakeSummary"] = None
	model["planReadyRequest"] = None
	model["feed"].append(
		feed_item(
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
	refresh_snapshot(
		model,
		now,
		currentActor="governor",
		currentStage="clarification_needed",
		runState="idle",
		transportState="connected",
	)


def apply_governor_semantic_plan_ready(
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
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
	append_completed_governor_dialogue_response: AppendCompletedGovernorDialogueResponse,
) -> None:
	model = session["model"]
	if not isinstance(model.get("acceptedIntakeSummary"), dict):
		reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"plan_ready_without_accepted_intake",
			body=reply,
			proposal=proposal,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
		)
		return
	append_completed_governor_dialogue_response(
		session,
		{
			**pending,
			"resultStage": "plan_ready",
			"turnType": "governed_work_intent",
			"semanticRouteType": "governed_work_intent",
			"semanticConfidence": governor_semantic.proposal_confidence(proposal),
			"semanticNormalizedText": governor_semantic.proposal_normalized_intent(
				proposal, pending.get("prompt") or ""
			),
		},
		reply,
		now,
		app_server_thread_id=app_server_thread_id,
		app_server_turn_id=app_server_turn_id,
		app_server_item_id=app_server_item_id,
		runtime_source=runtime_source,
	)


def complete_governor_semantic_intake(
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
	next_id: NextId,
	permission_request: PermissionRequest,
	feed_item: FeedItem,
	append_error: AppendError,
	refresh_snapshot: RefreshSnapshot,
	append_completed_governor_dialogue_response: AppendCompletedGovernorDialogueResponse,
	supersede_pending_permission_request: SupersedePendingPermissionRequest,
	reset_work_loop_state: ResetWorkLoopState,
) -> None:
	governor_meta = session.setdefault("meta", {}).setdefault("governorDialogue", {})
	if app_server_thread_id:
		governor_meta["appServerThreadId"] = app_server_thread_id
	if app_server_turn_id:
		governor_meta["lastAppServerTurnId"] = app_server_turn_id
	if app_server_item_id:
		governor_meta["lastAppServerItemId"] = app_server_item_id
	governor_meta["lastRuntimeSource"] = runtime_source
	governor_meta["lastUsedAt"] = utc_now()
	payload = governor_semantic.parse_governor_semantic_intake_payload(body)
	if payload is None:
		reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_payload_not_json",
			body="Corgi could not read the Governor intake proposal. Please try again.",
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
		)
		return
	proposal = governor_semantic.semantic_proposal(payload)
	reply = governor_semantic.semantic_user_copy(payload, "Corgi needs a clearer request before continuing.")
	route = governor_semantic.proposal_route(proposal)
	rejection_reason = governor_semantic.initial_rejection_reason(proposal)
	if rejection_reason:
		reject_governor_semantic_proposal(
			session,
			pending,
			now,
			rejection_reason,
			body=reply,
			proposal=proposal,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
		)
		return
	if route == "governor_dialogue":
		apply_governor_semantic_dialogue(
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
			permission_request=permission_request,
			feed_item=feed_item,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
			append_completed_governor_dialogue_response=append_completed_governor_dialogue_response,
		)
	elif route == "governed_work_intent":
		apply_governor_semantic_work_intent(
			session,
			pending,
			now,
			reply,
			proposal,
			repo_root=repo_root,
			permission_request=permission_request,
			feed_item=feed_item,
			refresh_snapshot=refresh_snapshot,
			supersede_pending_permission_request=supersede_pending_permission_request,
			reset_work_loop_state=reset_work_loop_state,
		)
	elif route == "clarification_needed":
		apply_governor_semantic_clarification(
			session,
			pending,
			now,
			reply,
			proposal,
			repo_root=repo_root,
			next_id=next_id,
			feed_item=feed_item,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
			reset_work_loop_state=reset_work_loop_state,
		)
	elif route == "permission_needed":
		recommended = governor_semantic.proposal_permission(proposal)
		if recommended not in {"observe", "plan", "execute"}:
			reject_governor_semantic_proposal(
				session,
				pending,
				now,
				"semantic_intake_permission_missing_scope",
				body=reply,
				proposal=proposal,
				append_error=append_error,
				refresh_snapshot=refresh_snapshot,
			)
			return
		if recommended == "observe":
			apply_governor_semantic_dialogue(
				session,
				pending,
				now,
				reply,
				{**proposal, "route_type": "governor_dialogue", "recommended_permission": "none"},
				runtime_source=runtime_source,
				app_server_thread_id=app_server_thread_id,
				app_server_turn_id=app_server_turn_id,
				app_server_item_id=app_server_item_id,
				permission_request=permission_request,
				feed_item=feed_item,
				append_error=append_error,
				refresh_snapshot=refresh_snapshot,
				append_completed_governor_dialogue_response=append_completed_governor_dialogue_response,
			)
		elif recommended == "execute":
			reject_governor_semantic_proposal(
				session,
				pending,
				now,
				"semantic_intake_execute_without_plan_context",
				body=reply,
				proposal=proposal,
				append_error=append_error,
				refresh_snapshot=refresh_snapshot,
			)
		else:
			apply_governor_semantic_work_intent(
				session,
				pending,
				now,
				reply,
				proposal,
				repo_root=repo_root,
				permission_request=permission_request,
				feed_item=feed_item,
				refresh_snapshot=refresh_snapshot,
				supersede_pending_permission_request=supersede_pending_permission_request,
				reset_work_loop_state=reset_work_loop_state,
			)
	elif route == "plan_ready":
		apply_governor_semantic_plan_ready(
			session,
			pending,
			now,
			reply,
			proposal,
			runtime_source=runtime_source,
			app_server_thread_id=app_server_thread_id,
			app_server_turn_id=app_server_turn_id,
			app_server_item_id=app_server_item_id,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
			append_completed_governor_dialogue_response=append_completed_governor_dialogue_response,
		)
	elif route == "block":
		reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_block",
			body=reply,
			proposal=proposal,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
		)
	else:
		reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_unknown_route",
			body=reply,
			proposal=proposal,
			append_error=append_error,
			refresh_snapshot=refresh_snapshot,
		)
