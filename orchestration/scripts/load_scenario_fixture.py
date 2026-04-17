#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.scenario_fixtures import (  # noqa: E402
	list_scenarios,
	materialize_scenario,
)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Developer-only loader for checked-in orchestration scenario fixtures."
	)
	parser.add_argument("--scenario", choices=list_scenarios())
	parser.add_argument(
		"--root",
		default=".",
		help="Repo root to receive the fixture overlay. Defaults to the current directory.",
	)
	parser.add_argument(
		"--replace",
		action="store_true",
		help="Replace top-level fixture-owned paths in the target before copying.",
	)
	parser.add_argument(
		"--list",
		action="store_true",
		help="List the available fixture scenarios and exit.",
	)
	return parser


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	if args.list:
		for name in list_scenarios():
			print(name)
		return 0

	if not args.scenario:
		raise SystemExit("--scenario is required unless --list is used")

	target = materialize_scenario(
		args.scenario,
		args.root,
		replace_existing=args.replace,
	)
	print(f"Loaded scenario fixture '{args.scenario}' into {target}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
