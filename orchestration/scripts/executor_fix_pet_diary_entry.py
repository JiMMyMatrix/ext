#!/usr/bin/env python3
"""Fix the seeded Pet Life Diary entry-submit bug for project benchmark tests."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path


BUGGY_SNIPPET = """\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tinput.value = "";
\trenderEntries();
"""

FIXED_SNIPPET = """\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tdiaryEntries.push({
\t\ttext,
\t\tcreatedAt: "Just now",
\t});
\tinput.value = "";
\trenderEntries();
"""


def patch_path_for(repo_root: Path, dispatch_ref: str) -> Path:
	return repo_root / ".agent" / "patches" / Path(dispatch_ref) / "src-app-js.patch"


def fix_app(repo_root: Path, dispatch_ref: str) -> None:
	app_path = repo_root / "src" / "app.js"
	if not app_path.exists():
		raise SystemExit("src/app.js is missing; cannot fix Pet Life Diary entry submit bug")
	source = app_path.read_text(encoding="utf-8")
	if "diaryEntries.push" in source:
		raise SystemExit(
			"src/app.js already appends diary entries; this bugfix dispatch must mutate the seeded bug"
		)
	if BUGGY_SNIPPET not in source:
		raise SystemExit("src/app.js does not contain the expected seeded diary-entry bug")
	fixed_source = source.replace(BUGGY_SNIPPET, FIXED_SNIPPET)
	patch_path = patch_path_for(repo_root, dispatch_ref)
	patch_path.parent.mkdir(parents=True, exist_ok=True)
	patch_path.write_text(
		"".join(
			difflib.unified_diff(
				source.splitlines(keepends=True),
				fixed_source.splitlines(keepends=True),
				fromfile="a/src/app.js",
				tofile="b/src/app.js",
			)
		),
		encoding="utf-8",
	)
	app_path.write_text(fixed_source, encoding="utf-8")
	print("src/app.js")


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Fix the seeded Pet Life Diary entry submit bug.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", required=True)
	args = parser.parse_args(argv)
	del args.objective

	fix_app(Path(args.repo_root).resolve(), args.dispatch_ref)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
