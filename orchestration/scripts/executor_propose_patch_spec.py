#!/usr/bin/env python3
"""Write an Executor-authored patch specification for a bounded dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PET_DIARY_BUGFIX_OLD_SNIPPET = """\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tinput.value = "";
\trenderEntries();
"""

PET_DIARY_BUGFIX_NEW_SNIPPET = """\tconst text = input.value.trim();
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


def repo_path(repo_root: Path, rel_path: str) -> Path:
    if Path(rel_path).is_absolute():
        raise SystemExit(f"patch proposal path must be repo-relative: {rel_path}")
    candidate = (repo_root / rel_path).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"patch proposal path escapes repo root: {rel_path}") from exc
    return candidate


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def propose_pet_diary_entry_submit(
    repo_root: Path,
    *,
    dispatch_ref: str,
    spec_ref: str,
    patch_artifact_ref: str,
    objective: str,
) -> None:
    app_path = repo_path(repo_root, "src/app.js")
    if not app_path.exists():
        raise SystemExit("src/app.js is missing; cannot propose Pet Life Diary patch")
    source = app_path.read_text(encoding="utf-8")
    if "diaryEntries.push" in source:
        raise SystemExit("src/app.js already appends diary entries; this dispatch must mutate the seeded bug")
    if PET_DIARY_BUGFIX_OLD_SNIPPET not in source:
        raise SystemExit("src/app.js does not contain the expected seeded diary-entry bug")

    write_json(
        repo_path(repo_root, spec_ref),
        {
            "schema_version": "corgi.patch-spec.v1",
            "dispatch_ref": dispatch_ref,
            "objective": objective,
            "intent": "Fix the Pet Life Diary submit handler so new diary entries are appended before rendering.",
            "proposed_by": "executor",
            "recipe": "pet_diary_entry_submit",
            "operations": [
                {
                    "path": "src/app.js",
                    "old_text": PET_DIARY_BUGFIX_OLD_SNIPPET,
                    "new_text": PET_DIARY_BUGFIX_NEW_SNIPPET,
                    "expected_replacements": 1,
                    "forbidden_text": "diaryEntries.push",
                    "patch_artifact": patch_artifact_ref,
                }
            ],
        },
    )
    print(spec_ref)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose a bounded Corgi patch specification.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--recipe", required=True, choices=["pet_diary_entry_submit"])
    parser.add_argument("--spec", required=True)
    parser.add_argument("--patch-artifact", required=True)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.recipe == "pet_diary_entry_submit":
        propose_pet_diary_entry_submit(
            repo_root,
            dispatch_ref=args.dispatch_ref,
            spec_ref=args.spec,
            patch_artifact_ref=args.patch_artifact,
            objective=args.objective,
        )
        return 0
    raise SystemExit(f"unsupported patch proposal recipe: {args.recipe}")


if __name__ == "__main__":
    raise SystemExit(main())
