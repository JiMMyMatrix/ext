#!/usr/bin/env python3
"""Create a bounded baseline note for a scratch real-project exercise."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


IGNORED_DIRS = {".agent", ".git", "__pycache__", "node_modules", "dist", "out"}


def read_json(path: Path) -> dict[str, Any]:
	try:
		payload = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}
	return payload if isinstance(payload, dict) else {}


def list_project_files(repo_root: Path) -> list[str]:
	files: list[str] = []
	for path in sorted(repo_root.rglob("*")):
		if path.is_symlink() or not path.is_file():
			continue
		relative = path.relative_to(repo_root)
		if any(part in IGNORED_DIRS for part in relative.parts):
			continue
		files.append(str(relative))
	return files


def read_text(path: Path, *, limit: int = 1200) -> str:
	try:
		return path.read_text(encoding="utf-8").strip()[:limit]
	except OSError:
		return ""


def build_baseline_note(
	repo_root: Path,
	*,
	dispatch_ref: str,
	objective: str,
	accepted_intake_ref: str,
) -> str:
	accepted = read_json(resolve_inside_repo(repo_root, accepted_intake_ref))
	files = list_project_files(repo_root)
	package_json = read_json(repo_root / "package.json")
	scripts = package_json.get("scripts") if isinstance(package_json.get("scripts"), dict) else {}
	entry_candidates = [
		rel
		for rel in ["index.html", "src/app.js", "src/main.js", "src/index.js", "README.md"]
		if (repo_root / rel).exists()
	]
	lines = [
		"# Scratch Project Baseline",
		"",
		f"Dispatch: `{dispatch_ref}`",
		f"Objective: {objective}",
		f"Accepted intake: `{accepted_intake_ref}`",
		"",
		"## Current project shape",
		f"- Project file count outside `.agent`: {len(files)}",
	]
	if files:
		lines.append("- Existing project files:")
		lines.extend(f"  - `{rel}`" for rel in files[:80])
	else:
		lines.append("- Existing project files: none yet")
	if len(files) > 80:
		lines.append(f"  - ... {len(files) - 80} more omitted")
	lines.extend(
		[
			"",
			"## Entry points and scripts",
			f"- Entry candidates: {', '.join(f'`{rel}`' for rel in entry_candidates) if entry_candidates else 'none found'}",
		]
	)
	if scripts:
		lines.append("- Package scripts:")
		lines.extend(f"  - `{name}`: `{value}`" for name, value in sorted(scripts.items()))
	else:
		lines.append("- Package scripts: none found")
	readme = read_text(repo_root / "README.md")
	if readme:
		lines.extend(["", "## README preview", readme])
	lines.extend(
		[
			"",
			"## Accepted step context",
			f"- Task: {accepted.get('task') or 'unknown'}",
			f"- Goal step: {accepted.get('goal_step_ref') or 'unknown'}",
			"",
			"## Next execution guidance",
			"- This baseline step intentionally does not mutate product files.",
			"- The next step should create or mutate declared project outputs under dispatch truth.",
			"- If the project remains empty, the next step should create the app shell and data model.",
			"",
		]
	)
	return "\n".join(lines)


def resolve_inside_repo(repo_root: Path, value: str) -> Path:
	candidate = Path(value)
	target = candidate if candidate.is_absolute() else repo_root / candidate
	resolved = target.resolve()
	if resolved != repo_root and repo_root not in resolved.parents:
		raise SystemExit(f"Path escapes scratch workspace: {value}")
	return resolved


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Inspect a scratch project baseline.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", required=True)
	parser.add_argument("--accepted-intake", required=True)
	parser.add_argument("--output", required=True)
	args = parser.parse_args(argv)

	repo_root = Path(args.repo_root).resolve()
	output = resolve_inside_repo(repo_root, args.output)
	output.parent.mkdir(parents=True, exist_ok=True)
	output.write_text(
		build_baseline_note(
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
