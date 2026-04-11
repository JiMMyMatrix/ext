#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.dispatch import (
    ALLOWED_ESTIMATED_COMPLEXITIES,
    ALLOWED_EXECUTION_MODES,
    ALLOWED_TASK_TRACKS,
    DEFAULT_HUMAN_ESCALATION_POLICY,
    DEFAULT_REPORT_FORMAT,
    build_coordination_fields,
    build_emit_parser,
    build_execution_payload,
    build_review_fields,
    dispatch_dir_for_ref,
    emit_main as main,
    parse_advisor_notes,
    parse_command_specs,
    parse_json_file,
    unique,
    validate_executor_run_ref_format,
)


if __name__ == "__main__":
    raise SystemExit(main())
