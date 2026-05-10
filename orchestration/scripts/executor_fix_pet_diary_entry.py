#!/usr/bin/env python3
"""Fix the seeded Pet Life Diary entry-submit bug for project benchmark tests."""

from __future__ import annotations

import argparse
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


def fix_app(repo_root: Path) -> None:
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
	app_path.write_text(source.replace(BUGGY_SNIPPET, FIXED_SNIPPET), encoding="utf-8")
	print("src/app.js")


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Fix the seeded Pet Life Diary entry submit bug.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", required=True)
	args = parser.parse_args(argv)
	del args.dispatch_ref, args.objective

	fix_app(Path(args.repo_root).resolve())
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
