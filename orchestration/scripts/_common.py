from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.paths import (
	constraint_hints_from_text,
	default_lane,
	git_branch_name,
	load_json,
	next_intake_ref,
	repo_relative,
	resolve_paths,
	slugify,
	summarize,
	trim_text,
	unique_strings,
	utc_now,
	write_json,
	write_text,
)

_paths = resolve_paths()
REPO_ROOT = _paths.repo_root
AGENT_ROOT = _paths.agent_root
INTAKES_ROOT = _paths.intakes_root
ORCHESTRATION_STATE_ROOT = _paths.orchestration_state_root
UI_SESSION_PATH = _paths.ui_session_path
