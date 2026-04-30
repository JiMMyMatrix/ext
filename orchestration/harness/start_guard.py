from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestration.harness.paths import resolve_agent_root, unique_strings
from orchestration.scripts.overlap_worktree import OVERLAP_ISOLATION_MODE, requested_overlap_isolation

MAX_ACTIVE_PARALLEL_DISPATCHES = 2
MAX_ACTIVE_ISOLATED_OVERLAP_DISPATCHES = 2
ACTIVE_HELPER_STATUSES = {"claimed", "running", "validated"}
SUBAGENT_ONLY_MODES = {"guided_agent", "strict_refactor"}
AUXILIARY_PREFIXES = (
    ".agent/dispatches/",
    ".agent/governor/",
    ".agent/reviews/",
    ".agent/runs/",
    ".agent/smoke/",
    ".agent/worktrees/",
)


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dispatch_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return resolve_agent_root(repo_root) / "dispatches" / Path(dispatch_ref)


def execution_mode_for_request(request: Dict[str, Any]) -> str:
    return request.get("execution_mode") or "manual_artifact_report"


def normalize_scope_entry(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip("/")


def path_like_string(value: str) -> bool:
    if "/" in value or value.startswith("."):
        return True
    suffix = Path(value).suffix.lower()
    return suffix in {
        ".py",
        ".md",
        ".json",
        ".txt",
        ".toml",
        ".yaml",
        ".yml",
        ".sh",
    }


def request_scope_reservations(request: Dict[str, Any]) -> List[str]:
    explicit = request.get("scope_reservations")
    if isinstance(explicit, list):
        return [normalize_scope_entry(item) for item in unique_strings(explicit)]

    derived: List[str] = []
    executor_run = request.get("executor_run")
    if isinstance(executor_run, dict):
        derived.extend(unique_strings(executor_run.get("planned_file_touch_list", [])))

    execution_payload = request.get("execution_payload")
    if isinstance(execution_payload, dict):
        derived.extend(unique_strings(execution_payload.get("declared_files", [])))
        derived.extend(unique_strings(execution_payload.get("target_files", [])))

    derived.extend(unique_strings(request.get("required_outputs", [])))

    for item in unique_strings(request.get("scope", [])):
        if path_like_string(item):
            derived.append(item)

    return [normalize_scope_entry(item) for item in unique_strings(derived)]


def request_dependency_refs(request: Dict[str, Any]) -> List[str]:
    return unique_strings(request.get("depends_on_dispatches", []))


def scopes_overlap(left: List[str], right: List[str]) -> bool:
    for candidate in left:
        for active in right:
            if not candidate or not active:
                continue
            if candidate == active:
                return True
            if candidate.startswith(active + "/") or active.startswith(candidate + "/"):
                return True
    return False


def tracked_path_is_auxiliary(rel_path: str) -> bool:
    normalized = normalize_scope_entry(rel_path)
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in AUXILIARY_PREFIXES)


def path_is_covered(rel_path: str, coverage: List[str]) -> bool:
    normalized = normalize_scope_entry(rel_path)
    for reserved in coverage:
        if normalized == reserved:
            return True
        if normalized.startswith(reserved + "/"):
            return True
    return False


def _run_git(repo_root: Path, *argv: str) -> str:
    proc = subprocess.run(
        ["git", *argv],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def _required_outputs_exist(repo_root: Path, request: Dict[str, Any]) -> bool:
    for rel_path in request.get("required_outputs", []):
        if not isinstance(rel_path, str) or not rel_path.strip():
            continue
        if not (repo_root / rel_path).exists():
            return False
    return True


def dependency_satisfied(repo_root: Path, dispatch_ref: str) -> bool:
    dispatch_dir = dispatch_dir_for_ref(repo_root, dispatch_ref)
    request_path = dispatch_dir / "request.json"
    result_path = dispatch_dir / "result.json"
    decision_path = dispatch_dir / "governor_decision.json"
    if not request_path.exists() or not result_path.exists() or not decision_path.exists():
        return False

    request = load_json(request_path)
    result = load_json(result_path)
    decision = load_json(decision_path)
    if decision.get("decision") != "accept":
        return False
    if result.get("status") != "completed":
        return False
    if result.get("blocker"):
        return False
    auto_validated = result.get("auto_validated")
    if not isinstance(auto_validated, list) or not auto_validated:
        return False
    if not _required_outputs_exist(repo_root, request):
        return False
    return True


def dependency_blockers(repo_root: Path, request: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    for dispatch_ref in request_dependency_refs(request):
        if not dependency_satisfied(repo_root, dispatch_ref):
            blockers.append(f"unsatisfied_dependency:{dispatch_ref}")
    return blockers


def _helper_dispatch_active(dispatch_dir: Path) -> bool:
    state_path = dispatch_dir / "state.json"
    if not state_path.exists():
        return False
    try:
        state = load_json(state_path)
    except Exception:
        return False
    return state.get("status") in ACTIVE_HELPER_STATUSES


def _live_dispatch_active(dispatch_dir: Path) -> bool:
    bridge_path = dispatch_dir / "spawn_bridge.json"
    result_path = dispatch_dir / "result.json"
    if not bridge_path.exists() or result_path.exists():
        return False
    try:
        bridge = load_json(bridge_path)
    except Exception:
        return False
    executor_record = bridge.get("spawn_records", {}).get("executor")
    return isinstance(executor_record, dict) and executor_record.get("outcome") == "spawned"


def collect_active_dispatches(
    repo_root: Path,
    *,
    lane: Optional[str],
    exclude_dispatch_ref: Optional[str] = None,
) -> List[Dict[str, Any]]:
    active: List[Dict[str, Any]] = []
    queue_root = resolve_agent_root(repo_root) / "dispatches"
    if not queue_root.exists():
        return active

    for request_path in sorted(queue_root.rglob("request.json")):
        dispatch_dir = request_path.parent
        try:
            request = load_json(request_path)
        except Exception:
            continue
        dispatch_ref = request.get("dispatch_ref")
        if not isinstance(dispatch_ref, str) or not dispatch_ref.strip():
            continue
        if exclude_dispatch_ref and dispatch_ref == exclude_dispatch_ref:
            continue
        if lane and request.get("lane") != lane:
            continue
        if not (_helper_dispatch_active(dispatch_dir) or _live_dispatch_active(dispatch_dir)):
            continue
        active.append(
            {
                "dispatch_ref": dispatch_ref,
                "lane": request.get("lane"),
                "execution_mode": execution_mode_for_request(request),
                "task_track": request.get("task_track"),
                "scope_reservations": request_scope_reservations(request),
                "overlap_isolation": request.get("overlap_isolation"),
            }
        )
    return active


def accepted_coverage_records(
    repo_root: Path,
    *,
    lane: Optional[str],
    exclude_dispatch_ref: Optional[str] = None,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    queue_root = resolve_agent_root(repo_root) / "dispatches"
    if not queue_root.exists():
        return records

    for decision_path in sorted(queue_root.rglob("governor_decision.json")):
        dispatch_dir = decision_path.parent
        request_path = dispatch_dir / "request.json"
        if not request_path.exists():
            continue
        try:
            request = load_json(request_path)
        except Exception:
            continue
        dispatch_ref = request.get("dispatch_ref")
        if not isinstance(dispatch_ref, str) or not dispatch_ref.strip():
            continue
        if exclude_dispatch_ref and dispatch_ref == exclude_dispatch_ref:
            continue
        if lane and request.get("lane") != lane:
            continue
        if not dependency_satisfied(repo_root, dispatch_ref):
            continue
        coverage = request_scope_reservations(request)
        if not coverage:
            continue
        records.append(
            {
                "dispatch_ref": dispatch_ref,
                "coverage": coverage,
            }
        )
    return records


def worktree_substantive_paths(repo_root: Path) -> List[str]:
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return []
    try:
        output = _run_git(repo_root, "status", "--short", "--untracked-files=all")
    except Exception:
        return []
    paths: List[str] = []
    for raw_line in output.splitlines():
        if len(raw_line) < 4:
            continue
        rel_path = raw_line[3:]
        if " -> " in rel_path:
            rel_path = rel_path.split(" -> ", 1)[1]
        normalized = normalize_scope_entry(rel_path)
        if not normalized or tracked_path_is_auxiliary(normalized):
            continue
        paths.append(normalized)
    return unique_strings(paths)


def worktree_coverage_blockers(
    repo_root: Path,
    request: Dict[str, Any],
    *,
    include_current_request_scope: bool,
) -> List[str]:
    lane = request.get("lane")
    coverage_sets: List[List[str]] = []
    coverage_sets.extend(record["coverage"] for record in accepted_coverage_records(repo_root, lane=lane))
    coverage_sets.extend(
        active_dispatch.get("scope_reservations") or []
        for active_dispatch in collect_active_dispatches(
            repo_root,
            lane=lane,
            exclude_dispatch_ref=request.get("dispatch_ref"),
        )
    )
    if include_current_request_scope:
        coverage_sets.append(request_scope_reservations(request))

    blockers: List[str] = []
    for rel_path in worktree_substantive_paths(repo_root):
        if any(path_is_covered(rel_path, coverage) for coverage in coverage_sets if coverage):
            continue
        blockers.append(f"uncovered_worktree_change:{rel_path}")
    return unique_strings(blockers)


def find_start_blockers(repo_root: Path, request: Dict[str, Any]) -> List[str]:
    blockers = dependency_blockers(repo_root, request)
    active = collect_active_dispatches(
        repo_root,
        lane=request.get("lane"),
        exclude_dispatch_ref=request.get("dispatch_ref"),
    )
    if not active:
        return blockers

    if len(active) >= MAX_ACTIVE_PARALLEL_DISPATCHES:
        blockers.append(f"parallel_limit_reached:{MAX_ACTIVE_PARALLEL_DISPATCHES}")

    candidate_scope = request_scope_reservations(request)
    if not candidate_scope:
        blockers.append("parallel_scope_unknown")
        return unique_strings(blockers)

    candidate_overlap = requested_overlap_isolation(request)
    if candidate_overlap:
        isolated_active = sum(
            1
            for active_dispatch in active
            if requested_overlap_isolation(active_dispatch)
            and requested_overlap_isolation(active_dispatch).get("mode") == OVERLAP_ISOLATION_MODE
        )
        if isolated_active >= MAX_ACTIVE_ISOLATED_OVERLAP_DISPATCHES:
            blockers.append(f"isolated_overlap_limit_reached:{MAX_ACTIVE_ISOLATED_OVERLAP_DISPATCHES}")
    for active_dispatch in active:
        active_scope = active_dispatch.get("scope_reservations") or []
        if not active_scope:
            blockers.append(f"parallel_scope_unknown:{active_dispatch['dispatch_ref']}")
            continue
        if not scopes_overlap(candidate_scope, active_scope):
            continue
        if _overlap_isolation_allows_parallel_start(
            request,
            candidate_overlap,
            active_dispatch,
        ):
            continue
        if candidate_overlap and active_dispatch.get("overlap_isolation"):
            blockers.append(f"isolated_scope_conflict:{active_dispatch['dispatch_ref']}")
            continue
        blockers.append(f"scope_conflict:{active_dispatch['dispatch_ref']}")

    return unique_strings(blockers)


def _overlap_isolation_allows_parallel_start(
    candidate_request: Dict[str, Any],
    candidate_overlap: Optional[Dict[str, str]],
    active_dispatch: Dict[str, Any],
) -> bool:
    if execution_mode_for_request(candidate_request) not in SUBAGENT_ONLY_MODES:
        return False
    if candidate_request.get("task_track") != "patch":
        return False
    if not candidate_overlap or candidate_overlap.get("mode") != OVERLAP_ISOLATION_MODE:
        return False

    active_overlap = requested_overlap_isolation(active_dispatch)
    if not active_overlap or active_overlap.get("mode") != OVERLAP_ISOLATION_MODE:
        return False
    if active_dispatch.get("execution_mode") not in SUBAGENT_ONLY_MODES:
        return False
    if active_dispatch.get("task_track") != "patch":
        return False
    if candidate_overlap.get("overlap_group") != active_overlap.get("overlap_group"):
        return False
    if candidate_overlap.get("integration_policy") != active_overlap.get("integration_policy"):
        return False
    return True


def format_blockers(blockers: List[str]) -> str:
    if not blockers:
        return "no blockers"
    return "; ".join(blockers)


def ensure_dispatch_startable(repo_root: Path, request: Dict[str, Any]) -> None:
    blockers = find_start_blockers(repo_root, request)
    if blockers:
        raise SystemExit(
            f"dispatch {request.get('dispatch_ref', '<unknown>')} cannot start yet: {format_blockers(blockers)}"
        )


def ensure_lane_worktree_tracked(repo_root: Path, request: Dict[str, Any]) -> None:
    blockers = worktree_coverage_blockers(repo_root, request, include_current_request_scope=True)
    if blockers:
        raise SystemExit(
            f"lane worktree contains uncovered substantive changes before finalize: {format_blockers(blockers)}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed gate for dispatch start readiness.")
    parser.add_argument("--dispatch-dir")
    parser.add_argument("--dispatch-ref")
    parser.add_argument("--root", default=".")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.root).resolve()

    if args.dispatch_dir:
        dispatch_dir = Path(args.dispatch_dir).resolve()
    elif args.dispatch_ref:
        dispatch_dir = dispatch_dir_for_ref(repo_root, args.dispatch_ref)
    else:
        raise SystemExit("--dispatch-dir or --dispatch-ref is required")

    request_path = dispatch_dir / "request.json"
    if not request_path.exists():
        raise SystemExit(f"request.json does not exist: {request_path}")

    request = load_json(request_path)
    ensure_dispatch_startable(repo_root, request)
    print(f"start_allowed:{request.get('dispatch_ref', '<unknown>')}")
    return 0
