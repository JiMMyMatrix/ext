#!/usr/bin/env python3
"""Compatibility entrypoint for the repo-local Governor advisory MCP server."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
	repo_root = Path(__file__).resolve().parent
	launcher = repo_root / "orchestration" / "scripts" / "serve_advisory_mcp.py"
	sys.argv = [str(launcher), *sys.argv[1:]]
	runpy.run_path(str(launcher), run_name="__main__")


if __name__ == "__main__":
	main()
