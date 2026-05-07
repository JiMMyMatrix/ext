#!/usr/bin/env python3
"""Runtime Governor advisory MCP entrypoint.

This is the product/Corgi runtime surface. Use `dev_mcp_server.py` for
developer consulting while building Corgi.
"""

from __future__ import annotations

import runpy
import sys
import os
from pathlib import Path


def main() -> None:
	repo_root = Path(__file__).resolve().parent
	launcher = repo_root / "orchestration" / "scripts" / "serve_advisory_mcp.py"
	os.environ["CORGI_ADVISORY_CONTEXT"] = "corgi-governor-runtime"
	os.environ["CORGI_ADVISORY_CALLER_ROLE"] = "governor"
	os.environ.pop("CORGI_ADVISORY_LAUNCH_PROFILE", None)
	sys.argv = [str(launcher), *sys.argv[1:]]
	runpy.run_path(str(launcher), run_name="__main__")


if __name__ == "__main__":
	main()
