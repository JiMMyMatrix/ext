from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

from orchestration.harness.transition import (
    ALLOWED_CONTINUE_ACTIONS,
    ALLOWED_HUMAN_STOP_REASONS,
    TRANSITION_TYPES,
)
from orchestration.harness.spawn_bridge import (
    BRIDGE_STAGES,
    HELPER_RUNTIME_PATH,
    LIVE_SUBAGENT_MODES,
    LIVE_SUBAGENT_PATH,
)
from orchestration.harness.reviewer import ReviewerContractViolation, resolve_review_artifact_path
from orchestration.scripts.overlap_worktree import INTEGRATION_POLICIES, OVERLAP_ISOLATION_MODE


REQUEST_REQUIRED = [
    "dispatch_ref",
    "from_role",
    "to_role",
    "objective",
    "scope",
    "non_goals",
    "inputs",
    "required_outputs",
    "acceptance_criteria",
    "required_validators",
    "stop_conditions",
    "report_format",
]

RESULT_REQUIRED = [
    "dispatch_ref",
    "status",
    "executor_run_refs",
    "written_or_updated",
    "auto_validated",
    "blocker",
    "recommended_next_bounded_task",
    "runtime_behavior_changed",
    "scope_respected",
]

DECISION_REQUIRED = [
    "dispatch_ref",
    "result_ref",
    "decision",
    "reason",
    "recommended_next_action",
]

ESCALATION_REQUIRED = [
    "dispatch_ref",
    "from_role",
    "to_role",
    "escalation_type",
    "reason",
    "artifacts_consulted",
    "recommended_human_decision",
    "forbidden_until_decided",
]

STATE_REQUIRED = [
    "dispatch_ref",
    "status",
    "claimed_by",
    "claimed_at",
    "run_ref",
    "result_ref",
    "last_transition_at",
    "transition_history",
    "notes",
]

RESULT_STATUS = {"completed", "partial", "blocked", "failed"}
STATE_STATUS = {"queued", "claimed", "running", "validated", "completed", "escalated"}
ESCALATION_TYPES = {
    "blocker",
    "milestone_boundary",
    "authority_boundary",
    "loop_budget_exhausted",
    "conflicting_policy",
    "safety_boundary",
    "missing_required_input",
}
EXECUTION_MODES = {
    "manual_artifact_report",
    "command_chain",
    "report_only_demo",
    "sample_correctness_chain",
    "sample_acceptance",
    "aggregate_report_refresh",
    "guided_agent",
    "strict_refactor",
}
SUPPORTED_SAMPLE_ACCEPTANCE_IDS = {"sample3", "sample6"}
TASK_TRACK_VALUES = {"diagnosis", "patch"}
ESTIMATED_COMPLEXITIES = {"low", "medium", "high"}
REVIEW_VERDICTS = {"pass", "request_changes", "inconclusive"}
DECISION_VALUES = {"accept", "reject", "needs_review", "needs_verification"}
SPAWN_BRIDGE_REQUIRED = [
    "dispatch_ref",
    "execution_mode",
    "resolved_path",
    "bridge_stage",
    "last_action",
    "spawn_records",
]
PROPOSED_TRANSITION_REQUIRED = [
    "lane",
    "source",
    "created_at",
    "transition",
    "requested_stop_reason",
    "dispatch_ref",
    "decision_ref",
    "evidence_refs",
    "next_action",
    "blocker",
    "completion_rule",
]

ALLOWED_TRANSITIONS = {
    None: {"queued"},
    "queued": {"claimed", "escalated"},
    "claimed": {"running", "escalated"},
    "running": {"validated", "escalated"},
    "validated": {"completed", "escalated"},
    "completed": set(),
    "escalated": set(),
}


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def missing_fields(payload: Dict, required: List[str]) -> List[str]:
    return [field for field in required if field not in payload]


def require_list(payload: Dict, field: str, failures: List[str]) -> None:
    value = payload.get(field)
    if value is not None and not isinstance(value, list):
        failures.append(f"{field} must be a list")


def require_string_list(payload: Dict, field: str, failures: List[str], *, prefix: str = "") -> None:
    value = payload.get(field)
    if value is None:
        return
    if not isinstance(value, list):
        failures.append(f"{prefix}{field} must be a list of non-empty strings")
        return
    if any(not isinstance(item, str) or not item.strip() for item in value):
        failures.append(f"{prefix}{field} must be a list of non-empty strings")


def require_string(payload: Dict, field: str, failures: List[str], *, prefix: str = "") -> None:
    value = payload.get(field)
    if value is None or not isinstance(value, str) or not value.strip():
        failures.append(f"{prefix}{field} must be a non-empty string")


def is_five_part_ref(value: str) -> bool:
    parts = value.split("/")
    return len(parts) == 5 and all(part.strip() for part in parts)


def validate_executor_run(payload: Dict, failures: List[str]) -> None:
    if not isinstance(payload, dict):
        failures.append("executor_run must be an object")
        return
    for field in [
        "run_ref",
        "objective",
        "scope",
        "read_list",
        "produce_list",
        "planned_file_touch_list",
        "non_goals",
        "stop_conditions",
    ]:
        if field not in payload:
            failures.append(f"executor_run missing field: {field}")
    for field in [
        "read_list",
        "produce_list",
        "planned_file_touch_list",
        "non_goals",
        "stop_conditions",
    ]:
        require_list(payload, field, failures)
    run_ref = payload.get("run_ref")
    if isinstance(run_ref, str) and run_ref.strip() and not is_five_part_ref(run_ref):
        failures.append(
            "executor_run.run_ref must be five slash-separated non-empty segments: "
            "<cycle>/<scope_type>/<scope_ref>/<artifact_kind>/<attempt>"
        )


def validate_advisor_context(payload: Dict, failures: List[str]) -> None:
    if not isinstance(payload, dict):
        failures.append("advisor_context must be an object")
        return
    consultations = payload.get("consultations", [])
    artifact_refs = payload.get("artifact_refs", [])
    if not isinstance(consultations, list):
        failures.append("advisor_context.consultations must be a list")
    if not isinstance(artifact_refs, list):
        failures.append("advisor_context.artifact_refs must be a list")


def validate_human_escalation_policy(payload: Dict, failures: List[str]) -> None:
    if not isinstance(payload, dict):
        failures.append("human_escalation_policy must be an object")
        return
    if "advisor_first_required" in payload and not isinstance(payload["advisor_first_required"], bool):
        failures.append("human_escalation_policy.advisor_first_required must be a boolean")
    if "allowed_without_advisors" in payload and not isinstance(
        payload["allowed_without_advisors"], list
    ):
        failures.append("human_escalation_policy.allowed_without_advisors must be a list")


def validate_escalation_context(payload: Dict, failures: List[str]) -> None:
    if not isinstance(payload, dict):
        failures.append("escalation_context must be an object")
        return
    prior_attempts = payload.get("prior_attempts")
    if not isinstance(prior_attempts, list):
        failures.append("escalation_context.prior_attempts must be a list")
    if "original_dispatch_ref" in payload:
        require_string(payload, "original_dispatch_ref", failures, prefix="escalation_context.")
    if "cumulative_failure_summary" in payload:
        require_string(payload, "cumulative_failure_summary", failures, prefix="escalation_context.")


def validate_batch_context(payload: Dict, failures: List[str]) -> None:
    if not isinstance(payload, dict):
        failures.append("batch_context must be an object")
        return
    require_string(payload, "parent_dispatch_ref", failures, prefix="batch_context.")
    require_string(payload, "batch_id", failures, prefix="batch_context.")
    if "batch_total" not in payload or not isinstance(payload.get("batch_total"), int):
        failures.append("batch_context.batch_total must be an integer")
    require_string(payload, "batch_scope", failures, prefix="batch_context.")
    require_string(payload, "required_checkpoint_artifact", failures, prefix="batch_context.")
    if "prior_batch_checkpoints" in payload and not isinstance(
        payload["prior_batch_checkpoints"], list
    ):
        failures.append("batch_context.prior_batch_checkpoints must be a list")


def validate_execution_plan(payload: Dict, failures: List[str]) -> None:
    if not isinstance(payload, dict):
        failures.append("execution_plan must be an object")
        return
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        failures.append("execution_plan.steps must be a non-empty list")
    if "total_estimated_minutes" not in payload or not isinstance(
        payload.get("total_estimated_minutes"), int
    ):
        failures.append("execution_plan.total_estimated_minutes must be an integer")
    if "checkpoint_after_step" not in payload or not isinstance(
        payload.get("checkpoint_after_step"), int
    ):
        failures.append("execution_plan.checkpoint_after_step must be an integer")


def validate_retry_handoff(payload: Dict, failures: List[str]) -> None:
    if not isinstance(payload, dict):
        failures.append("retry_handoff must be an object")
        return
    for field in [
        "failing_validator",
        "failing_artifact_path",
        "failing_key_path",
        "source_schema_ref",
        "expected_artifact_ref",
        "expected_value_summary",
        "observed_value_summary",
    ]:
        require_string(payload, field, failures, prefix="retry_handoff.")


def validate_review_fields(payload: Dict, failures: List[str]) -> None:
    review_required = payload.get("review_required")
    if review_required is not None and not isinstance(review_required, bool):
        failures.append("request.json review_required must be a boolean")
    if "review_focus" in payload:
        require_string_list(payload, "review_focus", failures, prefix="request.json ")
    review_artifact_path = payload.get("review_artifact_path")
    if review_artifact_path is not None and (
        not isinstance(review_artifact_path, str) or not review_artifact_path.strip()
    ):
        failures.append("request.json review_artifact_path must be a non-empty string")
    if isinstance(review_artifact_path, str) and review_artifact_path.strip():
        try:
            resolve_review_artifact_path(
                Path("."), payload.get("dispatch_ref", "cycle/unknown/task/a01"), review_artifact_path
            )
        except ReviewerContractViolation as exc:
            failures.append(str(exc))
    if review_required is True and not review_artifact_path:
        failures.append("request.json review_artifact_path is required when review_required is true")


def validate_overlap_isolation_request(payload: Dict, failures: List[str]) -> None:
    overlap = payload.get("overlap_isolation")
    if overlap is None:
        return
    if not isinstance(overlap, dict):
        failures.append("request.json overlap_isolation must be an object")
        return

    mode = overlap.get("mode")
    overlap_group = overlap.get("overlap_group")
    integration_policy = overlap.get("integration_policy")
    if mode != OVERLAP_ISOLATION_MODE:
        failures.append("request.json overlap_isolation.mode must be git_worktree")
    if not isinstance(overlap_group, str) or not overlap_group.strip():
        failures.append("request.json overlap_isolation.overlap_group must be a non-empty string")
    if integration_policy not in INTEGRATION_POLICIES:
        failures.append(
            "request.json overlap_isolation.integration_policy must be choose_one or can_stack"
        )
    if payload.get("execution_mode") not in LIVE_SUBAGENT_MODES:
        failures.append(
            "request.json overlap_isolation is supported only for live-subagent execution modes"
        )
    if payload.get("task_track") != "patch":
        failures.append("request.json overlap_isolation is supported only for patch tasks")
    scope_reservations = payload.get("scope_reservations")
    if not isinstance(scope_reservations, list) or not scope_reservations:
        failures.append("request.json overlap_isolation requires non-empty scope_reservations")


def validate_execution_payload(request: Dict, failures: List[str]) -> None:
    payload = request.get("execution_payload")
    if payload is None:
        return
    if not isinstance(payload, dict):
        failures.append("execution_payload must be an object")
        return
    execution_mode = request.get("execution_mode")
    if execution_mode == "command_chain" and not isinstance(payload.get("commands"), list):
        failures.append("command_chain dispatch requires execution_payload.commands list")
    if execution_mode == "manual_artifact_report" and not payload.get("summary"):
        failures.append("manual_artifact_report dispatch requires execution_payload.summary")
    if execution_mode == "sample_acceptance":
        require_string(payload, "sample_id", failures, prefix="sample_acceptance execution_payload.")
        sample_id = payload.get("sample_id")
        if isinstance(sample_id, str) and sample_id not in SUPPORTED_SAMPLE_ACCEPTANCE_IDS:
            supported = ", ".join(sorted(SUPPORTED_SAMPLE_ACCEPTANCE_IDS))
            failures.append(
                "sample_acceptance execution_payload.sample_id must be one of: " f"{supported}"
            )
    if execution_mode == "guided_agent":
        if not isinstance(payload.get("plan_steps"), list) or not payload["plan_steps"]:
            failures.append("guided_agent dispatch requires execution_payload.plan_steps list")
        if not isinstance(payload.get("declared_files"), list) or not payload["declared_files"]:
            failures.append("guided_agent dispatch requires execution_payload.declared_files list")
        validation = payload.get("validation")
        if not isinstance(validation, dict) or not validation:
            failures.append("guided_agent dispatch requires execution_payload.validation object")
        steps = payload.get("plan_steps", [])
        if isinstance(steps, list):
            for idx, step in enumerate(steps):
                prefix = f"guided_agent plan_steps[{idx}]."
                if not isinstance(step, dict):
                    failures.append(f"{prefix[:-1]} must be an object")
                    continue
                if not isinstance(step.get("step"), int):
                    failures.append(f"{prefix}step must be an integer")
                action = step.get("action")
                if action not in {"read", "edit"}:
                    failures.append(f"{prefix}action must be read or edit")
                require_string(step, "target", failures, prefix=prefix)
                if action == "read":
                    require_string(step, "purpose", failures, prefix=prefix)
                elif action == "edit":
                    require_string(step, "instruction", failures, prefix=prefix)
                    constraints = step.get("constraints")
                    if not isinstance(constraints, list) or not constraints:
                        failures.append(f"{prefix}constraints must be a non-empty list")
        if "turn_limit" in payload and not isinstance(payload["turn_limit"], int):
            failures.append("guided_agent execution_payload.turn_limit must be an integer")
        if "diff_limit" in payload and not isinstance(payload["diff_limit"], int):
            failures.append("guided_agent execution_payload.diff_limit must be an integer")
        require_string_list(
            payload,
            "injected_weakness_guards",
            failures,
            prefix="guided_agent execution_payload.",
        )
    if execution_mode == "strict_refactor":
        require_string(payload, "refactor_type", failures, prefix="strict_refactor execution_payload.")
        require_string(payload, "instruction", failures, prefix="strict_refactor execution_payload.")
        if not isinstance(payload.get("target_files"), list) or not payload["target_files"]:
            failures.append("strict_refactor dispatch requires execution_payload.target_files list")
        require_string(payload, "baseline_command", failures, prefix="strict_refactor execution_payload.")
        require_string(payload, "post_command", failures, prefix="strict_refactor execution_payload.")
        if "turn_limit" in payload and not isinstance(payload["turn_limit"], int):
            failures.append("strict_refactor execution_payload.turn_limit must be an integer")
        if "diff_limit" in payload and not isinstance(payload["diff_limit"], int):
            failures.append("strict_refactor execution_payload.diff_limit must be an integer")
        require_string_list(
            payload,
            "injected_weakness_guards",
            failures,
            prefix="strict_refactor execution_payload.",
        )
    if "validator_commands" in payload and not isinstance(payload["validator_commands"], list):
        failures.append("execution_payload.validator_commands must be a list")


def validate_request(payload: Dict, failures: List[str]) -> None:
    for field in missing_fields(payload, REQUEST_REQUIRED):
        failures.append(f"request.json missing field: {field}")
    if payload.get("from_role") != "agentA":
        failures.append("request.json from_role must be agentA")
    if payload.get("to_role") != "agentB":
        failures.append("request.json to_role must be agentB")
    for field in [
        "scope",
        "non_goals",
        "inputs",
        "required_outputs",
        "acceptance_criteria",
        "required_validators",
        "stop_conditions",
        "report_format",
    ]:
        require_list(payload, field, failures)
    execution_mode = payload.get("execution_mode")
    if execution_mode is not None and execution_mode not in EXECUTION_MODES:
        failures.append("request.json execution_mode is invalid")
    task_track = payload.get("task_track")
    if task_track is not None and task_track not in TASK_TRACK_VALUES:
        failures.append("request.json task_track must be diagnosis or patch")
    estimated_complexity = payload.get("estimated_complexity")
    if estimated_complexity is not None and estimated_complexity not in ESTIMATED_COMPLEXITIES:
        failures.append("request.json estimated_complexity must be low, medium, or high")
    if "attempt_number" in payload:
        attempt_number = payload.get("attempt_number")
        if not isinstance(attempt_number, int) or attempt_number < 1 or attempt_number > 3:
            failures.append("request.json attempt_number must be an integer between 1 and 3")
    if "escalated" in payload and not isinstance(payload["escalated"], bool):
        failures.append("request.json escalated must be a boolean")
    if "executor_run" in payload:
        validate_executor_run(payload["executor_run"], failures)
    if "advisor_context" in payload:
        validate_advisor_context(payload["advisor_context"], failures)
    if "human_escalation_policy" in payload:
        validate_human_escalation_policy(payload["human_escalation_policy"], failures)
    if "escalation_context" in payload:
        validate_escalation_context(payload["escalation_context"], failures)
    if "batch_context" in payload:
        validate_batch_context(payload["batch_context"], failures)
    if "execution_plan" in payload:
        validate_execution_plan(payload["execution_plan"], failures)
    if "retry_handoff" in payload:
        validate_retry_handoff(payload["retry_handoff"], failures)
    require_string_list(payload, "depends_on_dispatches", failures, prefix="request.json ")
    require_string_list(payload, "scope_reservations", failures, prefix="request.json ")
    validate_review_fields(payload, failures)
    validate_overlap_isolation_request(payload, failures)
    checkpoint_outputs = [
        item
        for item in payload.get("required_outputs", [])
        if isinstance(item, str) and "checkpoint" in Path(item).name
    ]
    batch_context = payload.get("batch_context")
    if isinstance(batch_context, dict) and batch_context.get("required_checkpoint_artifact"):
        checkpoint_outputs.append(str(batch_context["required_checkpoint_artifact"]))
    if estimated_complexity in {"medium", "high"} and "execution_plan" not in payload:
        failures.append(
            "request.json execution_plan is required when estimated_complexity is medium/high"
        )
    if (estimated_complexity in {"medium", "high"} or isinstance(batch_context, dict)) and not checkpoint_outputs:
        failures.append(
            "request.json must declare a checkpoint artifact for medium/high or batched dispatches"
        )
    validate_execution_payload(payload, failures)


def validate_result(payload: Dict, failures: List[str]) -> None:
    for field in missing_fields(payload, RESULT_REQUIRED):
        failures.append(f"result.json missing field: {field}")
    status = payload.get("status")
    if status is not None and status not in RESULT_STATUS:
        failures.append("result.json status must be one of: completed, partial, blocked, failed")
    for field in ["executor_run_refs", "written_or_updated", "auto_validated", "notes"]:
        require_list(payload, field, failures)
    if "runtime_behavior_changed" in payload and not isinstance(
        payload["runtime_behavior_changed"], bool
    ):
        failures.append("result.json runtime_behavior_changed must be a boolean")
    if "scope_respected" in payload and not isinstance(payload["scope_respected"], bool):
        failures.append("result.json scope_respected must be a boolean")
    if "failure_category" in payload and (
        not isinstance(payload["failure_category"], str) or not payload["failure_category"].strip()
    ):
        failures.append("result.json failure_category must be a non-empty string when present")
    require_string_list(payload, "review_artifact_refs", failures)


def validate_governor_decision(payload: Dict, failures: List[str]) -> None:
    for field in missing_fields(payload, DECISION_REQUIRED):
        failures.append(f"governor_decision.json missing field: {field}")

    decision = payload.get("decision")
    if decision is not None and decision not in DECISION_VALUES:
        failures.append(
            "governor_decision.json decision must be one of: accept, reject, needs_review, needs_verification"
        )

    for field in ["result_ref", "reason", "recommended_next_action"]:
        require_string(payload, field, failures, prefix="governor_decision.json ")

    review_ref = payload.get("review_ref")
    if review_ref is not None and (not isinstance(review_ref, str) or not review_ref.strip()):
        failures.append("governor_decision.json review_ref must be a non-empty string when present")


def validate_spawn_bridge(
    payload: Dict,
    failures: List[str],
    *,
    request: Optional[Dict] = None,
) -> None:
    for field in missing_fields(payload, SPAWN_BRIDGE_REQUIRED):
        failures.append(f"spawn_bridge.json missing field: {field}")

    dispatch_ref = payload.get("dispatch_ref")
    if dispatch_ref is not None and (not isinstance(dispatch_ref, str) or not dispatch_ref.strip()):
        failures.append("spawn_bridge.json dispatch_ref must be a non-empty string")

    execution_mode = payload.get("execution_mode")
    if execution_mode is not None and execution_mode not in EXECUTION_MODES:
        failures.append("spawn_bridge.json execution_mode is invalid")

    resolved_path = payload.get("resolved_path")
    if resolved_path not in {HELPER_RUNTIME_PATH, LIVE_SUBAGENT_PATH}:
        failures.append("spawn_bridge.json resolved_path must be helper_runtime or live_subagent")

    bridge_stage = payload.get("bridge_stage")
    if bridge_stage not in BRIDGE_STAGES:
        failures.append(
            f"spawn_bridge.json bridge_stage must be one of: {', '.join(sorted(BRIDGE_STAGES))}"
        )

    last_action = payload.get("last_action")
    if last_action is None or not isinstance(last_action, str) or not last_action.strip():
        failures.append("spawn_bridge.json last_action must be a non-empty string")

    review_required = payload.get("review_required")
    if review_required is not None and not isinstance(review_required, bool):
        failures.append("spawn_bridge.json review_required must be a boolean when present")

    for field in ["executor_handoff_ref", "reviewer_handoff_ref"]:
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            failures.append(
                f"spawn_bridge.json {field} must be a non-empty string when present"
            )
    overlap_isolation_ref = payload.get("overlap_isolation_ref")
    if overlap_isolation_ref is not None and (
        not isinstance(overlap_isolation_ref, str) or not overlap_isolation_ref.strip()
    ):
        failures.append(
            "spawn_bridge.json overlap_isolation_ref must be a non-empty string when present"
        )

    spawn_records = payload.get("spawn_records")
    if not isinstance(spawn_records, dict):
        failures.append("spawn_bridge.json spawn_records must be an object")
    else:
        for field in ["executor", "reviewer"]:
            if field not in spawn_records:
                failures.append(f"spawn_bridge.json spawn_records missing field: {field}")

    if isinstance(execution_mode, str) and isinstance(resolved_path, str):
        expected_path = (
            LIVE_SUBAGENT_PATH if execution_mode in LIVE_SUBAGENT_MODES else HELPER_RUNTIME_PATH
        )
        if resolved_path != expected_path:
            failures.append("spawn_bridge.json resolved_path does not match execution_mode")

    if request is not None:
        if dispatch_ref != request.get("dispatch_ref"):
            failures.append("dispatch_ref mismatch between request.json and spawn_bridge.json")
        if execution_mode != (request.get("execution_mode") or "manual_artifact_report"):
            failures.append("execution_mode mismatch between request.json and spawn_bridge.json")


def validate_overlap_isolation_artifact(
    payload: Dict,
    failures: List[str],
    *,
    request: Optional[Dict] = None,
) -> None:
    required = [
        "dispatch_ref",
        "originating_dispatch_ref",
        "lane",
        "lane_branch",
        "lane_repo_root",
        "mode",
        "overlap_group",
        "integration_policy",
        "base_commit_sha",
        "ephemeral_branch",
        "worktree_path",
        "status",
    ]
    for field in missing_fields(payload, required):
        failures.append(f"overlap_isolation.json missing field: {field}")

    for field in [
        "dispatch_ref",
        "originating_dispatch_ref",
        "lane",
        "lane_branch",
        "lane_repo_root",
        "overlap_group",
        "base_commit_sha",
        "ephemeral_branch",
        "worktree_path",
        "status",
    ]:
        require_string(payload, field, failures, prefix="overlap_isolation.json ")

    if payload.get("mode") != OVERLAP_ISOLATION_MODE:
        failures.append("overlap_isolation.json mode must be git_worktree")
    if payload.get("integration_policy") not in INTEGRATION_POLICIES:
        failures.append(
            "overlap_isolation.json integration_policy must be choose_one or can_stack"
        )
    if request is not None:
        if payload.get("dispatch_ref") != request.get("dispatch_ref"):
            failures.append("dispatch_ref mismatch between request.json and overlap_isolation.json")
        if payload.get("originating_dispatch_ref") != request.get("dispatch_ref"):
            failures.append(
                "originating_dispatch_ref mismatch between request.json and overlap_isolation.json"
            )
        if payload.get("lane") != request.get("lane"):
            failures.append("lane mismatch between request.json and overlap_isolation.json")
        request_overlap = request.get("overlap_isolation")
        if not isinstance(request_overlap, dict):
            failures.append(
                "overlap_isolation.json exists but request.json does not declare overlap_isolation"
            )
        else:
            if payload.get("overlap_group") != request_overlap.get("overlap_group"):
                failures.append("overlap_group mismatch between request.json and overlap_isolation.json")
            if payload.get("integration_policy") != request_overlap.get("integration_policy"):
                failures.append(
                    "integration_policy mismatch between request.json and overlap_isolation.json"
                )


def validate_proposed_transition(payload: Dict, failures: List[str]) -> None:
    for field in missing_fields(payload, PROPOSED_TRANSITION_REQUIRED):
        failures.append(f"proposed_transition.json missing field: {field}")

    require_string(payload, "lane", failures, prefix="proposed_transition.json ")
    require_string(payload, "source", failures, prefix="proposed_transition.json ")
    require_string(payload, "created_at", failures, prefix="proposed_transition.json ")
    require_string_list(payload, "evidence_refs", failures, prefix="proposed_transition.json ")

    transition = payload.get("transition")
    if transition not in TRANSITION_TYPES:
        failures.append(
            "proposed_transition.json transition must be one of: "
            + ", ".join(sorted(TRANSITION_TYPES))
        )

    requested_stop_reason = payload.get("requested_stop_reason")
    if requested_stop_reason is not None and requested_stop_reason not in ALLOWED_HUMAN_STOP_REASONS:
        failures.append(
            "proposed_transition.json requested_stop_reason must be null or one of: "
            + ", ".join(sorted(ALLOWED_HUMAN_STOP_REASONS))
        )

    for field in ["dispatch_ref", "decision_ref"]:
        value = payload.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            failures.append(
                f"proposed_transition.json {field} must be a non-empty string when present"
            )

    next_action = payload.get("next_action")
    blocker = payload.get("blocker")
    if transition == "continue_internal":
        if requested_stop_reason is not None:
            failures.append(
                "proposed_transition.json requested_stop_reason must be null for continue_internal"
            )
        if not isinstance(next_action, dict):
            failures.append(
                "proposed_transition.json next_action must be an object for continue_internal"
            )
        else:
            kind = next_action.get("kind")
            if kind not in ALLOWED_CONTINUE_ACTIONS:
                failures.append(
                    "proposed_transition.json next_action.kind must be one of: "
                    + ", ".join(sorted(ALLOWED_CONTINUE_ACTIONS))
                )
            ref = next_action.get("ref")
            if ref is not None and (not isinstance(ref, str) or not ref.strip()):
                failures.append(
                    "proposed_transition.json next_action.ref must be a non-empty string when present"
                )
            summary = next_action.get("summary")
            if summary is not None and not isinstance(summary, str):
                failures.append(
                    "proposed_transition.json next_action.summary must be a string when present"
                )
        if blocker is not None:
            failures.append("proposed_transition.json blocker must be null for continue_internal")
    elif transition == "interrupt_human":
        if next_action is not None:
            failures.append("proposed_transition.json next_action must be null for interrupt_human")
        if requested_stop_reason in {
            "material_blocker",
            "missing_permission",
            "missing_resource",
            "human_decision_required",
            "safety_boundary",
        }:
            if not isinstance(blocker, dict):
                failures.append(
                    "proposed_transition.json blocker must be an object for blocker-style interrupts"
                )
            else:
                category = blocker.get("category")
                summary = blocker.get("summary")
                artifact_refs = blocker.get("artifact_refs")
                forbidden = blocker.get("forbidden_until_resolved")
                if not isinstance(category, str) or not category.strip():
                    failures.append(
                        "proposed_transition.json blocker.category must be a non-empty string"
                    )
                if not isinstance(summary, str) or not summary.strip():
                    failures.append(
                        "proposed_transition.json blocker.summary must be a non-empty string"
                    )
                if not isinstance(artifact_refs, list) or not artifact_refs or any(
                    not isinstance(item, str) or not item.strip() for item in artifact_refs
                ):
                    failures.append(
                        "proposed_transition.json blocker.artifact_refs must be a non-empty list of strings"
                    )
                if forbidden is not None and (
                    not isinstance(forbidden, list)
                    or any(not isinstance(item, str) or not item.strip() for item in forbidden)
                ):
                    failures.append(
                        "proposed_transition.json blocker.forbidden_until_resolved must be a list of non-empty strings when present"
                    )
        elif blocker is not None:
            failures.append("proposed_transition.json blocker must be null for non-blocker interrupts")

    completion_rule = payload.get("completion_rule")
    if not isinstance(completion_rule, dict):
        failures.append("proposed_transition.json completion_rule must be an object")
    else:
        mode = completion_rule.get("completion_mode")
        rules_ref = completion_rule.get("rules_ref")
        if not isinstance(mode, str) or not mode.strip():
            failures.append(
                "proposed_transition.json completion_rule.completion_mode must be a non-empty string"
            )
        if not isinstance(rules_ref, str) or not rules_ref.strip():
            failures.append(
                "proposed_transition.json completion_rule.rules_ref must be a non-empty string"
            )


def validate_escalation(payload: Dict, failures: List[str]) -> None:
    for field in missing_fields(payload, ESCALATION_REQUIRED):
        failures.append(f"escalation.json missing field: {field}")
    if payload.get("from_role") not in {"agentA", "agentB"}:
        failures.append("escalation.json from_role must be agentA or agentB")
    if payload.get("to_role") not in {"human", "agentA"}:
        failures.append("escalation.json to_role must be human or agentA")
    escalation_type = payload.get("escalation_type")
    if escalation_type is not None and escalation_type not in ESCALATION_TYPES:
        failures.append("escalation.json escalation_type is invalid")
    for field in ["artifacts_consulted", "forbidden_until_decided"]:
        require_list(payload, field, failures)
    if "failure_category" in payload and (
        not isinstance(payload["failure_category"], str) or not payload["failure_category"].strip()
    ):
        failures.append("escalation.json failure_category must be a non-empty string when present")


def validate_state(payload: Dict, failures: List[str]) -> None:
    for field in missing_fields(payload, STATE_REQUIRED):
        failures.append(f"state.json missing field: {field}")
    status = payload.get("status")
    if status is not None and status not in STATE_STATUS:
        failures.append(
            "state.json status must be one of: queued, claimed, running, validated, completed, escalated"
        )
    require_list(payload, "notes", failures)
    require_list(payload, "transition_history", failures)

    history = payload.get("transition_history")
    if isinstance(history, list):
        previous = None
        for idx, item in enumerate(history):
            if not isinstance(item, dict):
                failures.append(f"state.json transition_history[{idx}] must be an object")
                continue
            for field in ["from", "to", "at", "actor"]:
                if field not in item:
                    failures.append(
                        f"state.json transition_history[{idx}] missing field: {field}"
                    )
            to_state = item.get("to")
            from_state = item.get("from")
            if to_state not in STATE_STATUS:
                failures.append(f"state.json transition_history[{idx}] has invalid to state")
            allowed = ALLOWED_TRANSITIONS.get(from_state, set())
            if to_state is not None and to_state not in allowed:
                failures.append(
                    f"state.json transition_history[{idx}] has illegal transition {from_state!r} -> {to_state!r}"
                )
            if previous is not None and previous != from_state:
                failures.append(
                    f"state.json transition_history[{idx}] does not chain from previous state"
                )
            previous = to_state
        if history and previous is not None and status is not None and previous != status:
            failures.append("state.json status does not match the last transition_history to-state")

    if status in {"claimed", "running", "validated", "completed"}:
        if not payload.get("claimed_by"):
            failures.append("state.json claimed_by must be set after claim")
        if not payload.get("claimed_at"):
            failures.append("state.json claimed_at must be set after claim")
    if status in {"running", "validated", "completed"} and not payload.get("run_ref"):
        failures.append("state.json run_ref must be set once execution has started")
    run_ref = payload.get("run_ref")
    if isinstance(run_ref, str) and run_ref.strip() and not is_five_part_ref(run_ref):
        failures.append(
            "state.json run_ref must be five slash-separated non-empty segments: "
            "<cycle>/<scope_type>/<scope_ref>/<artifact_kind>/<attempt>"
        )
    if status == "completed" and not payload.get("result_ref"):
        failures.append("state.json result_ref must be set when status is completed")


def run_dir_for_ref(repo_root: Path, run_ref: str) -> Path:
    return repo_root / ".agent" / "runs" / Path(run_ref)


def repo_root_for_path(path: Path) -> Path:
    current = path.resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / ".git").exists():
            return candidate
    return path.resolve().parent


def expected_dispatch_ref_for_dir(dispatch_dir: Path) -> Optional[str]:
    parts = dispatch_dir.parts
    if len(parts) < 5:
        return None
    return "/".join(parts[-5:])


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate governor/executor dispatch artifacts.")
    parser.add_argument("path", help="Dispatch directory or a dispatch JSON file.")
    args = parser.parse_args(argv)

    target = Path(args.path).resolve()
    failures: List[str] = []

    if target.is_dir():
        repo_root = repo_root_for_path(target)
        request_path = target / "request.json"
        state_path = target / "state.json"
        result_path = target / "result.json"
        escalation_path = target / "escalation.json"
        decision_path = target / "governor_decision.json"
        spawn_bridge_path = target / "spawn_bridge.json"
        overlap_isolation_path = target / "overlap_isolation.json"

        if not request_path.exists():
            failures.append("missing file: request.json")
        if not state_path.exists():
            failures.append("missing file: state.json")
        if failures:
            raise SystemExit("\n".join(failures))

        request = load_json(request_path)
        validate_request(request, failures)
        dispatch_ref = request.get("dispatch_ref")
        state = load_json(state_path)
        validate_state(state, failures)
        if dispatch_ref != state.get("dispatch_ref"):
            failures.append("dispatch_ref mismatch between request.json and state.json")

        if result_path.exists():
            result = load_json(result_path)
            validate_result(result, failures)
            if dispatch_ref != result.get("dispatch_ref"):
                failures.append("dispatch_ref mismatch between request.json and result.json")

        if escalation_path.exists():
            escalation = load_json(escalation_path)
            validate_escalation(escalation, failures)
            if dispatch_ref != escalation.get("dispatch_ref"):
                failures.append("dispatch_ref mismatch between request.json and escalation.json")

        if decision_path.exists():
            decision = load_json(decision_path)
            validate_governor_decision(decision, failures)
            if dispatch_ref != decision.get("dispatch_ref"):
                failures.append(
                    "dispatch_ref mismatch between request.json and governor_decision.json"
                )

        if spawn_bridge_path.exists():
            spawn_bridge = load_json(spawn_bridge_path)
            validate_spawn_bridge(spawn_bridge, failures, request=request)

        if overlap_isolation_path.exists():
            overlap_isolation = load_json(overlap_isolation_path)
            validate_overlap_isolation_artifact(overlap_isolation, failures, request=request)

        expected = expected_dispatch_ref_for_dir(target)
        if expected and dispatch_ref and dispatch_ref != expected:
            failures.append("dispatch_ref does not match dispatch directory path")

        status = state.get("status")
        result_ref = state.get("result_ref")
        run_ref = state.get("run_ref")

        if run_ref:
            run_dir = run_dir_for_ref(repo_root, run_ref)
            if not run_dir.is_dir():
                failures.append("state.json run_ref does not point to an existing run directory")

        if status == "completed":
            if not result_path.exists():
                failures.append("completed dispatch must include result.json")
            if result_ref and result_ref != str(result_path.relative_to(repo_root)):
                failures.append("state.json result_ref does not match result.json path")
            if result_path.exists():
                result = load_json(result_path)
                if result.get("status") != "completed":
                    failures.append("completed dispatch must have result.json status = completed")

        if status == "validated" and result_path.exists():
            failures.append("validated dispatch should not already have a terminal result.json")

        if status == "escalated" and not escalation_path.exists():
            failures.append("escalated dispatch must include escalation.json")

        if status in {"queued", "claimed", "running"}:
            if result_path.exists():
                failures.append(f"{status} dispatch should not already include result.json")
            if escalation_path.exists():
                failures.append(f"{status} dispatch should not already include escalation.json")
    else:
        if not target.exists():
            raise SystemExit(f"not found: {target}")
        payload = load_json(target)
        name = target.name
        if name == "request.json" or name.endswith("dispatch_request.template.json"):
            validate_request(payload, failures)
        elif name == "result.json" or name.endswith("dispatch_result.template.json"):
            validate_result(payload, failures)
        elif name == "state.json" or name.endswith("dispatch_state.template.json"):
            validate_state(payload, failures)
        elif name == "escalation.json" or name.endswith("escalation_record.template.json"):
            validate_escalation(payload, failures)
        elif name == "governor_decision.json":
            validate_governor_decision(payload, failures)
        elif name == "spawn_bridge.json":
            validate_spawn_bridge(payload, failures)
        elif name == "proposed_transition.json":
            validate_proposed_transition(payload, failures)
        else:
            failures.append(
                "unsupported file type; use a dispatch dir or request/result/state/escalation/governor_decision/spawn_bridge/proposed_transition JSON"
            )

    if failures:
        raise SystemExit("\n".join(failures))

    print("dispatch contract valid")
    return 0
