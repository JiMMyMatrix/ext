#!/usr/bin/env python3
"""Write an Executor-authored patch specification for a bounded dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.patch_specs import (  # noqa: E402
    PATCH_SPEC_SCHEMA_VERSION,
    PatchSpecError,
    load_dispatch_request,
    operation_for_text_replacement,
    repo_path,
    validate_patch_spec_path,
    validate_patch_spec_payload,
    write_json,
)


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


def propose_pet_diary_entry_submit(
    repo_root: Path,
    *,
    dispatch_ref: str,
    spec_ref: str,
    patch_artifact_ref: str,
    objective: str,
) -> None:
    app_path = repo_path(repo_root, "src/app.js", label="patch proposal path")
    if not app_path.exists():
        raise SystemExit("src/app.js is missing; cannot propose Pet Life Diary patch")
    source = app_path.read_text(encoding="utf-8")
    if "diaryEntries.push" in source:
        raise SystemExit("src/app.js already appends diary entries; this dispatch must mutate the seeded bug")
    if PET_DIARY_BUGFIX_OLD_SNIPPET not in source:
        raise SystemExit("src/app.js does not contain the expected seeded diary-entry bug")

    payload = {
        "schema_version": PATCH_SPEC_SCHEMA_VERSION,
        "dispatch_ref": dispatch_ref,
        "objective": objective,
        "intent": "Fix the Pet Life Diary submit handler so new diary entries are appended before rendering.",
        "proposed_by": "executor",
        "recipe": "pet_diary_entry_submit",
        "operations": [
            operation_for_text_replacement(
                repo_root,
                rel_path="src/app.js",
                old_text=PET_DIARY_BUGFIX_OLD_SNIPPET,
                new_text=PET_DIARY_BUGFIX_NEW_SNIPPET,
                expected_replacements=1,
                forbidden_text="diaryEntries.push",
                patch_artifact_ref=patch_artifact_ref,
            )
        ],
    }
    request = load_dispatch_request(repo_root, dispatch_ref)
    validate_patch_spec_payload(repo_root, payload, dispatch_ref=dispatch_ref, request=request)
    spec_path = repo_path(repo_root, spec_ref, label="patch proposal path")
    validate_patch_spec_path(repo_root, dispatch_ref, spec_path)
    write_json(spec_path, payload)
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

    try:
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
    except PatchSpecError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
