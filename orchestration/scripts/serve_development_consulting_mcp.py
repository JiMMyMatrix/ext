#!/usr/bin/env python3
"""Launch the development-only consulting MCP server.

This entrypoint intentionally uses the same advisory tool implementation as the
Governor runtime server, but marks the process as developer consulting. It is
not registered in the shipped Corgi runtime config.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
	source_root = Path(__file__).resolve().parents[2]
	launcher = source_root / "orchestration" / "scripts" / "serve_advisory_mcp.py"
	env = os.environ
	env["CORGI_ADVISORY_LAUNCH_PROFILE"] = "development"
	env["CORGI_ADVISORY_CONTEXT"] = "corgi-development-consulting"
	env["CORGI_ADVISORY_CALLER_ROLE"] = "developer"
	env["ORCHESTRATION_SOURCE_ROOT"] = str(source_root)
	env["ORCHESTRATION_REPO_ROOT"] = str(
		Path(env.get("ORCHESTRATION_REPO_ROOT") or source_root).resolve()
	)
	dev_state_dir = source_root / ".agent" / "development" / "advisory"
	env.setdefault(
		"CORGI_ADVISORY_STATE_DIR",
		str(dev_state_dir),
	)
	env.setdefault("MINIMAX_API_KEY_FILE", str(dev_state_dir / "minimax_api_key"))
	sys.argv = [str(launcher), *sys.argv[1:]]
	runpy.run_path(str(launcher), run_name="__main__")


if __name__ == "__main__":
	main()
