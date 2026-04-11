#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_lane_merge_ready import merge_ready_blocker
from scripts.governor_transition import (
    ALLOWED_HUMAN_STOP_REASONS,
    BLOCKER_STOP_REASONS,
    lane_completion_rule,
    load_transition,
)


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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed gate for human-facing governor interrupts.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()
    blocker = interrupt_gate_blocker(repo_root, args.lane, base_ref=args.base_ref)
    if blocker:
        raise SystemExit(f"illegal_human_interrupt:{blocker}")

    payload = load_transition(repo_root, args.lane)
    assert payload is not None
    print(f"interrupt_allowed:{payload['requested_stop_reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
