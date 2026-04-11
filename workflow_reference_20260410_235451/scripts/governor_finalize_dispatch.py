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

from scripts.harness_artifacts import load_review_artifact
from scripts.dispatch_start_guard import ensure_lane_worktree_tracked
from scripts.harness_runtime import ensure_approved_python_binary
from scripts.check_governor_liveness import liveness_blocker
from scripts.governor_transition import build_transition_payload, record_transition, relative_path
from scripts.reviewer_contract import (
    ReviewerContractViolation,
    capture_reviewer_guard_snapshot,
    enforce_reviewer_guard,
    resolve_review_artifact_path,
)

SUBAGENT_ONLY_MODES = {"guided_agent", "strict_refactor"}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def repo_root_for_path(path: Path) -> Path:
    current = path.resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / ".git").exists():
            return candidate
    return REPO_ROOT


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


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Finalize a completed dispatch using executor and reviewer artifacts.")
    parser.add_argument("--dispatch-dir", required=True)
    parser.add_argument("--skip-auto-review", action="store_true")
    args = parser.parse_args(argv)

    dispatch_dir = Path(args.dispatch_dir).resolve()
    repo_root = repo_root_for_path(dispatch_dir)
    request = load_json(dispatch_dir / "request.json")
    result = load_json(dispatch_dir / "result.json")
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
                    "scripts/reviewer_consume_dispatch.py",
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
            decision_ref=relative_path(decision_path, repo_root),
            evidence_refs=[
                relative_path(dispatch_dir / "result.json", repo_root),
                relative_path(decision_path, repo_root),
            ]
            + ([str(review_path.relative_to(repo_root))] if review_path and review_path.exists() else []),
            blocker={
                "category": "dispatch_blocker",
                "summary": str(result.get("blocker")),
                "artifact_refs": [relative_path(dispatch_dir / "result.json", repo_root)],
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


if __name__ == "__main__":
    raise SystemExit(main())
