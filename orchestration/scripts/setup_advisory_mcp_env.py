#!/usr/bin/env python3
"""Create/update the repo-local Python environment for the advisory MCP server."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_ROOT = REPO_ROOT / ".agent" / "orchestration" / "advisory" / ".venv"
VENV_PYTHON = VENV_ROOT / "bin" / "python"
REQUIREMENTS_PATH = REPO_ROOT / "orchestration" / "runtime" / "advisory" / "requirements.txt"
HOMEBREW_PYTHON_CANDIDATES = (
	Path("/opt/homebrew/bin/python3"),
	Path("/usr/local/bin/python3"),
)


def _resolve_python(raw_path: str | None) -> Path | None:
	if not raw_path:
		return None
	path = Path(raw_path).expanduser()
	if path.exists():
		return path.resolve()
	return None


def _select_base_python() -> Path:
	for env_name in (
		"CORGI_ADVISORY_MCP_BASE_PYTHON",
		"CORGI_ADVISORY_MCP_PYTHON",
		"ORCHESTRATION_ADVISORY_MCP_PYTHON",
		"CORGI_PYTHON",
	):
		candidate = _resolve_python(os.environ.get(env_name))
		if candidate:
			return candidate
	for candidate in HOMEBREW_PYTHON_CANDIDATES:
		if candidate.exists():
			return candidate.resolve()
	return Path(sys.executable).resolve()


def main() -> int:
	base_python = _select_base_python()
	if not REQUIREMENTS_PATH.exists():
		print(f"requirements file not found: {REQUIREMENTS_PATH}", file=sys.stderr)
		return 1

	if not VENV_PYTHON.exists():
		VENV_ROOT.parent.mkdir(parents=True, exist_ok=True)
		subprocess.run([str(base_python), "-m", "venv", str(VENV_ROOT)], check=True)

	subprocess.run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"], check=True)
	subprocess.run(
		[str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)],
		check=True,
	)
	print(f"Advisory MCP Python: {VENV_PYTHON}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
