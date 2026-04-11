#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.dispatch import (
    build_helper_review,
    build_reviewer_parser,
    discover_review_artifact_path,
    reviewer_main as main,
)


if __name__ == "__main__":
    raise SystemExit(main())
