from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Callable

from orchestration.harness import audit, dispatch, intake, session, transition
from orchestration.harness.paths import resolve_paths

Route = Callable[[str, list[str]], int]


def _session_command(command: str, argv: list[str]) -> int:
	command_map = {
		"state": ["state"],
		"submit-prompt": ["submit_prompt"],
		"answer-clarification": ["answer_clarification"],
		"set-permission-scope": ["set_permission_scope"],
		"decline-permission": ["decline_permission"],
		"execute-plan": ["execute_plan"],
		"revise-plan": ["revise_plan"],
		"complete-governor-turn": ["complete_governor_turn"],
		"fallback-governor-turn": ["fallback_governor_turn"],
		"fail-governor-turn": ["fail_governor_turn"],
		"interrupt": ["interrupt_run"],
		"reconnect": ["reconnect"],
	}
	return session.main([*command_map[command], *argv])


def _intake_command(command: str, argv: list[str]) -> int:
	command_map: dict[str, Callable[[list[str]], int]] = {
		"start": lambda rest: intake.shell_main(["start", *rest]),
		"answer": lambda rest: intake.shell_main(["answer", *rest]),
		"accept": lambda rest: intake.accept_main(rest),
		"validate-draft": lambda rest: intake.validate_main(["draft", *rest]),
		"validate-accepted": lambda rest: intake.validate_main(["accepted", *rest]),
	}
	return command_map[command](argv)


def _advisory_command(command: str, argv: list[str]) -> int:
	if command != "serve":
		raise ValueError(f"unsupported advisory command: {command}")
	paths = resolve_paths()
	env = os.environ.copy()
	existing_pythonpath = env.get("PYTHONPATH")
	env["PYTHONPATH"] = (
		str(paths.repo_root)
		if not existing_pythonpath
		else str(paths.repo_root) + os.pathsep + existing_pythonpath
	)
	env["ORCHESTRATION_REPO_ROOT"] = str(paths.repo_root)
	completed = subprocess.run(
		[sys.executable, str(paths.scripts_root / "serve_advisory_mcp.py"), *argv],
		cwd=paths.repo_root,
		env=env,
	)
	return completed.returncode


def _audit_command(command: str, argv: list[str]) -> int:
	return audit.run(command, argv)


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Canonical orchestration CLI harness for the custom Codex replacement."
	)
	subparsers = parser.add_subparsers(dest="group", required=True)

	session_parser = subparsers.add_parser("session", help="Extension-facing intake/session commands.")
	session_parser.add_argument(
		"command",
		choices=[
			"state",
			"submit-prompt",
			"answer-clarification",
			"set-permission-scope",
			"decline-permission",
			"execute-plan",
			"revise-plan",
			"complete-governor-turn",
			"fallback-governor-turn",
			"fail-governor-turn",
			"interrupt",
			"reconnect",
		],
	)
	session_parser.add_argument("args", nargs=argparse.REMAINDER)

	intake_parser = subparsers.add_parser("intake", help="Canonical intake artifact commands.")
	intake_parser.add_argument(
		"command",
		choices=["start", "answer", "accept", "validate-draft", "validate-accepted"],
	)
	intake_parser.add_argument("args", nargs=argparse.REMAINDER)

	dispatch_parser = subparsers.add_parser("dispatch", help="Dispatch and execution lifecycle commands.")
	dispatch_parser.add_argument(
		"command",
		choices=[
			"emit",
			"emit-micro",
			"validate",
			"start-guard",
			"consume-executor",
			"consume-reviewer",
			"finalize",
		],
	)
	dispatch_parser.add_argument("args", nargs=argparse.REMAINDER)

	transition_parser = subparsers.add_parser("transition", help="Transition and stop/continue gates.")
	transition_parser.add_argument(
		"command",
		choices=["record", "interrupt-check", "liveness-check", "merge-ready"],
	)
	transition_parser.add_argument("args", nargs=argparse.REMAINDER)

	advisory_parser = subparsers.add_parser("advisory", help="Governor-scoped advisory runtime entrypoints.")
	advisory_parser.add_argument("command", choices=["serve"])
	advisory_parser.add_argument("args", nargs=argparse.REMAINDER)

	audit_parser = subparsers.add_parser("audit", help="Architecture and surface audit commands.")
	audit_parser.add_argument(
		"command",
		choices=["verify-architecture", "verify-paths", "verify-role-policy"],
	)
	audit_parser.add_argument("args", nargs=argparse.REMAINDER)

	return parser


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)

	group_routes: dict[str, Route] = {
		"session": _session_command,
		"intake": _intake_command,
		"dispatch": dispatch.run,
		"transition": transition.run,
		"advisory": _advisory_command,
		"audit": _audit_command,
	}

	try:
		return group_routes[args.group](args.command, list(args.args))
	except SystemExit as exc:
		if isinstance(exc.code, int):
			return exc.code
		if exc.code not in (None, 0):
			print(exc.code, file=sys.stderr)
		return 1
	except ValueError as exc:
		print(str(exc), file=sys.stderr)
		return 2
