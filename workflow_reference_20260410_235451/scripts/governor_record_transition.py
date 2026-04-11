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
from scripts.check_governor_liveness import liveness_blocker
from scripts.governor_transition import (
    ALLOWED_CONTINUE_ACTIONS,
    ALLOWED_HUMAN_STOP_REASONS,
    build_transition_payload,
    record_transition,
)


def main(argv: Optional[list[str]] = None) -> int:
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
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()
    blocker = None
    if args.transition == "interrupt_human" and args.requested_stop_reason in {
        "material_blocker",
        "missing_permission",
        "missing_resource",
        "human_decision_required",
        "safety_boundary",
    }:
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


if __name__ == "__main__":
    raise SystemExit(main())
