#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.dispatch_start_guard import (
    accepted_coverage_records,
    dependency_satisfied,
    normalize_scope_entry,
    path_is_covered,
    tracked_path_is_auxiliary,
    worktree_substantive_paths,
)
from scripts.overlap_worktree import lane_overlap_blockers


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether a lane branch is merge-ready from tracked dispatch coverage.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()

    blocker = merge_ready_blocker(repo_root, args.lane, base_ref=args.base_ref)
    if blocker:
        raise SystemExit("lane is not merge-ready: " + blocker)

    print("merge-ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
