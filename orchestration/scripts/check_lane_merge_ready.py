#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.transition import (
    branch_changed_files,
    lane_unresolved_blockers,
    merge_ready_blocker,
    merge_ready_main as main,
    uncovered_changed_files,
    worktree_is_clean,
)


if __name__ == "__main__":
    raise SystemExit(main())
