#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.start_guard import (
    ACTIVE_HELPER_STATUSES,
    AUXILIARY_PREFIXES,
    MAX_ACTIVE_ISOLATED_OVERLAP_DISPATCHES,
    MAX_ACTIVE_PARALLEL_DISPATCHES,
    SUBAGENT_ONLY_MODES,
    accepted_coverage_records,
    collect_active_dispatches,
    dependency_blockers,
    dependency_satisfied,
    dispatch_dir_for_ref,
    ensure_dispatch_startable,
    ensure_lane_worktree_tracked,
    execution_mode_for_request,
    find_start_blockers,
    format_blockers,
    main,
    normalize_scope_entry,
    path_is_covered,
    path_like_string,
    request_dependency_refs,
    request_scope_reservations,
    scopes_overlap,
    tracked_path_is_auxiliary,
    worktree_coverage_blockers,
    worktree_substantive_paths,
)


if __name__ == "__main__":
    raise SystemExit(main())
