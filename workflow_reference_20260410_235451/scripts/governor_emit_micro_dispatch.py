#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.governor_emit_dispatch import main as emit_dispatch_main

MICRO_DISPATCH_ALLOWED_PREFIXES = (
    "docs/",
    "reports/",
    "evidence/",
    ".agent/",
)
MICRO_DISPATCH_ALLOWED_EXACT = {
    "AGENTS.md",
    "PROJECT_MEMORY.md",
    "README.md",
}


def unique(values: List[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in out:
            out.append(stripped)
    return out


def default_run_touch_list(scope: List[str], required_outputs: List[str], scope_reservations: List[str]) -> List[str]:
    if scope_reservations:
        return unique(scope_reservations + required_outputs)
    return unique(scope + required_outputs)


def micro_dispatch_scope_allowed(path: str) -> bool:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized in MICRO_DISPATCH_ALLOWED_EXACT or normalized.startswith(MICRO_DISPATCH_ALLOWED_PREFIXES)


def validate_micro_dispatch_args(args: argparse.Namespace) -> None:
    if args.review_required:
        raise SystemExit("micro-dispatch is limited to low-risk helper-backed work and must not require reviewer gating")
    paths = unique(args.scope + args.required_output + args.scope_reservation)
    disallowed = [path for path in paths if not micro_dispatch_scope_allowed(path)]
    if disallowed:
        raise SystemExit(
            "micro-dispatch is limited to low-risk helper-backed docs/report/evidence surfaces; "
            f"use a normal dispatch for: {', '.join(disallowed)}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Emit a low-friction helper-backed micro dispatch.")
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--lane", required=True)
    parser.add_argument("--scope", action="append", required=True, default=[])
    parser.add_argument("--non-goal", action="append", default=[])
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--required-output", action="append", default=[])
    parser.add_argument("--acceptance-criterion", action="append", default=[])
    parser.add_argument("--required-validator", action="append", default=[])
    parser.add_argument("--stop-condition", action="append", default=[])
    parser.add_argument("--report-format", action="append", default=[])
    parser.add_argument("--task-track", choices=["diagnosis", "patch"], default="diagnosis")
    parser.add_argument("--command", action="append", required=True, default=[])
    parser.add_argument("--validator-command", action="append", default=[])
    parser.add_argument("--execution-summary")
    parser.add_argument("--execution-claim", action="append", default=[])
    parser.add_argument("--execution-evidence", action="append", default=[])
    parser.add_argument("--execution-note", action="append", default=[])
    parser.add_argument("--execution-next-action")
    parser.add_argument("--review-required", action="store_true")
    parser.add_argument("--review-focus", action="append", default=[])
    parser.add_argument("--review-artifact-path")
    parser.add_argument("--depends-on-dispatch", action="append", default=[])
    parser.add_argument("--scope-reservation", action="append", default=[])
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    validate_micro_dispatch_args(args)

    run_touch = default_run_touch_list(args.scope, args.required_output, args.scope_reservation)
    emit_argv: List[str] = [
        "--dispatch-ref",
        args.dispatch_ref,
        "--objective",
        args.objective,
        "--task-kind",
        "micro_dispatch",
        "--lane",
        args.lane,
        "--execution-mode",
        "command_chain",
        "--task-track",
        args.task_track,
        "--estimated-complexity",
        "low",
        "--executor-run-ref",
        args.dispatch_ref,
        "--run-objective",
        args.objective,
        "--run-scope",
        args.objective,
        "--root",
        args.root,
    ]

    for value in args.scope:
        emit_argv.extend(["--scope", value])
    for value in args.non_goal:
        emit_argv.extend(["--non-goal", value])
    for value in args.input:
        emit_argv.extend(["--input", value])
    for value in args.required_output:
        emit_argv.extend(["--required-output", value])
        emit_argv.extend(["--run-produce", value])
    for value in args.acceptance_criterion:
        emit_argv.extend(["--acceptance-criterion", value])
    for value in args.required_validator:
        emit_argv.extend(["--required-validator", value])
    for value in args.stop_condition:
        emit_argv.extend(["--stop-condition", value])
        emit_argv.extend(["--run-stop-condition", value])
    for value in args.report_format:
        emit_argv.extend(["--report-format", value])
    for value in args.command:
        emit_argv.extend(["--command", value])
    for value in args.validator_command:
        emit_argv.extend(["--validator-command", value])
    for value in args.execution_claim:
        emit_argv.extend(["--execution-claim", value])
    for value in args.execution_evidence:
        emit_argv.extend(["--execution-evidence", value])
    for value in args.execution_note:
        emit_argv.extend(["--execution-note", value])
    for value in args.review_focus:
        emit_argv.extend(["--review-focus", value])
    for value in args.depends_on_dispatch:
        emit_argv.extend(["--depends-on-dispatch", value])
    for value in args.scope_reservation:
        emit_argv.extend(["--scope-reservation", value])
    for value in run_touch:
        emit_argv.extend(["--run-touch", value])
    if args.execution_summary:
        emit_argv.extend(["--execution-summary", args.execution_summary])
    if args.execution_next_action:
        emit_argv.extend(["--execution-next-action", args.execution_next_action])
    if args.review_required:
        emit_argv.append("--review-required")
    if args.review_artifact_path:
        emit_argv.extend(["--review-artifact-path", args.review_artifact_path])

    return emit_dispatch_main(emit_argv)


if __name__ == "__main__":
    raise SystemExit(main())
