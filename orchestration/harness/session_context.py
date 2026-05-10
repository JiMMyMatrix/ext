from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration.harness.intake import accepted_intake_path, request_draft_path
from orchestration.harness.paths import (
	load_json,
	repo_relative,
	resolve_paths,
	summarize,
)
from orchestration.harness.transition import load_transition


def load_request_draft_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	intake_ref = session["meta"].get("activeIntakeRef")
	if not isinstance(intake_ref, str) or not intake_ref:
		return None, None
	draft_path = request_draft_path(intake_ref, repo_root=repo_root)
	if not draft_path.exists():
		return None, None
	return load_json(draft_path), repo_relative(draft_path, repo_root)


def load_accepted_intake_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	intake_ref = session["meta"].get("activeIntakeRef")
	if not isinstance(intake_ref, str) or not intake_ref:
		return None, None
	accepted_path = accepted_intake_path(intake_ref, repo_root=repo_root)
	if not accepted_path.exists():
		return None, None
	return load_json(accepted_path), repo_relative(accepted_path, repo_root)


def latest_dispatch_summary(
	lane: str | None, *, repo_root: str | Path | None = None
) -> dict[str, Any] | None:
	if not isinstance(lane, str) or not lane.strip():
		return None

	queue_root = resolve_paths(repo_root).agent_root / "dispatches"
	if not queue_root.exists():
		return None

	best: tuple[float, dict[str, Any]] | None = None
	for state_path in queue_root.rglob("state.json"):
		dispatch_dir = state_path.parent
		request_path = dispatch_dir / "request.json"
		if not request_path.exists():
			continue
		try:
			request = load_json(request_path)
			state = load_json(state_path)
		except Exception:
			continue
		if request.get("lane") != lane:
			continue

		result_path = dispatch_dir / "result.json"
		decision_path = dispatch_dir / "governor_decision.json"
		result = load_json(result_path) if result_path.exists() else None
		decision = load_json(decision_path) if decision_path.exists() else None
		mtime = max(
			path.stat().st_mtime
			for path in [request_path, state_path, result_path, decision_path]
			if path.exists()
		)
		payload = {
			"dispatch_ref": request.get("dispatch_ref"),
			"objective": request.get("objective"),
			"state_status": state.get("status"),
			"state_ref": repo_relative(state_path, repo_root),
			"request_ref": repo_relative(request_path, repo_root),
			"result_status": result.get("status") if isinstance(result, dict) else None,
			"result_blocker": result.get("blocker") if isinstance(result, dict) else None,
			"result_ref": repo_relative(result_path, repo_root) if result_path.exists() else None,
			"decision": decision.get("decision") if isinstance(decision, dict) else None,
			"decision_reason": decision.get("reason") if isinstance(decision, dict) else None,
			"decision_ref": repo_relative(decision_path, repo_root) if decision_path.exists() else None,
		}
		if best is None or mtime > best[0]:
			best = (mtime, payload)

	return best[1] if best else None


def transition_summary(lane: str | None, *, repo_root: str | Path | None = None) -> dict[str, Any] | None:
	if not isinstance(lane, str) or not lane.strip():
		return None
	try:
		payload = load_transition(resolve_paths(repo_root).repo_root, lane)
	except SystemExit:
		return None
	if not isinstance(payload, dict):
		return None
	return {
		"transition": payload.get("transition"),
		"requested_stop_reason": payload.get("requested_stop_reason"),
		"next_action_kind": (payload.get("next_action") or {}).get("kind")
		if isinstance(payload.get("next_action"), dict)
		else None,
		"next_action_ref": (payload.get("next_action") or {}).get("ref")
		if isinstance(payload.get("next_action"), dict)
		else None,
		"ref": repo_relative(
			resolve_paths(repo_root).agent_root / "governor" / lane / "proposed_transition.json",
			repo_root,
		),
	}


def governor_dialogue_context(
	session: dict[str, Any],
	prompt: str,
	*,
	repo_root: str | Path | None = None,
	semantic_intake: bool = False,
) -> dict[str, Any]:
	model = session["model"]
	snapshot = model["snapshot"]
	task = snapshot.get("task")
	stage = snapshot.get("currentStage") or "idle"
	actor = snapshot.get("currentActor") or "orchestration"
	lane = snapshot.get("lane")
	request_draft, request_draft_ref = load_request_draft_summary(session, repo_root=repo_root)
	accepted_intake, accepted_intake_ref = load_accepted_intake_summary(session, repo_root=repo_root)
	dispatch_summary = latest_dispatch_summary(lane, repo_root=repo_root)
	transition = transition_summary(lane, repo_root=repo_root)
	primary_ref = (
		(dispatch_summary or {}).get("decision_ref")
		or (dispatch_summary or {}).get("result_ref")
		or (dispatch_summary or {}).get("state_ref")
		or accepted_intake_ref
		or request_draft_ref
		or (transition or {}).get("ref")
	)

	if model.get("activeClarification"):
		orchestration_summary = (
			"A clarification is still active. The request cannot continue until the user answers it."
		)
	elif snapshot.get("pendingPermissionRequest"):
		recommended_scope = snapshot["pendingPermissionRequest"].get("recommendedScope") or "plan"
		orchestration_summary = (
			f"The current request is blocked on a permission choice. Recommended scope: {recommended_scope}."
		)
	elif snapshot.get("currentStage") == "dispatch_queued" or snapshot.get("runState") == "queued":
		orchestration_summary = (
			f"Dispatch truth is queued{f' for {task}' if task else ''}. Executor has not started yet."
		)
	elif dispatch_summary:
		orchestration_summary = (
			f"The latest dispatch is {dispatch_summary.get('dispatch_ref')} with state "
			f"{dispatch_summary.get('state_status') or 'unknown'}."
		)
		if dispatch_summary.get("result_status"):
			orchestration_summary += f" Result status is {dispatch_summary['result_status']}."
		if dispatch_summary.get("decision"):
			orchestration_summary += f" Governor decision is {dispatch_summary['decision']}."
	elif accepted_intake:
		orchestration_summary = (
			f"The accepted intake is bound to {accepted_intake.get('lane') or lane or 'the current lane'} "
			f"for {accepted_intake.get('task') or accepted_intake.get('goal') or task or 'the current task'}."
		)
	elif request_draft:
		orchestration_summary = (
			f"Intake has a draft for {request_draft.get('task_hint') or request_draft.get('normalized_goal') or task or 'the current request'}, "
			f"and it is currently {request_draft.get('shell_state') or stage}."
		)
	elif snapshot.get("runState") == "running":
		orchestration_summary = (
			f"Corgi is actively working{f' on {task}' if task else ''}. Stop is available if the user needs it."
		)
	elif model.get("acceptedIntakeSummary"):
		orchestration_summary = (
			f"The latest accepted intake is {task or 'ready'}, and the session is currently idle."
		)
	else:
		orchestration_summary = (
			"Nothing is currently running. The user may start a bounded request or ask a progress question."
		)

	details = [
		f"Prompt: {summarize(prompt, 72)}",
		f"Current actor: {actor}",
		f"Current stage: {stage}",
	]
	if task:
		details.append(f"Current task: {task}")
	if request_draft_ref and request_draft:
		details.append(f"Request draft: {request_draft_ref} ({request_draft.get('shell_state')})")
	if accepted_intake_ref and accepted_intake:
		details.append(
			f"Accepted intake: {accepted_intake_ref} (lane={accepted_intake.get('lane')}, task={accepted_intake.get('task') or accepted_intake.get('goal')})"
		)
	if dispatch_summary:
		details.append(
			f"Latest dispatch: {dispatch_summary.get('dispatch_ref')} status={dispatch_summary.get('state_status')} ({dispatch_summary.get('state_ref')})"
		)
		if dispatch_summary.get("result_status") and dispatch_summary.get("result_ref"):
			details.append(
				f"Latest result: status={dispatch_summary['result_status']} ({dispatch_summary['result_ref']})"
			)
		if dispatch_summary.get("decision") and dispatch_summary.get("decision_ref"):
			details.append(
				f"Latest governor decision: {dispatch_summary['decision']} ({dispatch_summary['decision_ref']})"
			)
	if transition:
		details.append(
			f"Proposed transition: {transition.get('transition')} ({transition.get('ref')})"
		)
		if transition.get("next_action_kind"):
			details.append(
				f"Next internal action: {transition['next_action_kind']} -> {transition.get('next_action_ref') or 'none'}"
			)
	if semantic_intake:
		context_lines = [
			"Processed Governor semantic-intake input",
			"This request is being interpreted before workflow state changes.",
			"Return JSON only, using the semantic-intake schema from the outer prompt.",
			"Do not expose request ids, session refs, context refs, semantic provenance, or raw orchestration/control-plane metadata.",
			"",
			"Current session state:",
			f"- permission_scope: {snapshot.get('permissionScope') or 'unset'}",
			f"- current_actor: {actor}",
			f"- current_stage: {stage}",
			f"- run_state: {snapshot.get('runState') or 'idle'}",
		]
	else:
		context_lines = [
			"Processed Governor dialogue input",
			"This request already passed through controller/orchestration gating.",
			"Reply only with the user-facing answer in plain text.",
			"Do not expose request ids, session refs, context refs, semantic provenance, or raw orchestration/control-plane metadata.",
			"If you need evidence, inspect the repository and authoritative artifacts directly before answering.",
			"",
			"Current session state:",
			f"- permission_scope: {snapshot.get('permissionScope') or 'unset'}",
			f"- current_actor: {actor}",
			f"- current_stage: {stage}",
			f"- run_state: {snapshot.get('runState') or 'idle'}",
		]
	if task:
		context_lines.append(f"- current_task: {task}")
	if lane:
		context_lines.append(f"- lane: {lane}")
	context_lines.append(f"- orchestration_summary: {orchestration_summary}")
	context_lines.extend(["", "Authoritative artifact hints:"])
	artifact_lines: list[str] = []
	if accepted_intake_ref:
		artifact_lines.append(f"- accepted_intake_ref: {accepted_intake_ref}")
	if request_draft_ref:
		artifact_lines.append(f"- request_draft_ref: {request_draft_ref}")
	if dispatch_summary:
		if dispatch_summary.get("request_ref"):
			artifact_lines.append(f"- latest_dispatch_request_ref: {dispatch_summary['request_ref']}")
		if dispatch_summary.get("state_ref"):
			artifact_lines.append(f"- latest_dispatch_state_ref: {dispatch_summary['state_ref']}")
		if dispatch_summary.get("result_ref"):
			artifact_lines.append(f"- latest_dispatch_result_ref: {dispatch_summary['result_ref']}")
		if dispatch_summary.get("decision_ref"):
			artifact_lines.append(f"- latest_governor_decision_ref: {dispatch_summary['decision_ref']}")
	if transition and transition.get("ref"):
		artifact_lines.append(f"- proposed_transition_ref: {transition['ref']}")
	if artifact_lines:
		context_lines.extend(artifact_lines)
	else:
		context_lines.append("- none")
	context_lines.extend(
		[
			"",
			f"Processed user request: {prompt}",
			"Return JSON only." if semantic_intake else "Return only the human-facing reply with no headings or metadata.",
		]
	)
	return {
		"details": details,
		"primary_ref": primary_ref,
		"prompt": "\n".join(context_lines),
	}


def governor_dialogue_meta(session: dict[str, Any]) -> dict[str, Any]:
	meta = session.setdefault("meta", {})
	governor_dialogue = meta.setdefault("governorDialogue", {})
	if isinstance(governor_dialogue, dict):
		return governor_dialogue
	meta["governorDialogue"] = {}
	return meta["governorDialogue"]
