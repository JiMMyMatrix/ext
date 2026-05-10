#!/usr/bin/env python3
"""Validate that the Pet Life Diary submit flow appends and re-renders entries."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate(repo_root: Path) -> dict[str, Any]:
	app_path = repo_root / "src" / "app.js"
	index_path = repo_root / "index.html"
	failures: list[str] = []
	app_source = app_path.read_text(encoding="utf-8") if app_path.exists() else ""
	index_source = index_path.read_text(encoding="utf-8") if index_path.exists() else ""

	if "diary-form" not in index_source or "diary-entry-input" not in index_source:
		failures.append("index.html is missing the diary form/input used by the app")
	if "addEventListener(\"submit\"" not in app_source:
		failures.append("src/app.js does not register a submit handler")
	submit_handler_match = re.search(
		r'addEventListener\("submit"\s*,\s*\([^)]*\)\s*=>\s*\{(?P<body>.*?)\n\}\);',
		app_source,
		re.DOTALL,
	)
	submit_handler_body = submit_handler_match.group("body") if submit_handler_match else ""
	push_index = submit_handler_body.find("diaryEntries.push")
	render_after_push = submit_handler_body.find("renderEntries();", push_index)
	if not submit_handler_body:
		failures.append("src/app.js submit handler body could not be inspected")
	if push_index == -1:
		failures.append("src/app.js submit handler does not append submitted diary entries")
	if push_index != -1 and render_after_push == -1:
		failures.append("src/app.js submit handler does not re-render after appending the entry")

	return {
		"schema_version": "corgi.pet-diary-validation.v1",
		"status": "pass" if not failures else "fail",
		"checks": {
			"has_form": "diary-form" in index_source,
			"has_submit_handler": "addEventListener(\"submit\"" in app_source,
			"appends_entry_in_submit_handler": push_index != -1,
			"rerenders_after_append_in_submit_handler": push_index != -1
			and render_after_push != -1,
		},
		"failures": failures,
	}


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Validate the Pet Life Diary entry submit behavior.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--report", required=True)
	args = parser.parse_args(argv)

	repo_root = Path(args.repo_root).resolve()
	report_path = repo_root / args.report
	payload = validate(repo_root)
	write_json(report_path, payload)
	if payload["status"] != "pass":
		raise SystemExit("; ".join(payload["failures"]))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
