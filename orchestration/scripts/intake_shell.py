#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.intake import (
	accepted_intake_path,
	answer_intake_clarification,
	build_shell_parser,
	intake_dir,
	raw_request_path,
	request_draft_path,
	shell_main as main,
	start_intake,
)


if __name__ == "__main__":
	raise SystemExit(main())
