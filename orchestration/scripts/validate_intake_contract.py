#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.contracts import (
	build_intake_validator_parser,
	validate_accepted_intake,
	validate_intake_command as main,
	validate_request_draft,
)


if __name__ == "__main__":
	raise SystemExit(main())
