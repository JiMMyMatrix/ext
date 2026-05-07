#!/usr/bin/env python3
"""Development-only consulting MCP entrypoint.

Use this from the Corgi development environment when the human/Codex pair needs
advisor help. Product/runtime Corgi Governor use must keep using `mcp_server.py`.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
	repo_root = Path(__file__).resolve().parent
	launcher = repo_root / "orchestration" / "scripts" / "serve_development_consulting_mcp.py"
	sys.argv = [str(launcher), *sys.argv[1:]]
	runpy.run_path(str(launcher), run_name="__main__")


if __name__ == "__main__":
	main()
