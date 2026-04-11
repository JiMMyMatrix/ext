#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.paths import (
	actor_config_path,
	actor_config_ref,
	contract_path,
	contract_ref,
	prompt_path,
	prompt_ref,
	repo_relative,
	resolve_paths,
	script_path,
	script_ref,
)

_paths = resolve_paths()
REPO_ROOT = _paths.repo_root
ORCHESTRATION_ROOT = _paths.orchestration_root
PROMPTS_ROOT = _paths.prompts_root
CONTRACTS_ROOT = _paths.contracts_root
SCRIPTS_ROOT = _paths.scripts_root
RUNTIME_ROOT = _paths.runtime_root
ACTORS_ROOT = _paths.actors_root
