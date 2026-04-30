#!/usr/bin/env python3
"""Launch the Governor-only advisory MCP server under the approved Python."""

from __future__ import annotations

import os
import importlib.util
import runpy
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PATH = REPO_ROOT / "orchestration" / "runtime" / "advisory" / "mcp_server.py"
REQUIREMENTS_PATH = REPO_ROOT / "orchestration" / "runtime" / "advisory" / "requirements.txt"
ADVISORY_VENV_PYTHON = (
	REPO_ROOT / ".agent" / "orchestration" / "advisory" / ".venv" / "bin" / "python"
)
PYTHON_CANDIDATES = (
	"CORGI_ADVISORY_MCP_PYTHON",
	"ORCHESTRATION_ADVISORY_MCP_PYTHON",
	"ORCHESTRATION_APPROVED_PYTHON",
	"CORGI_PYTHON",
)
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


def _select_python() -> Path:
	for env_name in PYTHON_CANDIDATES:
		candidate = _resolve_python(os.environ.get(env_name))
		if candidate:
			return candidate
	if ADVISORY_VENV_PYTHON.exists():
		return ADVISORY_VENV_PYTHON.resolve()
	for candidate in HOMEBREW_PYTHON_CANDIDATES:
		if candidate.exists():
			return candidate.resolve()
	return Path(sys.executable).resolve()


def _prepare_env(approved_python: Path) -> dict[str, str]:
	env = os.environ.copy()
	existing_pythonpath = env.get("PYTHONPATH")
	env["PYTHONPATH"] = (
		str(REPO_ROOT)
		if not existing_pythonpath
		else str(REPO_ROOT) + os.pathsep + existing_pythonpath
	)
	env["ORCHESTRATION_REPO_ROOT"] = str(REPO_ROOT)
	env["ORCHESTRATION_APPROVED_PYTHON"] = str(approved_python)
	return env


def _verify_dependencies(approved_python: Path) -> None:
	missing: list[str] = []
	for module_name in ("anthropic", "mcp.server.fastmcp"):
		try:
			if importlib.util.find_spec(module_name) is None:
				missing.append(module_name)
		except ModuleNotFoundError:
			missing.append(module_name)
	if not missing:
		return

	raise SystemExit(
		"advisory MCP Python environment is missing dependencies: "
		+ ", ".join(sorted(set(missing)))
		+ "\nSelected Python: "
		+ str(approved_python)
		+ "\nRun: python3 orchestration/scripts/setup_advisory_mcp_env.py"
		+ "\nOr install manually: "
		+ str(approved_python)
		+ " -m pip install -r "
		+ str(REQUIREMENTS_PATH)
	)


def main() -> None:
	if not SERVER_PATH.exists():
		raise SystemExit(f"advisory MCP server not found: {SERVER_PATH}")

	approved_python = _select_python()
	env = _prepare_env(approved_python)
	current_python = Path(sys.executable).resolve()
	if current_python != approved_python:
		os.execve(
			str(approved_python),
			[str(approved_python), str(Path(__file__).resolve()), *sys.argv[1:]],
			env,
		)

	os.environ.update(env)
	_verify_dependencies(approved_python)
	sys.argv = [str(SERVER_PATH), *sys.argv[1:]]
	runpy.run_path(str(SERVER_PATH), run_name="__main__")


if __name__ == "__main__":
	main()
