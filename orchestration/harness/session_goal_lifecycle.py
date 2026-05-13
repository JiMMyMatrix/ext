from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from typing import Any, Callable

from orchestration.harness import intake
from orchestration.harness import session_execution
from orchestration.harness import session_work_lifecycle
from orchestration.harness.accepted_dispatch import (
	accepted_dispatch_blockers,
	dispatch_ref_from_decision_ref,
)
from orchestration.harness.paths import (
	default_lane,
	git_branch_name,
	load_json,
	repo_relative,
	resolve_paths,
	summarize,
	trim_text,
	validate_then_write,
)


NextId = Callable[[str], str]
ArtifactFactory = Callable[..., dict[str, Any]]
FeedItemFactory = Callable[..., dict[str, Any]]


DEFAULT_GOAL_STEPS = [
	{
		"title": "Create the base Pet Life Diary app",
		"objective": "Build a simple static Pet Life Diary app from scratch. Include a minimal UI, sample data, and README. Keep the project structure ready for small follow-up improvements.",
		"expected_output": "README.md, index.html, src/app.js, src/styles.css, and data/sample-pets.json exist in the scratch workspace.",
		"prompt_preset": "pet-life-diary-goal-base",
	},
	{
		"title": "Add species filtering",
		"objective": "Add a simple species filter to the existing pet diary app so users can show all entries or only Corgi/Cat entries. Keep the UI simple and preserve the existing app structure.",
		"expected_output": "index.html and src/app.js are updated with a working species filter.",
		"prompt_preset": "pet-life-diary-filter",
	},
	{
		"title": "Polish the demo README",
		"objective": "Polish the Pet Life Diary README so the project reads like a small portfolio demo. Include demo overview, files, how to open it, and what was improved.",
		"expected_output": "README.md explains the demo clearly for a human reviewer.",
		"prompt_preset": "pet-life-diary-readme-polish",
	},
]

PRODUCT_GOAL_STEPS = [
	{
		"title": "Create the product-scale Pet Life Diary app",
		"objective": "Build the realistic product-scale Pet Life Diary static web app foundation from scratch. Include multiple screens, local persistence, search and filters, analytics, sample data, validation notes, and several thousand lines of project code/data/docs.",
		"expected_output": "README.md, index.html, product JavaScript modules, styles, sample data, and validation script exist in the scratch workspace.",
		"prompt_preset": "pet-life-diary-product-benchmark",
	},
	{
		"title": "Add care routine planning",
		"objective": "Improve the existing product-scale Pet Life Diary app with a care routine planning surface. Add routine data/state, a routine board UI, and simple documentation while preserving the current app structure.",
		"expected_output": "index.html, src/state.js, src/ui.js, src/styles.css, and README.md are updated with care routine planning.",
		"prompt_preset": "pet-life-diary-product-routines",
	},
	{
		"title": "Prepare the portfolio demo handoff",
		"objective": "Polish the existing Pet Life Diary product demo for portfolio review. Add a concise product spec, strengthen README demo-readiness notes, and update validation notes without recreating the app.",
		"expected_output": "README.md, docs/product-spec.md, and tests/product-validation.js explain the demo, validation, and review checklist.",
		"prompt_preset": "pet-life-diary-product-portfolio",
	},
]

GOAL_PLAN_MAX_STEPS = 6


class GoalPlanValidationError(ValueError):
	pass


def goals_root(repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).agent_root / "goals"


def goal_dir(goal_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return goals_root(repo_root) / goal_ref


def goal_json_path(goal_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return goal_dir(goal_ref, repo_root=repo_root) / "goal.json"


def goal_plan_path(goal_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return goal_dir(goal_ref, repo_root=repo_root) / "goal_plan.json"


def goal_progress_path(goal_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return goal_dir(goal_ref, repo_root=repo_root) / "goal_progress.json"


def goal_decision_path(goal_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return goal_dir(goal_ref, repo_root=repo_root) / "goal_decision.json"


def load_goal_plan(goal_ref: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	return load_json(goal_plan_path(goal_ref, repo_root=repo_root))


def load_goal_progress(goal_ref: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	return load_json(goal_progress_path(goal_ref, repo_root=repo_root))


def load_goal(goal_ref: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	return load_json(goal_json_path(goal_ref, repo_root=repo_root))


def _require_string(payload: dict[str, Any], field: str, failures: list[str], prefix: str) -> None:
	if not isinstance(payload.get(field), str) or not payload.get(field).strip():
		failures.append(f"{prefix}: {field} must be a non-empty string")


def validate_goal_payload(
	payload: Any,
	failures: list[str],
	*,
	expected_goal_ref: str | None = None,
) -> None:
	if not isinstance(payload, dict):
		failures.append("invalid_goal_artifact: goal must be an object")
		return
	if payload.get("schema_version") != "corgi.goal.v1":
		failures.append("invalid_goal_artifact: goal schema_version must be corgi.goal.v1")
	_require_string(payload, "goal_ref", failures, "invalid_goal_artifact")
	_require_string(payload, "title", failures, "invalid_goal_artifact")
	_require_string(payload, "original_goal", failures, "invalid_goal_artifact")
	if expected_goal_ref and payload.get("goal_ref") != expected_goal_ref:
		failures.append("invalid_goal_artifact: goal_ref mismatch")
	if payload.get("status") not in {"active", "completed", "blocked"}:
		failures.append("invalid_goal_artifact: goal status is invalid")
	_require_string(payload, "created_at", failures, "invalid_goal_artifact")
	_require_string(payload, "updated_at", failures, "invalid_goal_artifact")


def validate_goal_plan_payload(
	payload: Any,
	failures: list[str],
	*,
	expected_goal_ref: str | None = None,
) -> None:
	if not isinstance(payload, dict):
		failures.append("invalid_goal_artifact: goal_plan must be an object")
		return
	if payload.get("schema_version") != "corgi.goal_plan.v1":
		failures.append("invalid_goal_artifact: goal_plan schema_version must be corgi.goal_plan.v1")
	_require_string(payload, "goal_ref", failures, "invalid_goal_artifact")
	if expected_goal_ref and payload.get("goal_ref") != expected_goal_ref:
		failures.append("invalid_goal_artifact: goal_plan goal_ref mismatch")
	plan_version = payload.get("plan_version")
	if not isinstance(plan_version, int) or plan_version < 1:
		failures.append("invalid_goal_artifact: goal_plan plan_version must be a positive integer")
	steps = payload.get("steps")
	if not isinstance(steps, list) or not steps:
		failures.append("invalid_goal_artifact: goal_plan steps must be a non-empty list")
		return
	if len(steps) > GOAL_PLAN_MAX_STEPS:
		failures.append(f"invalid_goal_artifact: goal_plan steps must be <= {GOAL_PLAN_MAX_STEPS}")
	seen_refs: set[str] = set()
	for index, step in enumerate(steps, start=1):
		if not isinstance(step, dict):
			failures.append(f"invalid_goal_artifact: goal_plan step {index} must be an object")
			continue
		for field in ["step_ref", "title", "objective", "expected_output", "status"]:
			_require_string(step, field, failures, "invalid_goal_artifact")
		step_ref = step.get("step_ref")
		if isinstance(step_ref, str):
			if step_ref in seen_refs:
				failures.append(f"invalid_goal_artifact: duplicate goal step ref {step_ref}")
		if step.get("step_index") != index:
			failures.append(f"invalid_goal_artifact: goal_plan step_index mismatch at {index}")
		if step.get("status") not in {"pending", "active", "completed", "blocked"}:
			failures.append(f"invalid_goal_artifact: goal_plan step status is invalid at {index}")
		dependency = step.get("depends_on_step_ref")
		if dependency is not None and dependency not in seen_refs:
			failures.append(f"invalid_goal_artifact: goal_plan dependency must reference earlier step at {index}")
		if isinstance(step_ref, str):
			seen_refs.add(step_ref)


def validate_goal_progress_payload(
	payload: Any,
	failures: list[str],
	*,
	expected_goal_ref: str | None = None,
	plan: dict[str, Any] | None = None,
) -> None:
	if not isinstance(payload, dict):
		failures.append("invalid_goal_artifact: goal_progress must be an object")
		return
	if payload.get("schema_version") != "corgi.goal_progress.v1":
		failures.append("invalid_goal_artifact: goal_progress schema_version must be corgi.goal_progress.v1")
	_require_string(payload, "goal_ref", failures, "invalid_goal_artifact")
	if expected_goal_ref and payload.get("goal_ref") != expected_goal_ref:
		failures.append("invalid_goal_artifact: goal_progress goal_ref mismatch")
	status = payload.get("status")
	if status not in {"active", "completed", "blocked"}:
		failures.append("invalid_goal_artifact: goal_progress status is invalid")
	steps = [step for step in (plan or {}).get("steps", []) if isinstance(step, dict)]
	step_by_ref = {
		step.get("step_ref"): step
		for step in steps
		if isinstance(step.get("step_ref"), str)
	}
	current_ref = payload.get("current_step_ref")
	current_index = payload.get("current_step_index")
	if status == "active":
		if not isinstance(current_ref, str) or not current_ref.strip():
			failures.append("invalid_goal_artifact: active goal_progress requires current_step_ref")
		if not isinstance(current_index, int) or current_index < 1:
			failures.append("invalid_goal_artifact: active goal_progress requires current_step_index")
	if isinstance(current_ref, str) and step_by_ref:
		step = step_by_ref.get(current_ref)
		if not step:
			failures.append("invalid_goal_artifact: current_step_ref is not in goal_plan")
		elif step.get("step_index") != current_index:
			failures.append("invalid_goal_artifact: current_step_index does not match goal_plan")
	completed = payload.get("completed_steps")
	if not isinstance(completed, list):
		failures.append("invalid_goal_artifact: completed_steps must be a list")
	else:
		for item in completed:
			if not isinstance(item, dict) or not isinstance(item.get("step_ref"), str):
				failures.append("invalid_goal_artifact: completed_steps entries must include step_ref")
				continue
			if step_by_ref and item.get("step_ref") not in step_by_ref:
				failures.append("invalid_goal_artifact: completed step is not in goal_plan")
	linked_work_refs = payload.get("linked_work_refs")
	if not isinstance(linked_work_refs, list) or not all(
		isinstance(item, str) for item in linked_work_refs
	):
		failures.append("invalid_goal_artifact: linked_work_refs must be a string list")


def validate_goal_decision_payload(
	payload: Any,
	failures: list[str],
	*,
	expected_goal_ref: str | None = None,
) -> None:
	if not isinstance(payload, dict):
		failures.append("invalid_goal_artifact: goal_decision must be an object")
		return
	if payload.get("schema_version") != "corgi.goal_decision.v1":
		failures.append("invalid_goal_artifact: goal_decision schema_version must be corgi.goal_decision.v1")
	_require_string(payload, "goal_ref", failures, "invalid_goal_artifact")
	if expected_goal_ref and payload.get("goal_ref") != expected_goal_ref:
		failures.append("invalid_goal_artifact: goal_decision goal_ref mismatch")
	if payload.get("decision") not in {"accept", "block"}:
		failures.append("invalid_goal_artifact: goal_decision decision is invalid")
	_require_string(payload, "reason", failures, "invalid_goal_artifact")
	if not isinstance(payload.get("completed_steps"), list):
		failures.append("invalid_goal_artifact: goal_decision completed_steps must be a list")
	if not isinstance(payload.get("linked_work_refs"), list):
		failures.append("invalid_goal_artifact: goal_decision linked_work_refs must be a list")
	_require_string(payload, "recorded_at", failures, "invalid_goal_artifact")


def _write_goal(goal_ref: str, payload: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	validate_then_write(
		goal_json_path(goal_ref, repo_root=repo_root),
		payload,
		lambda item, failures: validate_goal_payload(
			item,
			failures,
			expected_goal_ref=goal_ref,
		),
	)


def _write_goal_plan(goal_ref: str, payload: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	validate_then_write(
		goal_plan_path(goal_ref, repo_root=repo_root),
		payload,
		lambda item, failures: validate_goal_plan_payload(
			item,
			failures,
			expected_goal_ref=goal_ref,
		),
	)


def _write_goal_progress(
	goal_ref: str,
	payload: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
	plan: dict[str, Any] | None = None,
) -> None:
	plan_payload = plan
	if plan_payload is None and goal_plan_path(goal_ref, repo_root=repo_root).exists():
		plan_payload = load_goal_plan(goal_ref, repo_root=repo_root)
	validate_then_write(
		goal_progress_path(goal_ref, repo_root=repo_root),
		payload,
		lambda item, failures: validate_goal_progress_payload(
			item,
			failures,
			expected_goal_ref=goal_ref,
			plan=plan_payload,
		),
	)


def _write_goal_decision(goal_ref: str, payload: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	validate_then_write(
		goal_decision_path(goal_ref, repo_root=repo_root),
		payload,
		lambda item, failures: validate_goal_decision_payload(
			item,
			failures,
			expected_goal_ref=goal_ref,
		),
	)


def save_goal_progress(
	goal_ref: str,
	progress: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> None:
	_write_goal_progress(goal_ref, progress, repo_root=repo_root)


def update_goal_plan_step(
	goal_ref: str,
	step_ref: str,
	updates: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> None:
	plan = load_goal_plan(goal_ref, repo_root=repo_root)
	steps = []
	for raw_step in plan.get("steps", []):
		if isinstance(raw_step, dict) and raw_step.get("step_ref") == step_ref:
			steps.append({**raw_step, **updates})
		else:
			steps.append(raw_step)
	plan["steps"] = steps
	_write_goal_plan(goal_ref, plan, repo_root=repo_root)


def default_goal_steps() -> list[dict[str, Any]]:
	if os.environ.get("ORCHESTRATION_TEST_PROMPT_PRESET") == "pet-life-diary-product-goal":
		return PRODUCT_GOAL_STEPS
	return DEFAULT_GOAL_STEPS


def normalize_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
	normalized: list[dict[str, Any]] = []
	for index, raw_step in enumerate(steps or default_goal_steps(), start=1):
		title = trim_text(raw_step.get("title")) or f"Goal step {index}"
		objective = trim_text(raw_step.get("objective")) or title
		expected_output = trim_text(raw_step.get("expected_output")) or "Bounded step output is produced."
		normalized.append(
			{
				"step_ref": f"step-{index:02d}",
				"step_index": index,
				"title": title,
				"objective": objective,
				"expected_output": expected_output,
				"depends_on_step_ref": raw_step.get("depends_on_step_ref"),
				"prompt_preset": trim_text(raw_step.get("prompt_preset")) or None,
				"status": "pending",
				"work_ref": None,
			}
		)
	return normalized


def _normalize_steps_from_index(
	steps: list[dict[str, Any]],
	*,
	start_index: int,
) -> list[dict[str, Any]]:
	normalized: list[dict[str, Any]] = []
	local_to_global_refs: dict[str, str] = {}
	for offset, raw_step in enumerate(steps, start=0):
		index = start_index + offset
		local_ref = f"step-{offset + 1:02d}"
		global_ref = f"step-{index:02d}"
		local_to_global_refs[local_ref] = global_ref
		depends_on = raw_step.get("depends_on_step_ref")
		if isinstance(depends_on, str) and depends_on in local_to_global_refs:
			depends_on = local_to_global_refs[depends_on]
		normalized.append(
			{
				"step_ref": global_ref,
				"step_index": index,
				"title": trim_text(raw_step.get("title")) or f"Goal step {index}",
				"objective": (
					trim_text(raw_step.get("objective"))
					or trim_text(raw_step.get("title"))
					or f"Goal step {index}"
				),
				"expected_output": trim_text(raw_step.get("expected_output")) or "Bounded step output is produced.",
				"depends_on_step_ref": depends_on or None,
				"prompt_preset": trim_text(raw_step.get("prompt_preset")) or None,
				"status": "pending",
				"work_ref": None,
			}
		)
	return normalized


def parse_governor_goal_plan_response(body: str) -> tuple[str, list[dict[str, Any]]]:
	payload = _extract_json_payload(body)
	if not isinstance(payload, dict):
		raise GoalPlanValidationError("Governor goal plan must be a JSON object.")
	reply = trim_text(payload.get("user_visible_reply"))
	steps = payload.get("steps")
	if not isinstance(steps, list):
		raise GoalPlanValidationError("Governor goal plan must include a steps array.")
	return reply, validate_goal_steps(steps)


def validate_goal_steps(steps: list[Any]) -> list[dict[str, Any]]:
	if not steps:
		raise GoalPlanValidationError("Goal plan must contain at least one step.")
	if len(steps) > GOAL_PLAN_MAX_STEPS:
		raise GoalPlanValidationError(f"Goal plan cannot contain more than {GOAL_PLAN_MAX_STEPS} steps.")
	seen_refs: set[str] = set()
	validated: list[dict[str, Any]] = []
	for index, raw_step in enumerate(steps, start=1):
		if not isinstance(raw_step, dict):
			raise GoalPlanValidationError(f"Goal step {index} must be an object.")
		title = trim_text(raw_step.get("title"))
		objective = trim_text(raw_step.get("objective"))
		expected_output = trim_text(raw_step.get("expected_output"))
		if not title or not objective or not expected_output:
			raise GoalPlanValidationError(
				f"Goal step {index} must include title, objective, and expected_output."
			)
		if len(objective) > 700 or len(expected_output) > 500:
			raise GoalPlanValidationError(f"Goal step {index} is too broad for a bounded step.")
		step_ref = f"step-{index:02d}"
		depends_on = raw_step.get("depends_on_step_ref")
		if depends_on is not None:
			depends_on = trim_text(depends_on)
			if depends_on and depends_on not in seen_refs:
				raise GoalPlanValidationError(
					f"Goal step {index} depends on an unknown or later step."
				)
		validated.append(
			{
				"title": title,
				"objective": objective,
				"expected_output": expected_output,
				"depends_on_step_ref": depends_on or None,
				"prompt_preset": trim_text(raw_step.get("prompt_preset")) or None,
			}
		)
		seen_refs.add(step_ref)
	return validated


def _extract_json_payload(body: str) -> Any:
	text = trim_text(body)
	if not text:
		raise GoalPlanValidationError("Governor goal plan was empty.")
	try:
		return json.loads(text)
	except json.JSONDecodeError:
		start = text.find("{")
		end = text.rfind("}")
		if start < 0 or end <= start:
			raise GoalPlanValidationError("Governor goal plan did not contain JSON.") from None
		try:
			return json.loads(text[start : end + 1])
		except json.JSONDecodeError as exc:
			raise GoalPlanValidationError("Governor goal plan JSON could not be parsed.") from exc


def apply_goal_snapshot(
	session: dict[str, Any],
	*,
	goal_ref: str | None,
	goal_title: str | None,
	step: dict[str, Any] | None,
	step_count: int | None,
	status: str | None,
	latest_decision_ref: str | None = None,
) -> None:
	model = session["model"]
	snapshot = model["snapshot"]
	model["currentGoalRef"] = goal_ref
	model["currentGoalTitle"] = goal_title
	model["currentGoalStepRef"] = step.get("step_ref") if step else None
	model["currentGoalStepIndex"] = step.get("step_index") if step else None
	model["goalStepCount"] = step_count
	model["goalStatus"] = status
	model["latestGoalDecisionRef"] = latest_decision_ref
	snapshot["currentGoalRef"] = goal_ref
	snapshot["currentGoalTitle"] = goal_title
	snapshot["currentGoalStepRef"] = step.get("step_ref") if step else None
	snapshot["currentGoalStepIndex"] = step.get("step_index") if step else None
	snapshot["goalStepCount"] = step_count
	snapshot["goalStatus"] = status
	snapshot["latestGoalDecisionRef"] = latest_decision_ref


def create_goal_program(
	session: dict[str, Any],
	now: str,
	goal_text: str,
	*,
	next_id: NextId,
	repo_root: str | Path | None = None,
	steps: list[dict[str, Any]] | None = None,
	plan_source: str | None = None,
) -> dict[str, Any]:
	goal_ref = next_id("goal")
	step_payloads = normalize_steps(steps)
	resolved_plan_source = trim_text(plan_source) or (
		"governor" if steps is not None else "orchestration_template"
	)
	goal_title = summarize(goal_text, 96)
	goal_payload = {
		"schema_version": "corgi.goal.v1",
		"goal_ref": goal_ref,
		"title": goal_title,
		"original_goal": trim_text(goal_text),
		"status": "active",
		"created_at": now,
		"updated_at": now,
	}
	plan_payload = {
		"schema_version": "corgi.goal_plan.v1",
		"goal_ref": goal_ref,
		"created_at": now,
		"plan_version": 1,
		"proposed_by": resolved_plan_source,
		"plan_source": resolved_plan_source,
		"revision_history": [],
		"steps": step_payloads,
	}
	if resolved_plan_source == "orchestration_template":
		plan_payload["template_id"] = (
			"pet-life-diary-product-goal-v1"
			if os.environ.get("ORCHESTRATION_TEST_PROMPT_PRESET") == "pet-life-diary-product-goal"
			else "pet-life-diary-goal-program-v1"
		)
	progress_payload = {
		"schema_version": "corgi.goal_progress.v1",
		"goal_ref": goal_ref,
		"status": "active",
		"current_step_ref": step_payloads[0]["step_ref"] if step_payloads else None,
		"current_step_index": 1 if step_payloads else None,
		"completed_steps": [],
		"linked_work_refs": [],
		"blocked_reason": None,
		"final_goal_decision_ref": None,
		"created_at": now,
		"updated_at": now,
	}
	_write_goal(goal_ref, goal_payload, repo_root=repo_root)
	_write_goal_plan(goal_ref, plan_payload, repo_root=repo_root)
	_write_goal_progress(goal_ref, progress_payload, repo_root=repo_root, plan=plan_payload)
	session.setdefault("meta", {})["activeGoalRef"] = goal_ref
	apply_goal_snapshot(
		session,
		goal_ref=goal_ref,
		goal_title=goal_title,
		step=step_payloads[0] if step_payloads else None,
		step_count=len(step_payloads),
		status="active",
	)
	return {
		"goal_ref": goal_ref,
		"goal_title": goal_title,
		"steps": step_payloads,
	}


def revise_goal_program(
	session: dict[str, Any],
	goal_ref: str,
	replacement_steps: list[dict[str, Any]],
	now: str,
	*,
	reason: str,
	next_id: NextId,
	artifact_factory: ArtifactFactory,
	feed_item: FeedItemFactory,
	repo_root: str | Path | None = None,
) -> dict[str, Any]:
	model = session["model"]
	goal_payload = load_goal(goal_ref, repo_root=repo_root)
	progress = load_goal_progress(goal_ref, repo_root=repo_root)
	plan = load_goal_plan(goal_ref, repo_root=repo_root)
	previous_goal_payload = deepcopy(goal_payload)
	previous_progress = deepcopy(progress)
	previous_plan = deepcopy(plan)
	if goal_payload.get("status") != "active" or progress.get("status") != "active":
		raise GoalPlanValidationError("Only an active goal can be revised.")
	completed_step_refs = [
		step.get("step_ref")
		for step in progress.get("completed_steps", [])
		if isinstance(step, dict) and isinstance(step.get("step_ref"), str)
	]
	old_steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
	preserved_steps = [
		step for step in old_steps if step.get("step_ref") in completed_step_refs
	]
	if len(preserved_steps) != len(completed_step_refs):
		raise GoalPlanValidationError("Completed goal steps could not be preserved.")
	start_index = len(preserved_steps) + 1
	new_steps = _normalize_steps_from_index(replacement_steps, start_index=start_index)
	if not new_steps:
		raise GoalPlanValidationError("Goal revision must include at least one unfinished step.")
	previous_version = int(plan.get("plan_version") or 1)
	next_version = previous_version + 1
	history = [entry for entry in plan.get("revision_history", []) if isinstance(entry, dict)]
	history.append(
		{
			"from_plan_version": previous_version,
			"to_plan_version": next_version,
			"reason": trim_text(reason) or "goal_plan_revision",
			"revised_at": now,
			"preserved_step_refs": completed_step_refs,
			"replaced_step_refs": [
				step.get("step_ref")
				for step in old_steps
				if isinstance(step.get("step_ref"), str) and step.get("step_ref") not in completed_step_refs
			],
			"replaced_step_titles": [
				trim_text(step.get("title"))
				for step in old_steps
				if isinstance(step.get("step_ref"), str)
				and step.get("step_ref") not in completed_step_refs
				and trim_text(step.get("title"))
			],
			"replaced_from_step_index": start_index,
		}
	)
	plan["plan_version"] = next_version
	plan["last_revised_at"] = now
	plan["last_revision_reason"] = trim_text(reason) or "goal_plan_revision"
	plan["last_revised_by"] = "governor"
	plan["revision_history"] = history
	plan["steps"] = preserved_steps + new_steps
	_write_goal_plan(goal_ref, plan, repo_root=repo_root)
	try:
		begin_goal_step(
			session,
			goal_ref,
			new_steps[0],
			now,
			next_id=next_id,
			artifact_factory=artifact_factory,
			feed_item=feed_item,
			repo_root=repo_root,
		)
	except Exception as exc:
		_write_goal_plan(goal_ref, previous_plan, repo_root=repo_root)
		save_goal_progress(goal_ref, previous_progress, repo_root=repo_root)
		_write_goal(goal_ref, previous_goal_payload, repo_root=repo_root)
		raise GoalPlanValidationError("Could not activate the revised goal step.") from exc
	progress["current_step_ref"] = new_steps[0]["step_ref"]
	progress["current_step_index"] = new_steps[0]["step_index"]
	progress["status"] = "active"
	progress["blocked_reason"] = None
	progress["updated_at"] = now
	progress["goal_plan_version"] = next_version
	save_goal_progress(goal_ref, progress, repo_root=repo_root)
	goal_payload["updated_at"] = now
	_write_goal(goal_ref, goal_payload, repo_root=repo_root)
	plan = load_goal_plan(goal_ref, repo_root=repo_root)
	model["feed"].append(
		feed_item(
			"system_status",
			"Goal plan revised",
			f"Governor revised the unfinished goal path. Corgi will continue with step {new_steps[0]['step_index']} of {len(plan['steps'])}.",
			authoritative=True,
			now=now,
			source_artifact_ref=repo_relative(goal_plan_path(goal_ref, repo_root=repo_root), repo_root),
			presentation_key="goal.plan_revised",
			presentation_args={
				"goalRef": goal_ref,
				"planVersion": next_version,
				"currentStep": new_steps[0]["title"],
				"stepIndex": new_steps[0]["step_index"],
				"stepCount": len(plan["steps"]),
			},
		)
	)
	return {"goal_ref": goal_ref, "plan_version": next_version, "steps": plan["steps"]}


def begin_goal_step(
	session: dict[str, Any],
	goal_ref: str,
	step: dict[str, Any],
	now: str,
	*,
	next_id: NextId,
	artifact_factory: ArtifactFactory,
	feed_item: FeedItemFactory,
	repo_root: str | Path | None = None,
) -> None:
	model = session["model"]
	branch = model["snapshot"].get("branch") or git_branch_name(repo_root)
	lane = model["snapshot"].get("lane") or default_lane(branch)
	step_title = trim_text(step.get("title")) or f"Goal step {step.get('step_index')}"
	step_objective = trim_text(step.get("objective")) or step_title
	step_summary = summarize(step_objective, 96)

	session_work_lifecycle.reset_work_loop_state(session)
	intake_envelope = intake.start_intake(
		step_objective,
		normalized_text=f"{step_objective} Keep this as one bounded goal step.",
		repo_root=repo_root,
	)
	intake_ref = intake_envelope["intake_ref"]
	draft = load_json(intake.request_draft_path(intake_ref, repo_root=repo_root))
	if draft.get("shell_state") == "clarification_needed":
		intake.answer_intake_clarification(
			intake_ref,
			trim_text(step.get("expected_output")) or "Keep the step bounded and preserve the existing app structure.",
			repo_root=repo_root,
		)
	envelope = intake.accept_intake(
		intake_ref,
		lane=lane,
		branch=branch,
		task=step_title,
		repo_root=repo_root,
		goal_ref=goal_ref,
		goal_step_ref=step["step_ref"],
		goal_step_index=int(step["step_index"]),
	)
	session["meta"]["activeIntakeRef"] = intake_ref
	model["acceptedIntakeSummary"] = {
		"title": "Accepted goal step",
		"body": envelope["accepted_summary"],
	}
	model["snapshot"]["lane"] = envelope["lane"]
	model["snapshot"]["branch"] = envelope["branch"]
	model["snapshot"]["task"] = step_title
	model["snapshot"]["pendingPermissionRequest"] = None
	model["snapshot"]["pendingInterrupt"] = None
	model["snapshot"]["permissionScope"] = "plan"
	model["snapshot"]["currentActor"] = "governor"
	model["snapshot"]["currentStage"] = "plan_ready"
	model["snapshot"]["runState"] = "idle"
	model["snapshot"]["currentAttemptNumber"] = 0
	model["snapshot"]["latestReviewRef"] = None
	model["snapshot"]["latestReviewVerdict"] = None
	model["snapshot"]["latestGovernorDecisionRef"] = None
	model["snapshot"]["latestGovernorDecision"] = None
	model["currentAttemptNumber"] = 0
	model["latestReviewRef"] = None
	model["latestReviewVerdict"] = None
	model["latestGovernorDecisionRef"] = None
	model["latestGovernorDecision"] = None
	model["snapshot"]["recentArtifacts"] = [
		artifact_factory(envelope["accepted_intake_ref"], summary="Accepted intake for the current goal step.", authoritative=True, status="accepted"),
		artifact_factory(repo_relative(goal_plan_path(goal_ref, repo_root=repo_root), repo_root), summary="Authoritative goal step plan.", authoritative=True, status="active"),
		artifact_factory(repo_relative(goal_progress_path(goal_ref, repo_root=repo_root), repo_root), summary="Orchestration-owned goal progress.", authoritative=True, status="active"),
	]
	apply_goal_snapshot(
		session,
		goal_ref=goal_ref,
		goal_title=model.get("currentGoalTitle") or step_title,
		step=step,
		step_count=len(load_goal_plan(goal_ref, repo_root=repo_root).get("steps", [])),
		status="active",
		latest_decision_ref=model.get("latestGoalDecisionRef"),
	)
	plan_body = "\n\n".join(
		[
			f"Objective: {step_objective}",
			f"Proposed step: {step_title}",
			f"Expected output: {trim_text(step.get('expected_output')) or 'Bounded output is produced.'}",
			"Execution readiness: ready for this step as part of the active goal program.",
		]
	)
	model["planVersion"] = 1
	session_work_lifecycle.write_plan_artifact(
		session,
		now,
		plan_body,
		next_id=next_id,
		artifact_factory=artifact_factory,
		repo_root=repo_root,
	)
	model["planReadyRequest"] = session_work_lifecycle.build_plan_ready_request(
		model,
		now,
		next_id=next_id,
		foreground_request_id=model.get("activeForegroundRequestId"),
	)
	update_goal_plan_step(
		goal_ref,
		step["step_ref"],
		{
			"status": "active",
			"work_ref": model["snapshot"].get("currentWorkRef"),
			"started_at": now,
		},
		repo_root=repo_root,
	)
	model["feed"].append(
		feed_item(
			"system_status",
			"Goal step ready",
			f"{step_summary} This is step {step['step_index']} of the active goal.",
			authoritative=True,
			now=now,
			source_artifact_ref=repo_relative(goal_progress_path(goal_ref, repo_root=repo_root), repo_root),
			presentation_key="goal.step_ready",
			presentation_args={
				"step": step_title,
				"stepIndex": step["step_index"],
				"stepCount": len(load_goal_plan(goal_ref, repo_root=repo_root).get("steps", [])),
			},
		)
	)


def current_goal_step(
	goal_ref: str,
	*,
	repo_root: str | Path | None = None,
) -> dict[str, Any] | None:
	progress = load_goal_progress(goal_ref, repo_root=repo_root)
	step_ref = progress.get("current_step_ref")
	plan = load_goal_plan(goal_ref, repo_root=repo_root)
	for step in plan.get("steps", []):
		if isinstance(step, dict) and step.get("step_ref") == step_ref:
			return step
	return None


def advance_goal_after_decision(
	session: dict[str, Any],
	now: str,
	*,
	next_id: NextId,
	artifact_factory: ArtifactFactory,
	feed_item: FeedItemFactory,
	repo_root: str | Path | None = None,
) -> str:
	model = session["model"]
	goal_ref = model.get("currentGoalRef") or session.get("meta", {}).get("activeGoalRef")
	if not isinstance(goal_ref, str) or not goal_ref.strip():
		return "no_goal"
	if model["snapshot"].get("goalStatus") == "completed":
		return "completed"
	if model["snapshot"].get("goalStatus") == "blocked":
		return "blocked"
	if model["snapshot"].get("currentStage") != "governor_decision_recorded":
		if goal_stage_is_blocked(model["snapshot"].get("currentStage")):
			mark_goal_blocked(session, goal_ref, now, "current_step_blocked", repo_root=repo_root)
			return "blocked"
		return "not_terminal"
	decision = trim_text(model["snapshot"].get("latestGovernorDecision"))
	if decision != "accept":
		return "not_accepted"
	decision_ref = model["snapshot"].get("latestGovernorDecisionRef")
	dispatch_ref = dispatch_ref_from_decision_ref(repo_root, decision_ref)
	if not dispatch_ref:
		mark_goal_blocked(session, goal_ref, now, "missing_accepted_dispatch_ref", repo_root=repo_root)
		return "blocked"
	dispatch_blockers = accepted_dispatch_blockers(repo_root, dispatch_ref)
	if dispatch_blockers:
		mark_goal_blocked(session, goal_ref, now, "accepted_dispatch_invalid", repo_root=repo_root)
		model["feed"].append(
			feed_item(
				"system_status",
				"Goal stalled",
				"Corgi could not advance the goal because the completed step did not pass accepted-dispatch validation.",
				authoritative=True,
				now=now,
				source_artifact_ref=decision_ref if isinstance(decision_ref, str) else None,
				presentation_key="goal.stalled",
				presentation_args={
					"reason": "accepted_dispatch_invalid",
				},
				activity={
					"kind": "status",
					"state": "blocked",
					"summary": "Goal stalled during accepted-dispatch validation.",
				},
			)
		)
		return "blocked"
	progress = load_goal_progress(goal_ref, repo_root=repo_root)
	plan = load_goal_plan(goal_ref, repo_root=repo_root)
	steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
	current_ref = progress.get("current_step_ref")
	current_step = next((step for step in steps if step.get("step_ref") == current_ref), None)
	if not current_step:
		mark_goal_blocked(session, goal_ref, now, "missing_current_step", repo_root=repo_root)
		return "blocked"
	completed_steps = [
		step for step in progress.get("completed_steps", []) if isinstance(step, dict)
	]
	if not any(step.get("step_ref") == current_ref for step in completed_steps):
		completed_steps.append(
			{
				"step_ref": current_ref,
				"step_index": current_step.get("step_index"),
				"title": current_step.get("title"),
				"work_ref": model["snapshot"].get("currentWorkRef"),
				"governor_decision_ref": model["snapshot"].get("latestGovernorDecisionRef"),
				"completed_at": now,
			}
		)
	update_goal_plan_step(
		goal_ref,
		current_ref,
		{
			"status": "completed",
			"work_ref": model["snapshot"].get("currentWorkRef"),
			"governor_decision_ref": model["snapshot"].get("latestGovernorDecisionRef"),
			"completed_at": now,
		},
		repo_root=repo_root,
	)
	linked_work_refs = [
		ref
		for ref in progress.get("linked_work_refs", [])
		if isinstance(ref, str) and ref.strip()
	]
	work_ref = model["snapshot"].get("currentWorkRef")
	if isinstance(work_ref, str) and work_ref.strip() and work_ref not in linked_work_refs:
		linked_work_refs.append(work_ref)
	current_index = int(current_step.get("step_index") or 0)
	next_step = next((step for step in steps if int(step.get("step_index") or 0) == current_index + 1), None)
	progress["completed_steps"] = completed_steps
	progress["linked_work_refs"] = linked_work_refs
	progress["updated_at"] = now
	if next_step:
		progress["current_step_ref"] = next_step["step_ref"]
		progress["current_step_index"] = next_step["step_index"]
		progress["status"] = "active"
		save_goal_progress(goal_ref, progress, repo_root=repo_root)
		begin_goal_step(
			session,
			goal_ref,
			next_step,
			now,
			next_id=next_id,
			artifact_factory=artifact_factory,
			feed_item=feed_item,
			repo_root=repo_root,
		)
		return "next_step"
	progress["status"] = "completed"
	progress["current_step_ref"] = None
	progress["current_step_index"] = None
	decision_ref = write_goal_decision(session, goal_ref, now, progress, repo_root=repo_root)
	progress["final_goal_decision_ref"] = decision_ref
	save_goal_progress(goal_ref, progress, repo_root=repo_root)
	goal_payload = load_json(goal_json_path(goal_ref, repo_root=repo_root))
	goal_payload["status"] = "completed"
	goal_payload["updated_at"] = now
	_write_goal(goal_ref, goal_payload, repo_root=repo_root)
	apply_goal_snapshot(
		session,
		goal_ref=goal_ref,
		goal_title=goal_payload.get("title"),
		step=None,
		step_count=len(steps),
		status="completed",
		latest_decision_ref=decision_ref,
	)
	model["feed"].append(
		feed_item(
			"system_status",
			"Goal completed",
			f"Corgi completed {len(completed_steps)} goal steps and recorded the final goal decision.",
			authoritative=True,
			now=now,
			source_artifact_ref=decision_ref,
			presentation_key="goal.final_decision",
			presentation_args={
				"completedSteps": len(completed_steps),
				"decision": "accept",
			},
		)
	)
	return "completed"


def goal_stage_is_blocked(stage: Any) -> bool:
	return stage in {
		"blocked",
		"executor_blocked",
		"reviewer_blocked",
		"finalization_blocked",
		"governor_finalization_blocked",
		"revision_limit_reached",
	}


def mark_goal_blocked(
	session: dict[str, Any],
	goal_ref: str,
	now: str,
	reason: str,
	*,
	repo_root: str | Path | None = None,
) -> None:
	progress = load_goal_progress(goal_ref, repo_root=repo_root)
	progress["status"] = "blocked"
	progress["blocked_reason"] = reason
	progress["updated_at"] = now
	save_goal_progress(goal_ref, progress, repo_root=repo_root)
	step = current_goal_step(goal_ref, repo_root=repo_root)
	if step:
		update_goal_plan_step(
			goal_ref,
			step["step_ref"],
			{"status": "blocked", "blocked_reason": reason, "updated_at": now},
			repo_root=repo_root,
		)
	goal_payload = load_json(goal_json_path(goal_ref, repo_root=repo_root))
	goal_payload["status"] = "blocked"
	goal_payload["updated_at"] = now
	_write_goal(goal_ref, goal_payload, repo_root=repo_root)
	apply_goal_snapshot(
		session,
		goal_ref=goal_ref,
		goal_title=goal_payload.get("title"),
		step=step,
		step_count=len(load_goal_plan(goal_ref, repo_root=repo_root).get("steps", [])),
		status="blocked",
		latest_decision_ref=progress.get("final_goal_decision_ref"),
	)


def write_goal_decision(
	session: dict[str, Any],
	goal_ref: str,
	now: str,
	progress: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> str:
	goal_payload = load_json(goal_json_path(goal_ref, repo_root=repo_root))
	decision_payload = {
		"schema_version": "corgi.goal_decision.v1",
		"goal_ref": goal_ref,
		"decision": "accept",
		"reason": "All planned goal steps reached accepted Governor decisions.",
		"completed_steps": progress.get("completed_steps", []),
		"linked_work_refs": progress.get("linked_work_refs", []),
		"recorded_at": now,
	}
	path = goal_decision_path(goal_ref, repo_root=repo_root)
	_write_goal_decision(goal_ref, decision_payload, repo_root=repo_root)
	return repo_relative(path, repo_root)
