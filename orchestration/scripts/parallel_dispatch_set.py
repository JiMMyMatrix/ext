#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.parallel_dispatch import (  # noqa: E402
    parallel_set_artifact_path,
    parallel_set_blockers,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a reviewed conservative parallel dispatch set.")
    parser.add_argument("--parallel-set-ref", required=True)
    parser.add_argument("--root", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = Path(args.root).resolve()
    set_path = parallel_set_artifact_path(repo_root, args.parallel_set_ref)
    if not set_path.exists():
        raise SystemExit(f"parallel_set_missing:{args.parallel_set_ref}")
    blockers = parallel_set_blockers(
        repo_root,
        {"parallel_set_ref": args.parallel_set_ref, "dispatch_ref": "__set_validation__"},
    )
    blockers = [blocker for blocker in blockers if blocker != "parallel_set_member_missing:__set_validation__"]
    if blockers:
        raise SystemExit("; ".join(blockers))
    print(f"parallel_set_valid:{args.parallel_set_ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

