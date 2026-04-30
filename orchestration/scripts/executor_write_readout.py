#!/usr/bin/env python3
"""Write a bounded Executor readout artifact for a Corgi dispatch.

This helper is intentionally deterministic. It gives the current helper-backed
Executor path a useful, user-visible artifact without pretending to be a live
interactive agent runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}


def read_text(path: Path, *, limit: int = 1600) -> str:
	try:
		text = path.read_text(encoding="utf-8")
	except OSError:
		return ""
	return text.strip()[:limit]


def first_existing(repo_root: Path, candidates: list[str]) -> list[tuple[str, str]]:
	found: list[tuple[str, str]] = []
	for rel in candidates:
		text = read_text(repo_root / rel)
		if text:
			found.append((rel, text))
	return found


def bullet(text: str) -> str:
	return f"- {text}"


def build_readout(
	repo_root: Path,
	*,
	dispatch_ref: str,
	objective: str,
	accepted_intake_ref: str | None,
) -> str:
	accepted_intake = read_json(repo_root / accepted_intake_ref) if accepted_intake_ref else {}
	goal = str(accepted_intake.get("goal") or objective).strip()
	constraints = accepted_intake.get("constraints")
	if not isinstance(constraints, list):
		constraints = []
	reference_files = first_existing(
		repo_root,
		[
			"AGENTS.md",
			"orchestration/README.md",
			"orchestration/workflow.md",
			"orchestration/contracts/dispatch.md",
			"orchestration/contracts/ux.md",
			"package.json",
		],
	)
	available_paths = [
		path
		for path in [
			"src/executionWindowPanel.ts",
			"src/executionTransport.ts",
			"src/phase1Model.ts",
			"src/semanticSidecar.ts",
			"orchestration/harness/session.py",
			"orchestration/harness/dispatch.py",
			"orchestration/harness/executor_runtime.py",
			"orchestration/contracts/dispatch.md",
			"orchestration/contracts/ux.md",
		]
		if (repo_root / path).exists()
	]
	lines = [
		"# Executor Readout",
		"",
		f"Dispatch: `{dispatch_ref}`",
		f"Objective: {goal}",
		"",
		"## Accepted Intake",
		bullet(f"Source: `{accepted_intake_ref}`" if accepted_intake_ref else "Source: unavailable"),
		bullet(f"Task: {accepted_intake.get('task') or goal}"),
	]
	for item in constraints:
		lines.append(bullet(f"Constraint: {item}"))
	lines.extend(
		[
			"",
			"## Architecture Boundaries",
			bullet("VS Code extension and webview own the human-facing interaction surface."),
			bullet("Dialog/controller code shapes deterministic UI actions and context refs."),
			bullet("Semantic interpretation proposes intent, but orchestration validates legality."),
			bullet("Orchestration owns session, permission, dispatch, actor launch, and fail-closed state."),
			bullet("Governor owns planning/dialogue decisions; Executor owns bounded dispatch work; Reviewer stays read-only."),
			bullet("Workflow truth remains artifact-based: accepted intake is intake truth, request.json is dispatch truth."),
			"",
			"## Likely Implementation Surfaces",
		]
	)
	lines.extend(bullet(f"`{path}`") for path in available_paths)
	lines.extend(
		[
			"",
			"## Evidence Sampled",
		]
	)
	for rel, text in reference_files:
		preview = " ".join(text.split())[:260]
		lines.append(bullet(f"`{rel}`: {preview}"))
	lines.extend(
		[
			"",
			"## Risks Or Unknowns",
			bullet("The helper-backed Executor readout samples known authority surfaces and entrypoints; it does not replace a future live interactive Executor runtime."),
			bullet("Directory names alone are not authority. Runtime-enforced policy and contracts should win over reference material."),
			bullet("If the requested work becomes write-capable, Executor must run under a dispatch that declares the intended file touch set."),
			"",
			"## Execution Readiness",
			"This dispatch produced a bounded readout artifact and did not modify product code. Governor should review the readout, then decide whether to finalize, request review, or dispatch a narrower follow-up.",
			"",
		]
	)
	return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Write a bounded Executor readout artifact.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", required=True)
	parser.add_argument("--accepted-intake")
	parser.add_argument("--output", required=True)
	args = parser.parse_args(argv)

	repo_root = Path(args.repo_root).resolve()
	output = Path(args.output)
	if not output.is_absolute():
		output = repo_root / output
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(
		build_readout(
			repo_root,
			dispatch_ref=args.dispatch_ref,
			objective=args.objective,
			accepted_intake_ref=args.accepted_intake,
		),
		encoding="utf-8",
	)
	print(str(output.relative_to(repo_root)))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
