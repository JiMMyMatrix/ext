from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from orchestration.harness.paths import load_json, repo_relative, utc_now, write_json
from orchestration.harness.start_guard import (
    accepted_coverage_records,
    dependency_satisfied,
    normalize_scope_entry,
    path_is_covered,
    tracked_path_is_auxiliary,
    worktree_substantive_paths,
)
from orchestration.scripts.overlap_worktree import lane_overlap_blockers

TRANSITION_TYPES = {"continue_internal", "interrupt_human"}
ALLOWED_HUMAN_STOP_REASONS = {
    "merge_ready",
    "lane_complete",
    "material_blocker",
    "missing_permission",
    "missing_resource",
    "human_decision_required",
    "safety_boundary",
}
BLOCKER_STOP_REASONS = {
    "material_blocker",
    "missing_permission",
    "missing_resource",
    "human_decision_required",
    "safety_boundary",
}
ALLOWED_CONTINUE_ACTIONS = {
    "emit_dispatch",
    "route_review",
    "integrate_candidate",
    "rerun_validation",
    "structured_blocker",
    "replan",
}
DEFAULT_COMPLETION_MODE = "merge_ready_only"
SUPPORTED_COMPLETION_MODES = {DEFAULT_COMPLETION_MODE}


def governor_state_dir(repo_root: Path, lane: str) -> Path:
    return repo_root / ".agent" / "governor" / lane


def proposed_transition_path(repo_root: Path, lane: str) -> Path:
    return governor_state_dir(repo_root, lane) / "proposed_transition.json"


def lane_completion_rules_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "governance" / "lane_completion_rules.json"


def load_lane_completion_rules(repo_root: Path) -> Dict[str, Any]:
    path = lane_completion_rules_path(repo_root)
    if not path.exists():
        return {
            "default_completion_mode": DEFAULT_COMPLETION_MODE,
            "lanes": {},
        }
    payload = load_json(path)
    if not isinstance(payload, dict):
        return {
            "default_completion_mode": DEFAULT_COMPLETION_MODE,
            "lanes": {},
        }
    return payload


def lane_completion_rule(repo_root: Path, lane: str) -> Dict[str, Any]:
    rules = load_lane_completion_rules(repo_root)
    lane_rules = rules.get("lanes")
    lane_payload = lane_rules.get(lane) if isinstance(lane_rules, dict) else {}
    if not isinstance(lane_payload, dict):
        lane_payload = {}

    mode = lane_payload.get("completion_mode", rules.get("default_completion_mode", DEFAULT_COMPLETION_MODE))
    if mode not in SUPPORTED_COMPLETION_MODES:
        mode = DEFAULT_COMPLETION_MODE

    return {
        "completion_mode": mode,
        "rules_ref": repo_relative(lane_completion_rules_path(repo_root), repo_root),
    }


def _string_list(values: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if stripped and stripped not in out:
            out.append(stripped)
    return out


def build_transition_payload(
    *,
    repo_root: Path,
    lane: str,
    source: str,
    transition: str,
    requested_stop_reason: Optional[str] = None,
    next_action_kind: Optional[str] = None,
    next_action_ref: Optional[str] = None,
    next_action_summary: Optional[str] = None,
    dispatch_ref: Optional[str] = None,
    decision_ref: Optional[str] = None,
    evidence_refs: Optional[List[str]] = None,
    blocker: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if transition not in TRANSITION_TYPES:
        raise ValueError(f"transition must be one of: {', '.join(sorted(TRANSITION_TYPES))}")

    payload: Dict[str, Any] = {
        "lane": lane,
        "source": source,
        "created_at": utc_now(),
        "transition": transition,
        "requested_stop_reason": None,
        "dispatch_ref": dispatch_ref,
        "decision_ref": decision_ref,
        "evidence_refs": _string_list(evidence_refs),
        "next_action": None,
        "blocker": None,
        "completion_rule": lane_completion_rule(repo_root, lane),
    }

    if transition == "continue_internal":
        if next_action_kind not in ALLOWED_CONTINUE_ACTIONS:
            raise ValueError(f"continue_internal requires next_action.kind in: {', '.join(sorted(ALLOWED_CONTINUE_ACTIONS))}")
        payload["next_action"] = {
            "kind": next_action_kind,
            "ref": next_action_ref.strip() if isinstance(next_action_ref, str) and next_action_ref.strip() else None,
            "summary": next_action_summary.strip()
            if isinstance(next_action_summary, str) and next_action_summary.strip()
            else "",
        }
        return payload

    if requested_stop_reason not in ALLOWED_HUMAN_STOP_REASONS:
        raise ValueError(
            "requested_stop_reason must be one of: " + ", ".join(sorted(ALLOWED_HUMAN_STOP_REASONS))
        )
    payload["requested_stop_reason"] = requested_stop_reason

    if requested_stop_reason in BLOCKER_STOP_REASONS:
        if not isinstance(blocker, dict):
            raise ValueError("blocker metadata is required for blocker-style human interrupts")
        category = blocker.get("category")
        summary = blocker.get("summary")
        artifact_refs = _string_list(blocker.get("artifact_refs"))
        forbidden_until_resolved = _string_list(blocker.get("forbidden_until_resolved"))
        if not isinstance(category, str) or not category.strip():
            raise ValueError("blocker.category must be a non-empty string")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("blocker.summary must be a non-empty string")
        if not artifact_refs:
            raise ValueError("blocker.artifact_refs must contain at least one artifact ref")
        payload["blocker"] = {
            "category": category.strip(),
            "summary": summary.strip(),
            "artifact_refs": artifact_refs,
            "forbidden_until_resolved": forbidden_until_resolved,
        }

    return payload


def record_transition(repo_root: Path, payload: Dict[str, Any]) -> Path:
    lane = payload["lane"]
    path = proposed_transition_path(repo_root, lane)
    write_json(path, payload)
    return path


def load_transition(repo_root: Path, lane: str) -> Optional[Dict[str, Any]]:
    path = proposed_transition_path(repo_root, lane)
    if not path.exists():
        return None
    payload = load_json(path)
    if payload.get("lane") != lane:
        raise SystemExit("proposed_transition.json lane does not match requested lane")
    return payload


def run_git(repo_root: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def branch_changed_files(repo_root: Path, base_ref: str) -> List[str]:
    merge_base = run_git(repo_root, "merge-base", "HEAD", base_ref).strip()
    changed = run_git(repo_root, "diff", "--name-only", f"{merge_base}..HEAD").splitlines()
    return [normalize_scope_entry(path) for path in changed if path.strip() and not tracked_path_is_auxiliary(path)]


def worktree_is_clean(repo_root: Path) -> bool:
    return not worktree_substantive_paths(repo_root)


def uncovered_changed_files(changed_files: List[str], coverage_records: List[Dict[str, Any]]) -> List[str]:
    uncovered: List[str] = []
    for rel_path in changed_files:
        if any(path_is_covered(rel_path, record["coverage"]) for record in coverage_records):
            continue
        uncovered.append(rel_path)
    return uncovered


def lane_unresolved_blockers(repo_root: Path, lane: str) -> List[str]:
    queue_root = repo_root / ".agent" / "dispatches"
    if not queue_root.exists():
        return []

    blockers: List[str] = []
    for request_path in sorted(queue_root.rglob("request.json")):
        dispatch_dir = request_path.parent
        try:
            request = load_json(request_path)
        except Exception:
            continue
        if request.get("lane") != lane:
            continue

        dispatch_ref = request.get("dispatch_ref")
        state_path = dispatch_dir / "state.json"
        result_path = dispatch_dir / "result.json"
        decision_path = dispatch_dir / "governor_decision.json"

        state = load_json(state_path) if state_path.exists() else {}
        result = load_json(result_path) if result_path.exists() else None
        decision = load_json(decision_path) if decision_path.exists() else None

        decision_value = decision.get("decision") if isinstance(decision, dict) else None
        state_status = state.get("status")

        if decision_value in {"needs_review", "needs_verification"}:
            blockers.append(f"unresolved_decision:{dispatch_ref}")
            continue

        if request.get("review_required") and result is not None and decision_value is None:
            blockers.append(f"unresolved_review:{dispatch_ref}")
            continue

        if state_status in {"queued", "claimed", "running", "validated"} and decision_value not in {"accept", "reject"}:
            blockers.append(f"active_dispatch:{dispatch_ref}")
            continue

        if decision_value == "accept" and not dependency_satisfied(repo_root, dispatch_ref):
            blockers.append(f"incomplete_accepted_dispatch:{dispatch_ref}")

    blockers.extend(lane_overlap_blockers(repo_root, lane))
    return blockers


def merge_ready_blocker(repo_root: Path, lane: str, *, base_ref: str = "main") -> Optional[str]:
    if not worktree_is_clean(repo_root):
        return "worktree must be clean before final review or merge"

    changed_files = branch_changed_files(repo_root, base_ref)
    if not changed_files:
        return None

    coverage_records = accepted_coverage_records(repo_root, lane=lane)
    uncovered = uncovered_changed_files(changed_files, coverage_records)
    if uncovered:
        return (
            "changed files are not covered by accepted tracked dispatch scope: "
            + ", ".join(uncovered)
        )

    unresolved = lane_unresolved_blockers(repo_root, lane)
    if unresolved:
        return "unresolved lane workflow state remains: " + ", ".join(unresolved)

    return None


def interrupt_gate_blocker(repo_root: Path, lane: str, *, base_ref: str) -> Optional[str]:
    payload = load_transition(repo_root, lane)
    if payload is None:
        return "proposed_transition.json is missing"

    if payload.get("transition") != "interrupt_human":
        return "proposed transition is not a human interrupt"

    reason = payload.get("requested_stop_reason")
    if reason not in ALLOWED_HUMAN_STOP_REASONS:
        return "requested_stop_reason is not in the allowed human-stop allowlist"

    if reason == "merge_ready":
        return merge_ready_blocker(repo_root, lane, base_ref=base_ref)

    if reason == "lane_complete":
        completion_rule = lane_completion_rule(repo_root, lane)
        if completion_rule.get("completion_mode") != "merge_ready_only":
            return "lane_complete completion mode is unsupported"
        blocker = merge_ready_blocker(repo_root, lane, base_ref=base_ref)
        if blocker:
            return f"lane_complete requires merge_ready truth: {blocker}"
        return None

    blocker = payload.get("blocker")
    if reason in BLOCKER_STOP_REASONS:
        if not isinstance(blocker, dict):
            return "blocker metadata is required for blocker-style human interrupts"
        if not isinstance(blocker.get("category"), str) or not blocker["category"].strip():
            return "blocker.category must be a non-empty string"
        if not isinstance(blocker.get("summary"), str) or not blocker["summary"].strip():
            return "blocker.summary must be a non-empty string"
        artifact_refs = blocker.get("artifact_refs")
        if not isinstance(artifact_refs, list) or not artifact_refs or any(
            not isinstance(item, str) or not item.strip() for item in artifact_refs
        ):
            return "blocker.artifact_refs must be a non-empty list of strings"

    return None


def liveness_blocker(repo_root: Path, lane: str, *, base_ref: str) -> Optional[str]:
    transition = load_transition(repo_root, lane)

    if merge_ready_blocker(repo_root, lane, base_ref=base_ref) is None:
        return None

    if transition is not None and transition.get("transition") == "interrupt_human":
        blocker = interrupt_gate_blocker(repo_root, lane, base_ref=base_ref)
        if blocker is None:
            return None

    unresolved = lane_unresolved_blockers(repo_root, lane)
    if unresolved:
        return None

    if transition is not None and transition.get("transition") == "continue_internal":
        next_action = transition.get("next_action")
        if isinstance(next_action, dict) and next_action.get("kind") in ALLOWED_CONTINUE_ACTIONS:
            return None

    return "governor_stall: lane is unresolved, no legal stop reason exists, and no active or queued next action was recorded"


def build_interrupt_check_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed gate for human-facing governor interrupts.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--root", default=".")
    return parser


def interrupt_check_main(argv: Optional[list[str]] = None) -> int:
    args = build_interrupt_check_parser().parse_args(argv)

    repo_root = Path(args.root).resolve()
    blocker = interrupt_gate_blocker(repo_root, args.lane, base_ref=args.base_ref)
    if blocker:
        raise SystemExit(f"illegal_human_interrupt:{blocker}")

    payload = load_transition(repo_root, args.lane)
    assert payload is not None
    print(f"interrupt_allowed:{payload['requested_stop_reason']}")
    return 0


def build_liveness_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect illegal quiet stops and governor stalls.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--root", default=".")
    return parser


def liveness_main(argv: Optional[list[str]] = None) -> int:
    args = build_liveness_parser().parse_args(argv)

    repo_root = Path(args.root).resolve()
    blocker = liveness_blocker(repo_root, args.lane, base_ref=args.base_ref)
    if blocker:
        raise SystemExit(blocker)

    if merge_ready_blocker(repo_root, args.lane, base_ref=args.base_ref) is None:
        print("human_interrupt_allowed:merge_ready")
        return 0

    transition = load_transition(repo_root, args.lane)
    if transition and transition.get("transition") == "interrupt_human":
        print(f"human_interrupt_allowed:{transition['requested_stop_reason']}")
    elif transition and transition.get("transition") == "continue_internal":
        next_action = transition.get("next_action") or {}
        print(f"continue_internal:{next_action.get('kind', 'active_work')}")
    else:
        print("continue_internal:active_work")
    return 0


def build_merge_ready_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check whether a lane branch is merge-ready from tracked dispatch coverage.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--root", default=".")
    return parser


def merge_ready_main(argv: Optional[List[str]] = None) -> int:
    args = build_merge_ready_parser().parse_args(argv)

    repo_root = Path(args.root).resolve()

    blocker = merge_ready_blocker(repo_root, args.lane, base_ref=args.base_ref)
    if blocker:
        raise SystemExit("lane is not merge-ready: " + blocker)

    print("merge-ready")
    return 0


def build_record_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write a proposed governor transition and enforce stop/liveness gates.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--transition", choices=["continue_internal", "interrupt_human"], required=True)
    parser.add_argument("--requested-stop-reason", choices=sorted(ALLOWED_HUMAN_STOP_REASONS))
    parser.add_argument("--next-action-kind", choices=sorted(ALLOWED_CONTINUE_ACTIONS))
    parser.add_argument("--next-action-ref")
    parser.add_argument("--next-action-summary")
    parser.add_argument("--dispatch-ref")
    parser.add_argument("--decision-ref")
    parser.add_argument("--evidence-ref", action="append", default=[])
    parser.add_argument("--blocker-category")
    parser.add_argument("--blocker-summary")
    parser.add_argument("--blocker-artifact-ref", action="append", default=[])
    parser.add_argument("--forbidden-until-resolved", action="append", default=[])
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--root", default=".")
    return parser


def record_main(argv: Optional[list[str]] = None) -> int:
    args = build_record_parser().parse_args(argv)

    repo_root = Path(args.root).resolve()
    blocker = None
    if args.transition == "interrupt_human" and args.requested_stop_reason in BLOCKER_STOP_REASONS:
        blocker = {
            "category": args.blocker_category,
            "summary": args.blocker_summary,
            "artifact_refs": args.blocker_artifact_ref,
            "forbidden_until_resolved": args.forbidden_until_resolved,
        }

    payload = build_transition_payload(
        repo_root=repo_root,
        lane=args.lane,
        source=args.source,
        transition=args.transition,
        requested_stop_reason=args.requested_stop_reason,
        next_action_kind=args.next_action_kind,
        next_action_ref=args.next_action_ref,
        next_action_summary=args.next_action_summary,
        dispatch_ref=args.dispatch_ref,
        decision_ref=args.decision_ref,
        evidence_refs=args.evidence_ref,
        blocker=blocker,
    )
    path = record_transition(repo_root, payload)

    interrupt_blocker = interrupt_gate_blocker(repo_root, args.lane, base_ref=args.base_ref)
    if payload["transition"] == "interrupt_human" and interrupt_blocker:
        raise SystemExit(f"illegal_human_interrupt:{interrupt_blocker}")

    live_blocker = liveness_blocker(repo_root, args.lane, base_ref=args.base_ref)
    if live_blocker:
        raise SystemExit(live_blocker)

    print(str(path.relative_to(repo_root)))
    return 0


TransitionRoute = Callable[[list[str]], int]


def run(command: str, argv: list[str]) -> int:
    command_map: dict[str, TransitionRoute] = {
        "record": record_main,
        "interrupt-check": interrupt_check_main,
        "liveness-check": liveness_main,
        "merge-ready": merge_ready_main,
    }
    return command_map[command](argv)
