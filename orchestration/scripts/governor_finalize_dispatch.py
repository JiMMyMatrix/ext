#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.dispatch import (
    build_finalize_parser,
    decision_from_result_and_review,
    finalize_main as main,
    live_subagent_request,
    next_action_kind_for_decision,
    review_path_for_request,
)


if __name__ == "__main__":
    raise SystemExit(main())
