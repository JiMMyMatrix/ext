from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="UI session bridge for orchestration-backed extension state")
	subparsers = parser.add_subparsers(dest="command", required=True)

	subparsers.add_parser("state")

	def add_governor_runtime(command_parser: argparse.ArgumentParser) -> None:
		command_parser.add_argument("--governor-runtime", choices=["exec", "external"], default="exec")

	submit = subparsers.add_parser("submit_prompt")
	submit.add_argument("--text", required=True)
	submit.add_argument("--request-id")
	submit.add_argument("--session-ref")
	submit.add_argument("--context-ref")
	submit.add_argument("--semantic-mode", choices=["sidecar-first", "governor-first"])
	submit.add_argument("--turn-type")
	submit.add_argument("--normalized-text")
	submit.add_argument("--paraphrase")
	submit.add_argument("--semantic-input-version")
	submit.add_argument("--semantic-summary-ref")
	submit.add_argument("--semantic-context-flags-json")
	submit.add_argument("--semantic-route-type")
	submit.add_argument("--semantic-confidence")
	submit.add_argument("--semantic-block-reason")
	submit.add_argument("--auto-consume-executor", action="store_true")
	add_governor_runtime(submit)

	answer = subparsers.add_parser("answer_clarification")
	answer.add_argument("--text", required=True)
	answer.add_argument("--request-id")
	answer.add_argument("--session-ref")
	answer.add_argument("--context-ref")
	answer.add_argument("--turn-type")
	answer.add_argument("--normalized-text")
	answer.add_argument("--paraphrase")
	answer.add_argument("--semantic-input-version")
	answer.add_argument("--semantic-summary-ref")
	answer.add_argument("--semantic-context-flags-json")
	answer.add_argument("--semantic-route-type")
	answer.add_argument("--semantic-confidence")
	answer.add_argument("--semantic-block-reason")
	answer.add_argument("--auto-consume-executor", action="store_true")
	add_governor_runtime(answer)

	set_scope = subparsers.add_parser("set_permission_scope")
	set_scope.add_argument("--text")
	set_scope.add_argument("--request-id")
	set_scope.add_argument("--session-ref")
	set_scope.add_argument("--context-ref")
	set_scope.add_argument("--permission-scope", required=True)
	set_scope.add_argument("--turn-type")
	set_scope.add_argument("--normalized-text")
	set_scope.add_argument("--paraphrase")
	set_scope.add_argument("--semantic-input-version")
	set_scope.add_argument("--semantic-summary-ref")
	set_scope.add_argument("--semantic-context-flags-json")
	set_scope.add_argument("--semantic-route-type")
	set_scope.add_argument("--semantic-confidence")
	set_scope.add_argument("--semantic-block-reason")
	set_scope.add_argument("--auto-consume-executor", action="store_true")
	add_governor_runtime(set_scope)

	decline = subparsers.add_parser("decline_permission")
	decline.add_argument("--request-id")
	decline.add_argument("--session-ref")
	decline.add_argument("--context-ref")

	execute_plan = subparsers.add_parser("execute_plan")
	execute_plan.add_argument("--request-id")
	execute_plan.add_argument("--session-ref")
	execute_plan.add_argument("--context-ref")
	execute_plan.add_argument("--auto-consume-executor", action="store_true")
	add_governor_runtime(execute_plan)

	revise_plan = subparsers.add_parser("revise_plan")
	revise_plan.add_argument("--text", required=True)
	revise_plan.add_argument("--request-id")
	revise_plan.add_argument("--session-ref")
	revise_plan.add_argument("--context-ref")
	add_governor_runtime(revise_plan)

	complete_governor = subparsers.add_parser("complete_governor_turn")
	complete_governor.add_argument("--runtime-request-id", required=True)
	complete_governor.add_argument("--body", required=True)
	complete_governor.add_argument("--thread-id")
	complete_governor.add_argument("--turn-id")
	complete_governor.add_argument("--item-id")
	complete_governor.add_argument("--runtime-source", default="app-server")

	fallback_governor = subparsers.add_parser("fallback_governor_turn")
	fallback_governor.add_argument("--runtime-request-id", required=True)
	fallback_governor.add_argument("--reason")

	fail_governor = subparsers.add_parser("fail_governor_turn")
	fail_governor.add_argument("--runtime-request-id", required=True)
	fail_governor.add_argument("--reason")

	interrupt = subparsers.add_parser("interrupt_run")
	interrupt.add_argument("--text")
	interrupt.add_argument("--request-id")
	interrupt.add_argument("--session-ref")
	interrupt.add_argument("--context-ref")
	interrupt.add_argument("--turn-type")
	interrupt.add_argument("--normalized-text")
	interrupt.add_argument("--paraphrase")
	interrupt.add_argument("--semantic-input-version")
	interrupt.add_argument("--semantic-summary-ref")
	interrupt.add_argument("--semantic-context-flags-json")
	interrupt.add_argument("--semantic-route-type")
	interrupt.add_argument("--semantic-confidence")
	interrupt.add_argument("--semantic-block-reason")

	reconnect = subparsers.add_parser("reconnect")
	reconnect.add_argument("--request-id")
	reconnect.add_argument("--session-ref")
	return parser


def dispatch_kwargs_from_args(
	args: argparse.Namespace, *, repo_root: str | Path | None = None
) -> dict[str, Any]:
	semantic_context_flags = None
	if getattr(args, "semantic_context_flags_json", None):
		semantic_context_flags = json.loads(args.semantic_context_flags_json)
	return {
		"command": args.command,
		"text": getattr(args, "text", None),
		"repo_root": repo_root,
		"session_ref": getattr(args, "session_ref", None),
		"request_id": getattr(args, "request_id", None),
		"context_ref": getattr(args, "context_ref", None),
		"permission_scope": getattr(args, "permission_scope", None),
		"semantic_mode": getattr(args, "semantic_mode", None),
		"turn_type": getattr(args, "turn_type", None),
		"normalized_text": getattr(args, "normalized_text", None),
		"paraphrase": getattr(args, "paraphrase", None),
		"semantic_input_version": getattr(args, "semantic_input_version", None),
		"semantic_summary_ref": getattr(args, "semantic_summary_ref", None),
		"semantic_context_flags": semantic_context_flags,
		"semantic_route_type": getattr(args, "semantic_route_type", None),
		"semantic_confidence": getattr(args, "semantic_confidence", None),
		"semantic_block_reason": getattr(args, "semantic_block_reason", None),
		"governor_runtime": getattr(args, "governor_runtime", "exec"),
		"runtime_request_id": getattr(args, "runtime_request_id", None),
		"runtime_body": getattr(args, "body", None),
		"runtime_thread_id": getattr(args, "thread_id", None),
		"runtime_turn_id": getattr(args, "turn_id", None),
		"runtime_item_id": getattr(args, "item_id", None),
		"runtime_source": getattr(args, "runtime_source", "app-server"),
		"fallback_reason": getattr(args, "reason", None),
		"auto_consume_executor": bool(getattr(args, "auto_consume_executor", False)),
	}
