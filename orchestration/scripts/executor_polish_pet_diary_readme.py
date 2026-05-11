#!/usr/bin/env python3
"""Polish README.md for the Pet Life Diary goal-program benchmark."""

from __future__ import annotations

import argparse
from pathlib import Path


README_BODY = """# Pet Life Diary

Pet Life Diary is a small static portfolio demo for tracking everyday pet notes.
It is intentionally dependency-free: open `index.html` in a browser and the app
loads sample diary entries from the project files.

## Demo highlights

- Add a new diary entry from the page.
- Filter entries by pet species.
- Review sample pet data in `data/sample-pets.json`.

## Project files

- `index.html` defines the demo shell and form controls.
- `src/app.js` owns the diary entries, filtering, and rendering behavior.
- `src/styles.css` keeps the UI simple and friendly.
- `data/sample-pets.json` provides small sample data for the demo.

## How to run

Open `index.html` in any modern browser. No install step is required.

## Corgi build notes

This demo was completed as a multi-step Corgi goal: create the base app, add a
species filter, then polish the README for handoff.
"""


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Polish the Pet Life Diary README.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", required=True)
	args = parser.parse_args(argv)
	readme = Path(args.repo_root).resolve() / "README.md"
	if not readme.exists():
		raise SystemExit("README.md is missing; cannot polish the demo README")
	readme.write_text(README_BODY, encoding="utf-8")
	print(args.dispatch_ref)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
