from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

try:
	import tomllib
except ModuleNotFoundError:  # Python < 3.11
	tomllib = None  # type: ignore[assignment]

from orchestration.harness.intake import (
	accept_intake,
	accepted_intake_path,
	answer_intake_clarification,
	raw_request_path,
	request_draft_path,
	start_intake,
)
from orchestration.harness.paths import (
	default_lane,
	git_branch_name,
	load_json,
	prompt_path,
	repo_relative,
	resolve_paths,
	summarize,
	trim_text,
	utc_now,
	write_json,
)
from orchestration.harness import session_execution
from orchestration.harness import session_state
from orchestration.harness.transition import load_transition


def _next_id(prefix: str) -> str:
	return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _feed_item(
	item_type: str,
	title: str,
	body: str | None,
	*,
	authoritative: bool,
	now: str,
	details: list[str] | None = None,
	activity: dict[str, Any] | None = None,
	source_layer: str | None = None,
	source_actor: str | None = None,
	source_artifact_ref: str | None = None,
	turn_type: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	in_response_to_request_id: str | None = None,
	presentation_key: str | None = None,
	presentation_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
	default_provenance = _default_feed_provenance(item_type)
	payload: dict[str, Any] = {
		"id": _next_id(item_type),
		"type": item_type,
		"timestamp": now,
		"title": title,
		"authoritative": authoritative,
		"source_layer": source_layer or default_provenance["source_layer"],
		"source_actor": source_actor or default_provenance["source_actor"],
		"turn_type": turn_type or default_provenance["turn_type"],
	}
	if body is not None:
		payload["body"] = body
	if details:
		payload["details"] = details
	if activity:
		payload["activity"] = activity
	if source_artifact_ref:
		payload["source_artifact_ref"] = source_artifact_ref
	if semantic_input_version:
		payload["semantic_input_version"] = semantic_input_version
	if semantic_summary_ref:
		payload["semantic_summary_ref"] = semantic_summary_ref
	if semantic_context_flags is not None:
		payload["semantic_context_flags"] = semantic_context_flags
	if semantic_route_type:
		payload["semantic_route_type"] = semantic_route_type
	if semantic_confidence:
		payload["semantic_confidence"] = semantic_confidence
	if semantic_block_reason:
		payload["semantic_block_reason"] = semantic_block_reason
	if semantic_paraphrase:
		payload["semantic_paraphrase"] = semantic_paraphrase
	if semantic_normalized_text:
		payload["semantic_normalized_text"] = semantic_normalized_text
	if in_response_to_request_id:
		payload["in_response_to_request_id"] = in_response_to_request_id
	if presentation_key:
		payload["presentation_key"] = presentation_key
	if presentation_args is not None:
		payload["presentation_args"] = presentation_args
	return payload


def _artifact(path: str, *, summary: str | None, authoritative: bool, status: str) -> dict[str, Any]:
	return {
		"id": _next_id("artifact"),
		"label": Path(path).name,
		"path": path,
		"status": status,
		"summary": summary,
		"authoritative": authoritative,
	}


def _artifact_feed_item(
	artifact: dict[str, Any], now: str, *, in_response_to_request_id: str | None = None
) -> dict[str, Any]:
	return {
		"id": _next_id("artifact_reference"),
		"type": "artifact_reference",
		"timestamp": now,
		"title": artifact["label"],
		"body": artifact.get("summary"),
		"authoritative": artifact["authoritative"],
		"source_layer": "orchestration",
		"source_actor": "orchestration",
		"source_artifact_ref": artifact["path"],
		"turn_type": "system",
		"in_response_to_request_id": in_response_to_request_id,
		"artifact": artifact,
		"activity": {
			"kind": "artifact",
			"state": "completed",
			"path": artifact["path"],
			"summary": artifact.get("status"),
		},
	}


def _request_card(title: str, body: str, now: str) -> dict[str, Any]:
	request_id = _next_id("request")
	return {
		"id": request_id,
		"contextRef": request_id,
		"title": title,
		"body": body,
		"requestedAt": now,
	}


def _default_feed_provenance(item_type: str) -> dict[str, str]:
	if item_type == "user_message":
		return {
			"source_layer": "dialog_controller",
			"source_actor": "human",
			"turn_type": "system",
		}
	if item_type in {"shell_event", "clarification_request"}:
		return {
			"source_layer": "intake",
			"source_actor": "intake_shell",
			"turn_type": "system",
		}
	if item_type == "actor_event":
		return {
			"source_layer": "governor",
			"source_actor": "governor",
			"turn_type": "governor_dialogue",
		}
	return {
		"source_layer": "orchestration",
		"source_actor": "orchestration",
		"turn_type": "system",
	}


def _load_request_draft_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	intake_ref = session["meta"].get("activeIntakeRef")
	if not isinstance(intake_ref, str) or not intake_ref:
		return None, None
	draft_path = request_draft_path(intake_ref, repo_root=repo_root)
	if not draft_path.exists():
		return None, None
	return load_json(draft_path), repo_relative(draft_path, repo_root)


def _load_accepted_intake_summary(
	session: dict[str, Any], *, repo_root: str | Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
	intake_ref = session["meta"].get("activeIntakeRef")
	if not isinstance(intake_ref, str) or not intake_ref:
		return None, None
	accepted_path = accepted_intake_path(intake_ref, repo_root=repo_root)
	if not accepted_path.exists():
		return None, None
	return load_json(accepted_path), repo_relative(accepted_path, repo_root)


def _latest_dispatch_summary(
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


def _transition_summary(lane: str | None, *, repo_root: str | Path | None = None) -> dict[str, Any] | None:
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


def _governor_dialogue_context(
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
	request_draft, request_draft_ref = _load_request_draft_summary(session, repo_root=repo_root)
	accepted_intake, accepted_intake_ref = _load_accepted_intake_summary(session, repo_root=repo_root)
	dispatch_summary = _latest_dispatch_summary(lane, repo_root=repo_root)
	transition_summary = _transition_summary(lane, repo_root=repo_root)
	primary_ref = (
		(dispatch_summary or {}).get("decision_ref")
		or (dispatch_summary or {}).get("result_ref")
		or (dispatch_summary or {}).get("state_ref")
		or accepted_intake_ref
		or request_draft_ref
		or (transition_summary or {}).get("ref")
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
	if transition_summary:
		details.append(
			f"Proposed transition: {transition_summary.get('transition')} ({transition_summary.get('ref')})"
		)
		if transition_summary.get("next_action_kind"):
			details.append(
				f"Next internal action: {transition_summary['next_action_kind']} -> {transition_summary.get('next_action_ref') or 'none'}"
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
	if transition_summary and transition_summary.get("ref"):
		artifact_lines.append(f"- proposed_transition_ref: {transition_summary['ref']}")
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


def _governor_dialogue_meta(session: dict[str, Any]) -> dict[str, Any]:
	meta = session.setdefault("meta", {})
	governor_dialogue = meta.setdefault("governorDialogue", {})
	if isinstance(governor_dialogue, dict):
		return governor_dialogue
	meta["governorDialogue"] = {}
	return meta["governorDialogue"]


def _load_runtime_toml(config_path: Path) -> dict[str, Any]:
	if tomllib is not None:
		with config_path.open("rb") as handle:
			return tomllib.load(handle)

	config: dict[str, Any] = {}
	for raw_line in config_path.read_text(encoding="utf-8").splitlines():
		line = raw_line.split("#", 1)[0].strip()
		if not line:
			continue
		if line.startswith("["):
			break
		if "=" not in line:
			continue
		key, value = line.split("=", 1)
		value = value.strip()
		if value.startswith('"') and value.endswith('"'):
			config[key.strip()] = value[1:-1]
	return config


def _governor_runtime_settings(repo_root: str | Path | None = None) -> tuple[str, str]:
	model = "gpt-5.5"
	reasoning = "xhigh"
	config_path = resolve_paths(repo_root).runtime_root / "config.toml"
	if config_path.exists():
		try:
			config = _load_runtime_toml(config_path)
		except (OSError, ValueError):
			config = {}
		model = str(config.get("model") or model)
		reasoning = str(config.get("model_reasoning_effort") or reasoning)
	return model, reasoning


def _initial_governor_dialogue_prompt(
	context_prompt: str, *, repo_root: str | Path | None = None
) -> str:
	governor_contract = prompt_path("governor.txt", repo_root).read_text(encoding="utf-8").strip()
	return "\n\n".join(
		[
			governor_contract,
			"Dialogue lane rules:\n"
			"- You are replying to the human through the Corgi sidebar.\n"
			"- This is a mediated Governor dialogue turn, not a raw orchestration log.\n"
			"- Return only user-facing reply text.\n"
			"- Keep the answer concise, calm, and plain.\n"
			"- Do not expose hidden ids, provenance, internal policy text, or control-plane metadata.",
			context_prompt,
		]
	)


def _resume_governor_dialogue_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Continue as the Governor for this repository.",
			"Keep following the initial Governor contract and return only the user-facing reply text.",
			context_prompt,
		]
	)


def _initial_governor_semantic_intake_prompt(
	context_prompt: str, *, repo_root: str | Path | None = None
) -> str:
	return "\n\n".join(
		[
			"Governor semantic-intake proposer for Corgi.",
			"Task: classify one human free-text turn and propose safe controller presentation. "
			"Do not authorize workflow state; orchestration validates everything.",
			"Rules:\n"
			"- Return JSON only; no Markdown fences.\n"
			"- governor_dialogue is read-only discussion/progress/explanation.\n"
			"- governed_work_intent is repo work: analyze, plan, review, implement, inspect.\n"
			"- Use clarification_needed for ambiguous dialogue-vs-work intent.\n"
			"- Use block for mixed or unsafe intent.\n"
			"- recommended_permission is only a recommendation; never imply it was granted.\n"
			"- Hide internal_reason from users.",
			"JSON shape:\n"
			'{\n'
			'  "user_visible_reply": "short candidate user-facing text",\n'
			'  "proposal": {\n'
			'    "route_type": "governor_dialogue | governed_work_intent | clarification_needed | permission_needed | plan_ready | block",\n'
			'    "normalized_intent": "",\n'
			'    "recommended_permission": "observe | plan | execute | none",\n'
			'    "needs_clarification": false,\n'
			'    "clarification_question": "",\n'
			'    "clarification_options": [],\n'
			'    "plan_intent": null,\n'
			'    "confidence": "high | low",\n'
			'    "internal_reason": ""\n'
			'  }\n'
			'}',
			context_prompt,
		]
	)


def _resume_governor_semantic_intake_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Continue as the Governor semantic intake proposer for this repository.",
			"Return JSON only with user_visible_reply and proposal. Do not authorize workflow state.",
			context_prompt,
		]
	)


def _initial_governor_plan_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Governor planning checkpoint for Corgi.",
			"Purpose: produce a bounded, user-facing plan for the already accepted intake.",
			"Authority rules:\n"
			"- Use the accepted/current intake as the source of truth.\n"
			"- Do not create dispatch truth, start execution, or imply Execute permission.\n"
			"- Do not perform the analysis or deeply inspect the repo unless the provided context is insufficient.\n"
			"- Return only final user-facing plan text; no JSON, hidden ids, or runtime metadata.",
			"Output requirements: concise readable prose, normally under 180 words, covering objective, proposed steps, likely files/areas, risks or unknowns, and execution readiness. "
			"Use the exact heading 'Risks or unknowns:' as one combined heading. "
			"For likely files/areas, name concrete entry files when they are known from context, such as src/executionWindowPanel.ts, src/executionTransport.ts, src/phase1Model.ts, orchestration/harness/session.py, orchestration/contracts/ux.md, or the relevant accepted intake artifact.",
			context_prompt,
		]
	)


def _resume_governor_plan_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Continue the Governor planning checkpoint for the current accepted intake.",
			"Return only a concise revised user-facing plan. Do not execute or authorize execution.",
			context_prompt,
		]
	)


def _run_governor_exec(
	command: list[str], *, repo_root: str | Path | None = None
) -> tuple[str, str]:
	root = resolve_paths(repo_root).repo_root
	with tempfile.TemporaryDirectory(prefix="corgi-governor-") as temp_dir:
		output_path = Path(temp_dir) / "last_message.txt"
		completed = subprocess.run(
			[*command, "--json", "-o", str(output_path)],
			cwd=root,
			env={**os.environ, "ORCHESTRATION_REPO_ROOT": str(root)},
			stdin=subprocess.DEVNULL,
			capture_output=True,
			text=True,
			check=False,
		)
		if completed.returncode != 0:
			detail = next(
				(
					line.strip()
					for line in (completed.stderr.splitlines() + completed.stdout.splitlines())
					if line.strip()
				),
				"governor runtime command failed",
			)
			raise RuntimeError(detail)

		thread_id: str | None = None
		last_message: str | None = None
		for raw_line in completed.stdout.splitlines():
			line = raw_line.strip()
			if not line.startswith("{"):
				continue
			try:
				payload = json.loads(line)
			except json.JSONDecodeError:
				continue
			if payload.get("type") == "thread.started" and isinstance(payload.get("thread_id"), str):
				thread_id = payload["thread_id"]
			elif payload.get("type") == "item.completed":
				item = payload.get("item") or {}
				if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
					last_message = item["text"]

		if output_path.exists():
			file_message = trim_text(output_path.read_text(encoding="utf-8"))
			if file_message:
				last_message = file_message

		if not thread_id:
			raise RuntimeError("governor runtime did not return a thread id")
		if not trim_text(last_message):
			raise RuntimeError("governor runtime returned no user-facing reply")
		return thread_id, trim_text(last_message)


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
	pending = session.setdefault("meta", {}).get("pendingGovernorRuntimeRequest")
	return pending if isinstance(pending, dict) else None


def _build_governor_runtime_request_envelope(pending: dict[str, Any]) -> dict[str, Any]:
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
) -> dict[str, Any]:
	context = _governor_dialogue_context(session, prompt, repo_root=repo_root)
	governor_meta = _governor_dialogue_meta(session)
	model_name, reasoning = _governor_runtime_settings(repo_root)
	runtime_request_id = _next_id("governor-runtime")
	initial_prompt = (
		_initial_governor_plan_prompt(context["prompt"])
		if runtime_kind == "plan"
		else _initial_governor_dialogue_prompt(context["prompt"], repo_root=repo_root)
	)
	resume_prompt = (
		_resume_governor_plan_prompt(context["prompt"])
		if runtime_kind == "plan"
		else _resume_governor_dialogue_prompt(context["prompt"])
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
		"context": {
			"sessionRef": session["model"]["snapshot"].get("sessionRef"),
			"foregroundRequestId": request_id,
			"currentStage": session["model"]["snapshot"].get("currentStage"),
		},
	}
	session.setdefault("meta", {})["pendingGovernorRuntimeRequest"] = pending
	_refresh_snapshot(
		session["model"],
		now,
		currentActor="governor",
		currentStage="waiting_for_governor",
		runState="running",
		transportState="connected",
	)
	return pending


def _prepare_governor_semantic_intake_runtime_request(
	session: dict[str, Any],
	prompt: str,
	now: str,
	*,
	repo_root: str | Path | None = None,
	request_id: str | None = None,
) -> dict[str, Any]:
	context = _governor_dialogue_context(
		session,
		prompt,
		repo_root=repo_root,
		semantic_intake=True,
	)
	governor_meta = _governor_dialogue_meta(session)
	model_name, _reasoning = _governor_runtime_settings(repo_root)
	reasoning = "low"
	runtime_request_id = _next_id("governor-runtime")
	pending = {
		"runtimeKind": "semantic_intake",
		"runtimeRequestId": runtime_request_id,
		"requestId": request_id,
		"preferredAppServerThreadId": governor_meta.get("appServerThreadId")
		if isinstance(governor_meta.get("appServerThreadId"), str)
		else None,
		"initialPrompt": _initial_governor_semantic_intake_prompt(context["prompt"], repo_root=repo_root),
		"resumePrompt": _resume_governor_semantic_intake_prompt(context["prompt"]),
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
	_refresh_snapshot(
		session["model"],
		now,
		currentActor="governor",
		currentStage="semantic_intake",
		runState="running",
		transportState="connected",
	)
	return pending


def _append_completed_governor_dialogue_response(
	session: dict[str, Any],
	pending: dict[str, Any],
	body: str,
	now: str,
	*,
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
		_set_plan_ready_request(model, now, foreground_request_id=pending.get("requestId"))
	else:
		model["planReadyRequest"] = None
	model["activeForegroundRequestId"] = None
	return True


def _parse_governor_semantic_intake_payload(body: str) -> dict[str, Any] | None:
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


def _governor_semantic_proposal(payload: dict[str, Any]) -> dict[str, Any]:
	proposal = payload.get("proposal")
	if not isinstance(proposal, dict):
		proposal = payload
	return proposal


def _governor_semantic_user_copy(payload: dict[str, Any], fallback: str) -> str:
	return trim_text(payload.get("user_visible_reply") if isinstance(payload.get("user_visible_reply"), str) else "") or fallback


def _record_rejected_governor_semantic_proposal(
	session: dict[str, Any], pending: dict[str, Any], reason: str, proposal: Any
) -> None:
	session.setdefault("meta", {})["lastRejectedGovernorSemanticProposal"] = {
		"runtimeRequestId": pending.get("runtimeRequestId"),
		"requestId": pending.get("requestId"),
		"reason": reason,
		"proposal": proposal if isinstance(proposal, dict) else None,
		"rejectedAt": utc_now(),
	}


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
	permission = proposal.get("recommended_permission")
	return permission if permission in {"observe", "plan", "execute", "none"} else "none"


def _proposal_route(proposal: dict[str, Any]) -> str | None:
	route = proposal.get("route_type")
	return route if isinstance(route, str) else None


def _proposal_confidence(proposal: dict[str, Any]) -> str:
	confidence = proposal.get("confidence")
	return confidence if confidence in {"high", "low"} else "low"


def _proposal_normalized_intent(proposal: dict[str, Any], fallback: str) -> str:
	return trim_text(proposal.get("normalized_intent") if isinstance(proposal.get("normalized_intent"), str) else "") or fallback


def _governor_semantic_clarification_options(proposal: dict[str, Any]) -> list[dict[str, Any]]:
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


def _apply_governor_semantic_dialogue(
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
	if not _scope_satisfies(_current_permission_scope(model), "observe"):
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
				presentation_args={"scope": "observe"},
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
		initial_scope = _recommended_permission_scope(normalized)
	if initial_scope == "execute":
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_execute_without_plan_context",
			body=reply,
			proposal=proposal,
		)
		return
	_supersede_pending_permission_request(model, now, request_id=pending.get("requestId"))
	envelope = start_intake(prompt, normalized_text=normalized, repo_root=repo_root)
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
			presentation_args={"scope": required_scope},
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
	confidence = _proposal_confidence(proposal)
	if confidence != "high" and route != "block":
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_low_confidence",
			body=reply,
			proposal=proposal,
		)
		return
	if "permission_scope" in proposal:
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_direct_permission_mutation",
			body=reply,
			proposal=proposal,
		)
		return
	if route in {"clarification_reply", "execute", "dispatch"}:
		_reject_governor_semantic_proposal(
			session,
			pending,
			now,
			"semantic_intake_unsupported_state_claim",
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
		_set_plan_ready_request(model, now, foreground_request_id=request_id)
	else:
		model["planReadyRequest"] = None
	model["activeForegroundRequestId"] = None
	return True


def _initial_model(now: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	branch = git_branch_name(repo_root)
	return {
		"snapshot": {
			"sessionRef": _next_id("session"),
			"lane": None,
			"branch": branch,
			"task": None,
			"currentActor": "intake_shell",
			"currentStage": "idle",
			"permissionScope": "unset",
			"runState": "idle",
			"transportState": "connected",
			"pendingPermissionRequest": None,
			"pendingInterrupt": None,
			"recentArtifacts": [],
			"snapshotFreshness": {"receivedAt": now},
		},
		"feed": [
			_feed_item(
				"system_status",
				"Ready when you are",
				"Ask Corgi to work on this repo.",
				authoritative=True,
				now=now,
			)
		],
		"activeClarification": None,
		"activeForegroundRequestId": None,
		"acceptedIntakeSummary": None,
		"planReadyRequest": None,
	}


def _normalize_session(session: dict[str, Any], now: str, *, repo_root: str | Path | None = None) -> None:
	session.setdefault("meta", {})
	session["meta"].setdefault("activeIntakeRef", None)
	session["meta"].setdefault("processedRequestIds", {})
	session["meta"].setdefault("governorDialogue", {})
	model = session.setdefault("model", _initial_model(now, repo_root=repo_root))
	snapshot = model.setdefault("snapshot", {})
	snapshot.setdefault("sessionRef", _next_id("session"))
	snapshot.setdefault("lane", None)
	snapshot.setdefault("branch", git_branch_name(repo_root))
	snapshot.setdefault("task", None)
	snapshot.setdefault("currentActor", "intake_shell")
	snapshot.setdefault("currentStage", "idle")
	if "permissionScope" not in snapshot:
		legacy_access_mode = snapshot.get("accessMode")
		snapshot["permissionScope"] = (
			"execute" if legacy_access_mode == "full_access" else "unset"
		)
	snapshot.setdefault("runState", "idle")
	snapshot.setdefault("transportState", "connected")
	if "pendingPermissionRequest" not in snapshot:
		legacy_pending = snapshot.get("pendingApproval")
		if isinstance(legacy_pending, dict):
			snapshot["pendingPermissionRequest"] = {
				**legacy_pending,
				"recommendedScope": "plan",
				"allowedScopes": _allowed_permission_scopes("plan"),
			}
		else:
			snapshot["pendingPermissionRequest"] = None
	snapshot.setdefault("pendingInterrupt", None)
	snapshot.setdefault("recentArtifacts", [])
	snapshot.setdefault("snapshotFreshness", {"receivedAt": now})
	model.setdefault("feed", [])
	model.setdefault("activeClarification", None)
	model.setdefault("activeForegroundRequestId", None)
	model.setdefault("acceptedIntakeSummary", None)
	model.setdefault("planReadyRequest", None)
	if isinstance(model.get("activeClarification"), dict):
		model["activeClarification"].setdefault(
			"contextRef", model["activeClarification"].get("id")
		)
	if isinstance(snapshot.get("pendingPermissionRequest"), dict):
		snapshot["pendingPermissionRequest"].setdefault(
			"contextRef", snapshot["pendingPermissionRequest"].get("id")
		)
		snapshot["pendingPermissionRequest"].setdefault("recommendedScope", "plan")
		snapshot["pendingPermissionRequest"]["allowedScopes"] = _allowed_permission_scopes(
			snapshot["pendingPermissionRequest"].get("recommendedScope")
		)
		snapshot["pendingPermissionRequest"].setdefault(
			"continuationKind", "intake_acceptance"
		)
		snapshot["pendingPermissionRequest"].setdefault(
			"foregroundRequestId", None
		)
	if isinstance(snapshot.get("pendingInterrupt"), dict):
		snapshot["pendingInterrupt"].setdefault(
			"contextRef",
			f"interrupt:{snapshot['snapshotFreshness'].get('receivedAt', now)}",
		)
	if (
		model.get("planReadyRequest") is None
		and model.get("acceptedIntakeSummary")
		and snapshot.get("currentStage") == "plan_ready"
		and snapshot.get("permissionScope") == "plan"
		and not snapshot.get("pendingPermissionRequest")
		and not model.get("activeClarification")
		and snapshot.get("runState") != "running"
	):
		_set_plan_ready_request(
			model,
			now,
			foreground_request_id=model.get("activeForegroundRequestId"),
			advance_version=False,
		)


def load_session(repo_root: str | Path | None = None) -> dict[str, Any]:
	now = utc_now()
	session_path = resolve_paths(repo_root).ui_session_path
	payload = load_json(session_path, default=None)
	if payload is None:
		payload = {
			"model": _initial_model(now, repo_root=repo_root),
			"meta": {"activeIntakeRef": None},
		}
		_normalize_session(payload, now, repo_root=repo_root)
		write_json(session_path, payload)
		return payload
	_normalize_session(payload, now, repo_root=repo_root)
	return payload


def save_session(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	write_json(resolve_paths(repo_root).ui_session_path, session)


def _refresh_snapshot(model: dict[str, Any], now: str, **overrides: Any) -> None:
	model["snapshot"].update(overrides)
	model["snapshot"]["snapshotFreshness"] = {"receivedAt": now}


def public_model(session: dict[str, Any]) -> dict[str, Any]:
	return session["model"]


def _semantic_provenance(
	*,
	turn_type: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	in_response_to_request_id: str | None = None,
) -> dict[str, Any]:
	return {
		"turn_type": turn_type,
		"semantic_input_version": semantic_input_version,
		"semantic_summary_ref": semantic_summary_ref,
		"semantic_context_flags": semantic_context_flags,
		"semantic_route_type": semantic_route_type,
		"semantic_confidence": semantic_confidence,
		"semantic_block_reason": semantic_block_reason,
		"semantic_paraphrase": semantic_paraphrase,
		"semantic_normalized_text": semantic_normalized_text,
		"in_response_to_request_id": in_response_to_request_id,
	}


def _append_user_turn(
	model: dict[str, Any],
	now: str,
	*,
	title: str,
	body: str,
	turn_type: str | None = None,
	semantic_input_version: str | None = None,
	semantic_summary_ref: str | None = None,
	semantic_context_flags: dict[str, Any] | None = None,
	semantic_route_type: str | None = None,
	semantic_confidence: str | None = None,
	semantic_block_reason: str | None = None,
	semantic_paraphrase: str | None = None,
	semantic_normalized_text: str | None = None,
	in_response_to_request_id: str | None = None,
) -> None:
	model["feed"].append(
		_feed_item(
			"user_message",
			title,
			body,
			authoritative=False,
			now=now,
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
				in_response_to_request_id=in_response_to_request_id,
			),
		)
	)


def _current_permission_scope(model: dict[str, Any]) -> str:
	return model["snapshot"].get("permissionScope") or "unset"


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
	model["feed"].append(
		_feed_item(
			"error",
			title,
			body,
			authoritative=True,
			now=now,
			source_artifact_ref=source_artifact_ref,
			in_response_to_request_id=in_response_to_request_id,
			presentation_key=presentation_key,
			presentation_args=presentation_args or {"title": title, "body": body},
		)
	)
	_refresh_snapshot(model, now)


def _processed_request_ids(session: dict[str, Any]) -> dict[str, Any]:
	meta = session.setdefault("meta", {})
	processed = meta.setdefault("processedRequestIds", {})
	if isinstance(processed, dict):
		return processed
	meta["processedRequestIds"] = {}
	return meta["processedRequestIds"]


def _is_duplicate_request(session: dict[str, Any], request_id: str | None) -> bool:
	if not request_id:
		return False
	return request_id in _processed_request_ids(session)


def _remember_request(session: dict[str, Any], request_id: str | None, command: str, now: str) -> None:
	if not request_id:
		return
	_processed_request_ids(session)[request_id] = {"command": command, "handledAt": now}


def _parse_received_at(value: str | None) -> Any:
	return session_state.parse_received_at(value)


def _is_snapshot_stale(snapshot: dict[str, Any], now: str) -> bool:
	return session_state.is_snapshot_stale(snapshot, now)


def _current_interrupt_context_ref(model: dict[str, Any]) -> str:
	return f"interrupt:{model['snapshot']['snapshotFreshness'].get('receivedAt') or utc_now()}"


def _context_matches(expected_context_ref: str | None, provided_context_ref: str | None) -> bool:
	return session_state.context_matches(expected_context_ref, provided_context_ref)


def _session_ref_matches(model: dict[str, Any], provided_session_ref: str | None) -> bool:
	return session_state.session_ref_matches(model, provided_session_ref)


def _permission_rank(scope: str | None) -> int:
	return session_state.permission_rank(scope)


def _scope_satisfies(current_scope: str | None, required_scope: str | None) -> bool:
	return session_state.scope_satisfies(current_scope, required_scope)


def _allowed_permission_scopes(required_scope: str | None) -> list[str]:
	return session_state.allowed_permission_scopes(required_scope)


def _format_permission_scope(scope: str | None) -> str:
	return session_state.format_permission_scope(scope)


def _should_request_execute_for_accepted_continuation(
	model: dict[str, Any], semantic_context_flags: dict[str, Any] | None
) -> bool:
	return bool(
		model.get("acceptedIntakeSummary")
		and model["snapshot"].get("permissionScope") == "plan"
		and model["snapshot"].get("currentStage") == "plan_ready"
		and isinstance(semantic_context_flags, dict)
		and semantic_context_flags.get("used_accepted_intake_summary")
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
	request_id = _next_id("permission")
	return {
		"id": request_id,
		"contextRef": request_id,
		"title": "Permission needed",
		"body": f"Choose {recommended_scope} if you want Corgi to continue this request.",
		"recommendedScope": recommended_scope,
		"allowedScopes": _allowed_permission_scopes(recommended_scope),
		"continuationKind": continuation_kind,
		"pendingPrompt": pending_prompt,
		"pendingNormalizedText": pending_normalized_text,
		"foregroundRequestId": foreground_request_id,
		"requestedAt": now,
	}


def _build_plan_ready_request(
	model: dict[str, Any], now: str, *, foreground_request_id: str | None = None
) -> dict[str, Any] | None:
	summary = model.get("acceptedIntakeSummary")
	if not isinstance(summary, dict):
		return None
	request_id = _next_id("plan-ready")
	plan_version = int(model.get("planVersion") or 1)
	return {
		"id": request_id,
		"contextRef": request_id,
		"planContextRef": request_id,
		"planVersion": plan_version,
		"title": "Plan ready",
		"body": "Review the Governor plan, then execute it or add details for a revision.",
		"requestedAt": now,
		"foregroundRequestId": foreground_request_id,
		"acceptedIntakeSummary": summary,
		"allowedActions": ["execute_plan", "revise_plan"],
	}


def _accepted_intake_ref(session: dict[str, Any], repo_root: str | Path | None = None) -> str | None:
	return session_execution.accepted_intake_ref(session, repo_root)


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
	return session_execution.emit_plan_execution_dispatch(
		session,
		now,
		repo_root=repo_root,
		request_id=request_id,
		next_id=_next_id,
		append_error=_append_error,
	)


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
	model: dict[str, Any],
	now: str,
	*,
	foreground_request_id: str | None = None,
	advance_version: bool = True,
) -> None:
	if advance_version:
		model["planVersion"] = int(model.get("planVersion") or 0) + 1
	else:
		model["planVersion"] = int(model.get("planVersion") or 1)
	model["planReadyRequest"] = _build_plan_ready_request(
		model, now, foreground_request_id=foreground_request_id
	)


def _recommended_permission_scope(prompt: str) -> str:
	lower = prompt.lower().strip()
	if any(
		lower == token or lower.startswith(f"{token} ")
		for token in (
			"implement",
			"build",
			"create",
			"refactor",
			"fix",
			"debug",
			"update",
			"change",
			"write",
		)
	):
		return "execute"
	return "plan"


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
			model["snapshot"]["recentArtifacts"] = (
				decision["artifacts"] + review["artifacts"] + execution["artifacts"] + artifacts
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
	_refresh_snapshot(
		model,
		now,
		currentActor="orchestration",
		currentStage="dispatch_queued" if permission_scope == "execute" else "intake_accepted",
		runState="queued" if permission_scope == "execute" else "idle",
		transportState="connected",
	)
	if permission_scope == "execute" and auto_consume_executor:
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
	if session_ref is not None and not _session_ref_matches(model, session_ref):
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
		if not _scope_satisfies(_current_permission_scope(model), "observe"):
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
					presentation_args={"scope": "observe"},
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

	if _should_request_execute_for_accepted_continuation(model, semantic_context_flags):
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
				presentation_args={"scope": "execute"},
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
	required_scope = _recommended_permission_scope(semantic_prompt)
	if _scope_satisfies(_current_permission_scope(model), required_scope):
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
			permission_scope=_current_permission_scope(model),
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
			presentation_args={"scope": required_scope},
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
	if session_ref is not None and not _session_ref_matches(model, session_ref):
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
	if not _context_matches(expected_context_ref, context_ref):
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
	required_scope = _recommended_permission_scope(semantic_answer)
	if _scope_satisfies(_current_permission_scope(model), required_scope):
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
			permission_scope=_current_permission_scope(model),
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
			presentation_args={"scope": required_scope},
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
	if session_ref is not None and not _session_ref_matches(model, session_ref):
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
	if not _context_matches(expected_context_ref, context_ref):
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
	if not _scope_satisfies(permission_scope, recommended_scope):
		_append_error(
			model,
			"Permission scope too low",
			f"Choose {_format_permission_scope(recommended_scope)} or higher to continue this request.",
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
			model["snapshot"]["recentArtifacts"] = (
				decision["artifacts"] + review["artifacts"] + execution["artifacts"] + existing_artifacts
			)
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
	auto_consume_executor: bool = False,
) -> None:
	now = utc_now()
	model = session["model"]
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
	if session_ref is not None and not _session_ref_matches(model, session_ref):
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
		_append_error(
			model,
			"No plan is ready",
			"There is no current plan checkpoint to execute.",
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
	if not _context_matches(plan_ready.get("contextRef"), context_ref):
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
		model["snapshot"]["recentArtifacts"] = (
			decision["artifacts"] + review["artifacts"] + execution["artifacts"] + existing_artifacts
		)
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
	if session_ref is not None and not _session_ref_matches(model, session_ref):
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
	if not _context_matches(plan_ready.get("contextRef"), context_ref):
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
		app_server_thread_id=thread_id,
		app_server_turn_id=turn_id,
		app_server_item_id=item_id,
		runtime_source=runtime_source,
	)
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
	if session_ref is not None and not _session_ref_matches(model, session_ref):
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
	if not _context_matches(expected_context_ref, context_ref):
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
	if session_ref is not None and not _session_ref_matches(model, session_ref):
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
	expected_context_ref = _current_interrupt_context_ref(model)
	if not _context_matches(expected_context_ref, context_ref):
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
		and not _is_snapshot_stale(model["snapshot"], now)
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
	if command not in {"state", "complete_governor_turn", "fallback_governor_turn", "fail_governor_turn"} and _is_duplicate_request(session, request_id):
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
		_remember_request(session, request_id, command, now)
	save_session(session, repo_root=repo_root)
	pending = _pending_governor_runtime_request(session)
	if governor_runtime == "external" and pending:
		return {
			"kind": "governor_runtime_request",
			"model": public_model(session),
			"request": _build_governor_runtime_request_envelope(pending),
		}
	return public_model(session)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="UI session bridge for orchestration-backed extension state")
	subparsers = parser.add_subparsers(dest="command", required=True)

	subparsers.add_parser("state")

	def add_governor_runtime(parser: argparse.ArgumentParser) -> None:
		parser.add_argument("--governor-runtime", choices=["exec", "external"], default="exec")

	submit = subparsers.add_parser("submit_prompt")
	submit.add_argument("--text", required=True)
	submit.add_argument("--request-id")
	submit.add_argument("--session-ref")
	submit.add_argument("--context-ref")
	submit.add_argument("--semantic-mode", choices=["sidecar-first", "governor-first"])
	submit.add_argument("--turn-type")
	submit.add_argument("--normalized-text")
	submit.add_argument("--paraphrase")
	submit.add_argument("--semantic-input-version")
	submit.add_argument("--semantic-summary-ref")
	submit.add_argument("--semantic-context-flags-json")
	submit.add_argument("--semantic-route-type")
	submit.add_argument("--semantic-confidence")
	submit.add_argument("--semantic-block-reason")
	submit.add_argument("--auto-consume-executor", action="store_true")
	add_governor_runtime(submit)

	answer = subparsers.add_parser("answer_clarification")
	answer.add_argument("--text", required=True)
	answer.add_argument("--request-id")
	answer.add_argument("--session-ref")
	answer.add_argument("--context-ref")
	answer.add_argument("--turn-type")
	answer.add_argument("--normalized-text")
	answer.add_argument("--paraphrase")
	answer.add_argument("--semantic-input-version")
	answer.add_argument("--semantic-summary-ref")
	answer.add_argument("--semantic-context-flags-json")
	answer.add_argument("--semantic-route-type")
	answer.add_argument("--semantic-confidence")
	answer.add_argument("--semantic-block-reason")
	answer.add_argument("--auto-consume-executor", action="store_true")
	add_governor_runtime(answer)

	set_scope = subparsers.add_parser("set_permission_scope")
	set_scope.add_argument("--text")
	set_scope.add_argument("--request-id")
	set_scope.add_argument("--session-ref")
	set_scope.add_argument("--context-ref")
	set_scope.add_argument("--permission-scope", required=True)
	set_scope.add_argument("--turn-type")
	set_scope.add_argument("--normalized-text")
	set_scope.add_argument("--paraphrase")
	set_scope.add_argument("--semantic-input-version")
	set_scope.add_argument("--semantic-summary-ref")
	set_scope.add_argument("--semantic-context-flags-json")
	set_scope.add_argument("--semantic-route-type")
	set_scope.add_argument("--semantic-confidence")
	set_scope.add_argument("--semantic-block-reason")
	set_scope.add_argument("--auto-consume-executor", action="store_true")
	add_governor_runtime(set_scope)
	decline = subparsers.add_parser("decline_permission")
	decline.add_argument("--request-id")
	decline.add_argument("--session-ref")
	decline.add_argument("--context-ref")
	execute_plan = subparsers.add_parser("execute_plan")
	execute_plan.add_argument("--request-id")
	execute_plan.add_argument("--session-ref")
	execute_plan.add_argument("--context-ref")
	execute_plan.add_argument("--auto-consume-executor", action="store_true")
	revise_plan = subparsers.add_parser("revise_plan")
	revise_plan.add_argument("--text", required=True)
	revise_plan.add_argument("--request-id")
	revise_plan.add_argument("--session-ref")
	revise_plan.add_argument("--context-ref")
	add_governor_runtime(revise_plan)
	complete_governor = subparsers.add_parser("complete_governor_turn")
	complete_governor.add_argument("--runtime-request-id", required=True)
	complete_governor.add_argument("--body", required=True)
	complete_governor.add_argument("--thread-id")
	complete_governor.add_argument("--turn-id")
	complete_governor.add_argument("--item-id")
	complete_governor.add_argument("--runtime-source", default="app-server")
	fallback_governor = subparsers.add_parser("fallback_governor_turn")
	fallback_governor.add_argument("--runtime-request-id", required=True)
	fallback_governor.add_argument("--reason")
	fail_governor = subparsers.add_parser("fail_governor_turn")
	fail_governor.add_argument("--runtime-request-id", required=True)
	fail_governor.add_argument("--reason")
	interrupt = subparsers.add_parser("interrupt_run")
	interrupt.add_argument("--text")
	interrupt.add_argument("--request-id")
	interrupt.add_argument("--session-ref")
	interrupt.add_argument("--context-ref")
	interrupt.add_argument("--turn-type")
	interrupt.add_argument("--normalized-text")
	interrupt.add_argument("--paraphrase")
	interrupt.add_argument("--semantic-input-version")
	interrupt.add_argument("--semantic-summary-ref")
	interrupt.add_argument("--semantic-context-flags-json")
	interrupt.add_argument("--semantic-route-type")
	interrupt.add_argument("--semantic-confidence")
	interrupt.add_argument("--semantic-block-reason")
	reconnect = subparsers.add_parser("reconnect")
	reconnect.add_argument("--request-id")
	reconnect.add_argument("--session-ref")
	return parser


def main(argv: list[str] | None = None, *, repo_root: str | Path | None = None) -> int:
	args = build_parser().parse_args(argv)
	try:
		semantic_context_flags = None
		if getattr(args, "semantic_context_flags_json", None):
			semantic_context_flags = json.loads(args.semantic_context_flags_json)
		model = dispatch_session_action(
			args.command,
			text=getattr(args, "text", None),
			repo_root=repo_root,
			session_ref=getattr(args, "session_ref", None),
			request_id=getattr(args, "request_id", None),
			context_ref=getattr(args, "context_ref", None),
			permission_scope=getattr(args, "permission_scope", None),
			semantic_mode=getattr(args, "semantic_mode", None),
			turn_type=getattr(args, "turn_type", None),
			normalized_text=getattr(args, "normalized_text", None),
			paraphrase=getattr(args, "paraphrase", None),
			semantic_input_version=getattr(args, "semantic_input_version", None),
			semantic_summary_ref=getattr(args, "semantic_summary_ref", None),
			semantic_context_flags=semantic_context_flags,
			semantic_route_type=getattr(args, "semantic_route_type", None),
			semantic_confidence=getattr(args, "semantic_confidence", None),
			semantic_block_reason=getattr(args, "semantic_block_reason", None),
			governor_runtime=getattr(args, "governor_runtime", "exec"),
			runtime_request_id=getattr(args, "runtime_request_id", None),
			runtime_body=getattr(args, "body", None),
			runtime_thread_id=getattr(args, "thread_id", None),
			runtime_turn_id=getattr(args, "turn_id", None),
			runtime_item_id=getattr(args, "item_id", None),
			runtime_source=getattr(args, "runtime_source", "app-server"),
			fallback_reason=getattr(args, "reason", None),
			auto_consume_executor=bool(getattr(args, "auto_consume_executor", False)),
		)
	except (ValueError, json.JSONDecodeError) as exc:
		raise SystemExit(str(exc))
	print(json.dumps(model, indent=2, sort_keys=True))
	return 0
