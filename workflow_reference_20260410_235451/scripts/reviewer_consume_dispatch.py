#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.harness_artifacts import (
    ArtifactContractError,
    load_acceptance_review,
    load_review_artifact,
)
from scripts.reviewer_contract import (
    ReviewerContractViolation,
    capture_reviewer_guard_snapshot,
    enforce_reviewer_guard,
    resolve_review_artifact_path,
)


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

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Consume or generate reviewer output for a completed dispatch.")
    parser.add_argument("--dispatch-dir", required=True)
    parser.add_argument("--review-json-file")
    args = parser.parse_args(argv)

    dispatch_dir = Path(args.dispatch_dir).resolve()
    repo_root = repo_root_for_path(dispatch_dir)
    request_path = dispatch_dir / "request.json"
    result_path = dispatch_dir / "result.json"

    if not request_path.exists():
        raise SystemExit("request.json does not exist")
    if not result_path.exists():
        raise SystemExit("result.json does not exist")

    request = load_json(request_path)
    result = load_json(result_path)
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


if __name__ == "__main__":
    raise SystemExit(main())
