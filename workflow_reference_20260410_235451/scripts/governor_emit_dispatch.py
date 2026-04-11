#!/usr/bin/env python3
import argparse
import json
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_executor_run_ref_format(run_ref: str) -> None:
    parts = run_ref.split("/")
    if len(parts) != 5 or any(not part.strip() for part in parts):
        raise SystemExit(
            "executor_run_ref must be five slash-separated non-empty segments: "
            "<cycle>/<scope_type>/<scope_ref>/<artifact_kind>/<attempt>"
        )


def dispatch_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return repo_root / ".agent" / "dispatches" / Path(dispatch_ref)


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


def main(argv: Optional[List[str]] = None) -> int:
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
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
