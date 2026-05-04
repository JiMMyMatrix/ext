from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from orchestration.harness.paths import repo_relative, resolve_agent_root, script_ref, utc_now, write_json
from orchestration.harness.start_guard import ensure_lane_worktree_tracked
from orchestration.harness.transition import build_transition_payload, liveness_blocker, record_transition
from orchestration.harness.dispatch_guards import artifact_only_executor_readout_request
from orchestration.harness.artifacts import (
    ArtifactContractError,
    load_acceptance_review,
    load_review_artifact,
)
from orchestration.harness.reviewer import (
    ReviewerContractViolation,
    capture_reviewer_guard_snapshot,
    enforce_reviewer_guard,
    resolve_review_artifact_path,
)
from orchestration.harness.runtime_support import ensure_approved_python_binary

DEFAULT_REPORT_FORMAT = [
    "what was written or updated",
    "what was auto-validated",
    "whether any blocker exists",
    "recommended next bounded task",
]

DEFAULT_HUMAN_ESCALATION_POLICY = {
    "advisor_first_required": True,
    "allowed_without_advisors": ["authority_boundary", "safety_boundary", "missing_required_input"],
    "note": "Governor should consult bounded advisors before escalating unresolved lane-direction questions to the human.",
}

ALLOWED_EXECUTION_MODES = {
    "manual_artifact_report",
    "command_chain",
    "report_only_demo",
    "sample_correctness_chain",
    "sample_acceptance",
    "aggregate_report_refresh",
    "guided_agent",
    "strict_refactor",
}
ALLOWED_TASK_TRACKS = {"diagnosis", "patch"}
ALLOWED_ESTIMATED_COMPLEXITIES = {"low", "medium", "high"}
SUBAGENT_ONLY_MODES = {"guided_agent", "strict_refactor"}

DispatchRoute = Callable[[list[str]], int]


def unique(values: List[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in out:
            out.append(stripped)
    return out


def parse_json_file(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    payload_path = Path(path)
    return json.loads(payload_path.read_text(encoding="utf-8"))


def parse_command_specs(values: List[str]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for value in values:
        argv = shlex.split(value)
        if not argv:
            continue
        specs.append({
            "argv": argv,
            "cwd": ".",
            "timeout_sec": None,
            "allow_failure": False,
            "name": argv[0],
        })
    return specs


def parse_advisor_notes(values: List[str]) -> List[Dict[str, str]]:
    notes: List[Dict[str, str]] = []
    for value in values:
        provider, sep, summary = value.partition(":")
        provider = provider.strip()
        summary = summary.strip() if sep else value.strip()
        if provider:
            notes.append({"provider": provider, "summary": summary})
        elif summary:
            notes.append({"provider": "unspecified", "summary": summary})
    return notes


def validate_executor_run_ref_format(run_ref: str) -> None:
    parts = run_ref.split("/")
    if len(parts) != 5 or any(not part.strip() for part in parts):
        raise SystemExit(
            "executor_run_ref must be five slash-separated non-empty segments: "
            "<cycle>/<scope_type>/<scope_ref>/<artifact_kind>/<attempt>"
        )


def dispatch_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return resolve_agent_root(repo_root) / "dispatches" / Path(dispatch_ref)


def build_execution_payload(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.execution_payload_file:
        payload = parse_json_file(args.execution_payload_file)
        if not isinstance(payload, dict):
            raise SystemExit("execution payload file must contain a JSON object")
        if args.injected_weakness_guard:
            payload["injected_weakness_guards"] = unique(args.injected_weakness_guard)
        return payload

    payload: Dict[str, Any] = {}
    if args.command:
        payload["commands"] = parse_command_specs(args.command)
    if args.validator_command:
        payload["validator_commands"] = parse_command_specs(args.validator_command)
    if args.execution_summary:
        payload["summary"] = args.execution_summary
    if args.sample_id:
        payload["sample_id"] = args.sample_id
    if args.execution_claim:
        payload["claims"] = unique(args.execution_claim)
    if args.execution_evidence:
        payload["evidence"] = unique(args.execution_evidence)
    if args.execution_note:
        payload["notes"] = unique(args.execution_note)
    if args.execution_next_action:
        payload["next_action"] = args.execution_next_action
    if args.injected_weakness_guard:
        payload["injected_weakness_guards"] = unique(args.injected_weakness_guard)
    return payload or None


def build_review_fields(args: argparse.Namespace) -> Dict[str, Any]:
    review_requested = bool(args.review_required or args.review_focus or args.review_artifact_path)
    if not review_requested:
        return {}
    if not args.review_artifact_path:
        raise SystemExit("--review-artifact-path is required when reviewer fields are used")
    payload: Dict[str, Any] = {
        "review_required": True,
        "review_artifact_path": args.review_artifact_path,
    }
    if args.review_focus:
        payload["review_focus"] = unique(args.review_focus)
    return payload


def build_coordination_fields(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if args.depends_on_dispatch:
        payload["depends_on_dispatches"] = unique(args.depends_on_dispatch)
    if args.scope_reservation:
        payload["scope_reservations"] = unique(args.scope_reservation)
    overlap_requested = bool(
        args.overlap_group or args.overlap_isolation_mode or args.integration_policy
    )
    if overlap_requested:
        overlap_group = (args.overlap_group or "").strip()
        if not overlap_group:
            raise SystemExit("--overlap-group is required when overlap isolation is configured")
        payload["overlap_isolation"] = {
            "mode": (args.overlap_isolation_mode or "git_worktree").strip(),
            "overlap_group": overlap_group,
            "integration_policy": (args.integration_policy or "choose_one").strip(),
        }
    return payload


def build_emit_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Emit or normalize a governor/executor dispatch.")
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--objective")
    parser.add_argument("--task-kind", default="bounded_task")
    parser.add_argument("--lane", default="executor_weakness_registry_adoption")
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--non-goal", action="append", default=[])
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--required-output", action="append", default=[])
    parser.add_argument("--acceptance-criterion", action="append", default=[])
    parser.add_argument("--required-validator", action="append", default=[])
    parser.add_argument("--stop-condition", action="append", default=[])
    parser.add_argument("--report-format", action="append", default=[])
    parser.add_argument("--whitelist-class")
    parser.add_argument("--loop-iteration", type=int, default=1)
    parser.add_argument("--execution-mode", choices=sorted(ALLOWED_EXECUTION_MODES))
    parser.add_argument("--task-track", choices=sorted(ALLOWED_TASK_TRACKS))
    parser.add_argument("--estimated-complexity", choices=sorted(ALLOWED_ESTIMATED_COMPLEXITIES))
    parser.add_argument("--attempt-number", type=int, default=1)
    parser.add_argument("--work-ref")
    parser.add_argument("--plan-ref")
    parser.add_argument("--plan-version", type=int)
    parser.add_argument("--revision-of-dispatch-ref")
    parser.add_argument("--escalated", action="store_true")
    parser.add_argument("--escalation-context-file")
    parser.add_argument("--batch-context-file")
    parser.add_argument("--execution-plan-file")
    parser.add_argument("--retry-handoff-file")
    parser.add_argument("--execution-payload-file")
    parser.add_argument("--command", action="append", default=[])
    parser.add_argument("--validator-command", action="append", default=[])
    parser.add_argument("--execution-summary")
    parser.add_argument("--sample-id")
    parser.add_argument("--execution-claim", action="append", default=[])
    parser.add_argument("--execution-evidence", action="append", default=[])
    parser.add_argument("--execution-note", action="append", default=[])
    parser.add_argument("--execution-next-action")
    parser.add_argument("--injected-weakness-guard", action="append", default=[])
    parser.add_argument("--consulted-advisor", action="append", default=[])
    parser.add_argument("--advisor-artifact", action="append", default=[])
    parser.add_argument("--allow-human-escalation-without-advisors", action="store_true")
    parser.add_argument("--review-required", action="store_true")
    parser.add_argument("--review-focus", action="append", default=[])
    parser.add_argument("--review-artifact-path")
    parser.add_argument("--depends-on-dispatch", action="append", default=[])
    parser.add_argument("--scope-reservation", action="append", default=[])
    parser.add_argument("--overlap-isolation-mode")
    parser.add_argument("--overlap-group")
    parser.add_argument("--integration-policy")
    parser.add_argument("--executor-run-ref")
    parser.add_argument("--run-objective")
    parser.add_argument("--run-scope")
    parser.add_argument("--run-read", action="append", default=[])
    parser.add_argument("--run-produce", action="append", default=[])
    parser.add_argument("--run-touch", action="append", default=[])
    parser.add_argument("--run-non-goal", action="append", default=[])
    parser.add_argument("--run-stop-condition", action="append", default=[])
    parser.add_argument("--normalize-existing", action="store_true")
    parser.add_argument("--root", default=".")
    return parser


def emit_main(argv: Optional[List[str]] = None) -> int:
    args = build_emit_parser().parse_args(argv)

    repo_root = Path(args.root).resolve()
    dispatch_dir = dispatch_dir_for_ref(repo_root, args.dispatch_ref)
    request_path = dispatch_dir / "request.json"
    state_path = dispatch_dir / "state.json"

    if args.normalize_existing:
        if not request_path.exists():
            raise SystemExit("cannot normalize dispatch state: request.json does not exist")
        request = json.loads(request_path.read_text(encoding="utf-8"))
    else:
        if request_path.exists():
            raise SystemExit(f"dispatch already exists: {dispatch_dir}")
        if not args.objective:
            raise SystemExit("--objective is required unless --normalize-existing is used")

        request = {
            "dispatch_ref": args.dispatch_ref,
            "from_role": "agentA",
            "to_role": "agentB",
            "task_kind": args.task_kind,
            "lane": args.lane,
            "objective": args.objective,
            "scope": unique(args.scope),
            "non_goals": unique(args.non_goal),
            "inputs": unique(args.input),
            "required_outputs": unique(args.required_output),
            "acceptance_criteria": unique(args.acceptance_criterion),
            "required_validators": unique(args.required_validator),
            "stop_conditions": unique(args.stop_condition),
            "report_format": unique(args.report_format) or DEFAULT_REPORT_FORMAT,
            "whitelist_class": args.whitelist_class or "",
            "loop_iteration": args.loop_iteration,
            "created_at": utc_now(),
            "advisor_context": {
                "consultations": parse_advisor_notes(args.consulted_advisor),
                "artifact_refs": unique(args.advisor_artifact),
            },
            "human_escalation_policy": {
                **DEFAULT_HUMAN_ESCALATION_POLICY,
                "advisor_first_required": not args.allow_human_escalation_without_advisors,
            },
            "attempt_number": args.attempt_number,
            "escalated": bool(args.escalated),
        }
        if args.work_ref:
            request["work_ref"] = args.work_ref
        if args.plan_ref:
            request["plan_ref"] = args.plan_ref
        if args.plan_version is not None:
            request["plan_version"] = args.plan_version
        if args.revision_of_dispatch_ref:
            request["revision_of_dispatch_ref"] = args.revision_of_dispatch_ref
        if args.task_track:
            request["task_track"] = args.task_track
        if args.estimated_complexity:
            request["estimated_complexity"] = args.estimated_complexity
        if args.execution_mode:
            request["execution_mode"] = args.execution_mode
        if args.escalation_context_file:
            request["escalation_context"] = parse_json_file(args.escalation_context_file)
            request["escalated"] = True
        if args.batch_context_file:
            request["batch_context"] = parse_json_file(args.batch_context_file)
        if args.execution_plan_file:
            request["execution_plan"] = parse_json_file(args.execution_plan_file)
        if args.retry_handoff_file:
            request["retry_handoff"] = parse_json_file(args.retry_handoff_file)
        request.update(build_review_fields(args))
        request.update(build_coordination_fields(args))
        execution_payload = build_execution_payload(args)
        if execution_payload is not None:
            request["execution_payload"] = execution_payload
        if args.executor_run_ref:
            validate_executor_run_ref_format(args.executor_run_ref)
            request["executor_run"] = {
                "run_ref": args.executor_run_ref,
                "objective": args.run_objective or args.objective,
                "scope": args.run_scope or args.objective,
                "read_list": unique(args.run_read),
                "produce_list": unique(args.run_produce),
                "planned_file_touch_list": unique(args.run_touch),
                "non_goals": unique(args.run_non_goal) or unique(args.non_goal),
                "stop_conditions": unique(args.run_stop_condition) or unique(args.stop_condition),
            }
        write_json(request_path, request)

    now = utc_now()
    state = {
        "dispatch_ref": request["dispatch_ref"],
        "status": "queued",
        "claimed_by": None,
        "claimed_at": None,
        "run_ref": request.get("executor_run", {}).get("run_ref"),
        "result_ref": None,
        "last_transition_at": now,
        "transition_history": [
            {
                "from": None,
                "to": "queued",
                "at": now,
                "actor": "agentA",
                "note": "dispatch initialized",
            }
        ],
        "notes": [],
    }
    write_json(state_path, state)
    print(str(dispatch_dir.relative_to(repo_root)))
    return 0


def load_dispatch_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_root_for_path(path: Path, fallback: Path | None = None) -> Path:
    current = path.resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / ".git").exists():
            return candidate
    return fallback or current.parent


def discover_review_artifact_path(dispatch_dir: Path, request: Dict[str, Any], repo_root: Path) -> Path:
    _ = dispatch_dir
    return resolve_review_artifact_path(repo_root, request["dispatch_ref"], request.get("review_artifact_path"))


def build_helper_review(
    repo_root: Path,
    request: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    findings: List[str] = []
    residual_risks: List[str] = []
    validator_assessment: List[str] = []
    scope_assessment: List[str] = []

    validator_assessment.append(f"executor_result_status={result.get('status')}")
    validator_assessment.extend(
        item for item in result.get("auto_validated", []) if isinstance(item, str) and item.strip()
    )

    if result.get("scope_respected") is True:
        scope_assessment.append("declared file scope appears respected")
    else:
        scope_assessment.append("scope respected flag is false")
        findings.append("executor result reported scope_respected = false")

    verdict = "pass"
    if result.get("status") != "completed":
        verdict = "request_changes"
        findings.append(f"executor result status is {result.get('status')}, not completed")
    if result.get("blocker"):
        verdict = "request_changes"
        findings.append(f"executor blocker present: {result.get('blocker')}")
    if result.get("scope_respected") is False:
        verdict = "request_changes"

    acceptance_review_paths = [
        rel_path
        for rel_path in result.get("written_or_updated", [])
        if isinstance(rel_path, str) and rel_path.endswith("_review.json")
    ]
    accepted_reviews = 0
    for rel_path in acceptance_review_paths:
        try:
            review_payload = load_acceptance_review(repo_root / rel_path)
        except (ArtifactContractError, FileNotFoundError) as exc:
            verdict = "request_changes"
            findings.append(str(exc))
            continue
        status = review_payload.get("status")
        validator_assessment.append(f"acceptance_review_status[{rel_path}]={status}")
        if status == "accepted":
            accepted_reviews += 1
        else:
            verdict = "request_changes"
            findings.append(f"acceptance review {rel_path} is not accepted (status={status})")

    task_track = request.get("task_track")
    runtime_behavior_changed = result.get("runtime_behavior_changed") is True
    if task_track == "patch" and runtime_behavior_changed and accepted_reviews == 0:
        verdict = "inconclusive"
        residual_risks.append(
            "runtime behavior changed but helper-backed review has no accepted acceptance-review artifact to verify semantics"
        )

    review_focus = request.get("review_focus", [])
    if isinstance(review_focus, list) and review_focus:
        residual_risks.append(
            "helper-backed reviewer did not independently reason over all requested review_focus items; governor may prefer the reviewer subagent for semantic review"
        )

    if verdict == "pass":
        recommendation = "accept"
    elif verdict == "request_changes":
        recommendation = "redispatch_or_reject"
    else:
        recommendation = "bounded_verification_or_reviewer_subagent"

    return {
        "dispatch_ref": request["dispatch_ref"],
        "reviewer_role": "agentR-helper",
        "verdict": verdict,
        "validator_assessment": validator_assessment,
        "scope_assessment": scope_assessment,
        "findings": findings,
        "residual_risks": residual_risks,
        "recommendation": recommendation,
    }


def build_reviewer_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consume or generate reviewer output for a completed dispatch.")
    parser.add_argument("--dispatch-dir", required=True)
    parser.add_argument("--review-json-file")
    return parser


def reviewer_main(argv: Optional[List[str]] = None) -> int:
    args = build_reviewer_parser().parse_args(argv)

    dispatch_dir = Path(args.dispatch_dir).resolve()
    repo_root = repo_root_for_path(dispatch_dir)
    request_path = dispatch_dir / "request.json"
    result_path = dispatch_dir / "result.json"

    if not request_path.exists():
        raise SystemExit("request.json does not exist")
    if not result_path.exists():
        raise SystemExit("result.json does not exist")

    request = load_dispatch_json(request_path)
    result = load_dispatch_json(result_path)
    if not request.get("review_required"):
        raise SystemExit("dispatch is not reviewer-gated")

    review_path = discover_review_artifact_path(dispatch_dir, request, repo_root)
    snapshot = capture_reviewer_guard_snapshot(repo_root, dispatch_dir)

    try:
        if args.review_json_file:
            source = Path(args.review_json_file).resolve()
            review_payload = load_review_artifact(source)
            if review_payload.get("dispatch_ref") != request["dispatch_ref"]:
                raise SystemExit("review payload dispatch_ref does not match request dispatch_ref")
            write_json(review_path, review_payload)
        elif review_path.exists():
            review_payload = load_review_artifact(review_path)
            if review_payload.get("dispatch_ref") != request["dispatch_ref"]:
                raise SystemExit("existing review artifact dispatch_ref does not match request dispatch_ref")
        else:
            review_payload = build_helper_review(repo_root, request, result)
            write_json(review_path, review_payload)
        enforce_reviewer_guard(repo_root, dispatch_dir, review_path, snapshot)
    except ReviewerContractViolation as exc:
        raise SystemExit(str(exc)) from exc

    review_rel = str(review_path.relative_to(repo_root))
    print(review_rel)
    return 0


def review_path_for_request(repo_root: Path, request: Dict[str, Any]) -> Optional[Path]:
    if request.get("review_required"):
        return resolve_review_artifact_path(repo_root, request["dispatch_ref"], request.get("review_artifact_path"))
    return None


def live_subagent_request(request: Dict[str, Any]) -> bool:
    execution_mode = request.get("execution_mode") or "manual_artifact_report"
    return execution_mode in SUBAGENT_ONLY_MODES


def decision_from_result_and_review(request: Dict[str, Any], result: Dict[str, Any], review: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if result.get("status") != "completed" or result.get("blocker"):
        return {
            "decision": "reject",
            "reason": "executor result is not a clean completed result",
            "recommended_next_action": "redispatch_or_escalate",
        }

    if request.get("review_required"):
        if review is None:
            return {
                "decision": "needs_review",
                "reason": "review_required is true but no review artifact is available",
                "recommended_next_action": "run_reviewer",
            }
        verdict = review.get("verdict")
        if verdict == "pass":
            return {
                "decision": "accept",
                "reason": "reviewer passed and executor result is complete",
                "recommended_next_action": "governor_may_accept",
            }
        if verdict == "request_changes":
            return {
                "decision": "reject",
                "reason": "reviewer requested changes",
                "recommended_next_action": "redispatch_or_reject",
            }
        return {
            "decision": "needs_verification",
            "reason": "reviewer was inconclusive",
            "recommended_next_action": "bounded_verification_or_reviewer_subagent",
        }

    return {
        "decision": "accept",
        "reason": "review not required and executor result is complete",
        "recommended_next_action": "governor_may_accept",
    }


def next_action_kind_for_decision(decision: Dict[str, Any], result: Dict[str, Any]) -> str:
    decision_value = decision.get("decision")
    if decision_value == "needs_review":
        return "route_review"
    if decision_value == "needs_verification":
        return "rerun_validation"
    if decision_value == "reject" and result.get("blocker"):
        return "structured_blocker"
    return "replan"


def build_finalize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Finalize a completed dispatch using executor and reviewer artifacts.")
    parser.add_argument("--dispatch-dir", required=True)
    parser.add_argument("--skip-auto-review", action="store_true")
    return parser


def finalize_main(argv: Optional[List[str]] = None) -> int:
    args = build_finalize_parser().parse_args(argv)

    dispatch_dir = Path(args.dispatch_dir).resolve()
    repo_root = repo_root_for_path(dispatch_dir)
    request = load_dispatch_json(dispatch_dir / "request.json")
    result = load_dispatch_json(dispatch_dir / "result.json")
    state_path = dispatch_dir / "state.json"
    state = load_dispatch_json(state_path) if state_path.exists() else {}
    if not artifact_only_executor_readout_request(repo_root, request, result=result, state=state):
        ensure_lane_worktree_tracked(repo_root, request)

    review_path = review_path_for_request(repo_root, request)
    review = None
    if (
        request.get("review_required")
        and review_path is not None
        and not review_path.exists()
        and not args.skip_auto_review
        and not live_subagent_request(request)
    ):
        snapshot = capture_reviewer_guard_snapshot(repo_root, dispatch_dir)
        try:
            subprocess.run(
                [
                    str(ensure_approved_python_binary()),
                    script_ref("reviewer_consume_dispatch.py", repo_root),
                    "--dispatch-dir",
                    str(dispatch_dir),
                ],
                cwd=str(repo_root),
                check=True,
                capture_output=True,
                text=True,
            )
            enforce_reviewer_guard(repo_root, dispatch_dir, review_path, snapshot)
        except ReviewerContractViolation as exc:
            raise SystemExit(str(exc)) from exc
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or "").strip()
            if "reviewer_contract_violation:" in message:
                raise SystemExit(message.splitlines()[-1]) from exc
            raise

    if review_path is not None and review_path.exists():
        review = load_review_artifact(review_path)

    decision = decision_from_result_and_review(request, result, review)
    payload = {
        "dispatch_ref": request["dispatch_ref"],
        "result_ref": str((dispatch_dir / "result.json").relative_to(repo_root)),
        "review_ref": str(review_path.relative_to(repo_root)) if review_path and review_path.exists() else None,
        **decision,
    }
    decision_path = dispatch_dir / "governor_decision.json"
    write_json(decision_path, payload)
    lane = request.get("lane")
    if isinstance(lane, str) and lane.strip():
        transition_payload = build_transition_payload(
            repo_root=repo_root,
            lane=lane,
            source="governor_finalize_dispatch",
            transition="continue_internal",
            next_action_kind=next_action_kind_for_decision(decision, result),
            next_action_ref=request.get("dispatch_ref"),
            next_action_summary=str(decision.get("recommended_next_action") or decision.get("reason") or ""),
            dispatch_ref=request.get("dispatch_ref"),
            decision_ref=repo_relative(decision_path, repo_root),
            evidence_refs=[
                repo_relative(dispatch_dir / "result.json", repo_root),
                repo_relative(decision_path, repo_root),
            ]
            + ([str(review_path.relative_to(repo_root))] if review_path and review_path.exists() else []),
            blocker={
                "category": "dispatch_blocker",
                "summary": str(result.get("blocker")),
                "artifact_refs": [repo_relative(dispatch_dir / "result.json", repo_root)],
                "forbidden_until_resolved": ["Do not treat this dispatch as lane-complete."],
            }
            if result.get("blocker")
            else None,
        )
        record_transition(repo_root, transition_payload)
        blocker = liveness_blocker(repo_root, lane, base_ref="main")
        if blocker:
            raise SystemExit(blocker)
    print(str(decision_path.relative_to(repo_root)))
    return 0


def run(command: str, argv: list[str]) -> int:
    command_map: dict[str, DispatchRoute] = {
        "emit": emit_main,
        "emit-micro": lambda rest: __import__(
            "orchestration.scripts.governor_emit_micro_dispatch", fromlist=["main"]
        ).main(rest),
        "validate": lambda rest: __import__(
            "orchestration.harness.dispatch_contracts", fromlist=["main"]
        ).main(rest),
        "start-guard": lambda rest: __import__(
            "orchestration.harness.start_guard", fromlist=["main"]
        ).main(rest),
        "consume-executor": lambda rest: __import__(
            "orchestration.harness.executor_runtime", fromlist=["main"]
        ).main(rest),
        "consume-reviewer": reviewer_main,
        "finalize": finalize_main,
    }
    return command_map[command](argv)
