#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.session import (
	build_parser,
	dispatch_session_action,
	handle_answer_clarification,
	handle_approve,
	handle_decline_or_hold,
	handle_interrupt,
	handle_reconnect,
	handle_submit_prompt,
	load_session,
	main,
	public_model,
	save_session,
)


if __name__ == "__main__":
	raise SystemExit(main())
