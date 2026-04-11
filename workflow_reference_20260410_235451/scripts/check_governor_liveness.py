#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_governor_interrupt_gate import interrupt_gate_blocker
from scripts.check_lane_merge_ready import lane_unresolved_blockers, merge_ready_blocker
from scripts.governor_transition import ALLOWED_CONTINUE_ACTIONS, load_transition


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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Detect illegal quiet stops and governor stalls.")
    parser.add_argument("--lane", required=True)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
