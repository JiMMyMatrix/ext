#!/usr/bin/env python3
"""Apply a bounded Executor patch specification for command-backed dispatches."""

from __future__ import annotations

import argparse
import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PreparedPatch:
    rel_path: str
    target_path: Path
    before: str
    after: str
    patch_artifact: str | None


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_path(repo_root: Path, rel_path: str) -> Path:
    if Path(rel_path).is_absolute():
        raise SystemExit(f"patch spec path must be repo-relative: {rel_path}")
    candidate = (repo_root / rel_path).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"patch spec path escapes repo root: {rel_path}") from exc
    return candidate


def write_patch_artifact(
    repo_root: Path,
    artifact_ref: str,
    *,
    rel_path: str,
    before: str,
    after: str,
) -> None:
    artifact_path = repo_path(repo_root, artifact_ref)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    patch_source = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )
    if not patch_source:
        raise SystemExit(f"patch spec did not mutate {rel_path}")
    artifact_path.write_text(patch_source, encoding="utf-8")


def prepare_operation(repo_root: Path, operation: dict[str, Any]) -> PreparedPatch:
    rel_path = operation.get("path")
    old_text = operation.get("old_text")
    new_text = operation.get("new_text")
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise SystemExit("patch operation missing path")
    if not isinstance(old_text, str) or not old_text:
        raise SystemExit(f"patch operation for {rel_path} missing old_text")
    if not isinstance(new_text, str) or not new_text:
        raise SystemExit(f"patch operation for {rel_path} missing new_text")

    target_path = repo_path(repo_root, rel_path)
    if not target_path.exists():
        raise SystemExit(f"patch target is missing: {rel_path}")
    before = target_path.read_text(encoding="utf-8")

    forbidden_text = operation.get("forbidden_text")
    if isinstance(forbidden_text, str) and forbidden_text and forbidden_text in before:
        raise SystemExit(f"patch target already contains forbidden text: {rel_path}")

    expected_replacements = operation.get("expected_replacements", 1)
    if not isinstance(expected_replacements, int) or expected_replacements < 1:
        raise SystemExit(f"patch operation for {rel_path} has invalid expected_replacements")
    occurrences = before.count(old_text)
    if occurrences != expected_replacements:
        raise SystemExit(
            f"patch operation for {rel_path} expected {expected_replacements} replacement(s), found {occurrences}"
        )

    after = before.replace(old_text, new_text, expected_replacements)
    if after == before:
        raise SystemExit(f"patch spec did not mutate {rel_path}")

    patch_artifact = operation.get("patch_artifact")
    return PreparedPatch(
        rel_path=rel_path,
        target_path=target_path,
        before=before,
        after=after,
        patch_artifact=(
            patch_artifact if isinstance(patch_artifact, str) and patch_artifact.strip() else None
        ),
    )


def apply_spec(repo_root: Path, dispatch_ref: str, spec_path: Path) -> list[str]:
    spec = load_json(spec_path)
    if spec.get("schema_version") != "corgi.patch-spec.v1":
        raise SystemExit("unsupported patch spec schema_version")
    spec_dispatch_ref = spec.get("dispatch_ref")
    if spec_dispatch_ref != dispatch_ref:
        raise SystemExit("patch spec dispatch_ref does not match")
    operations = spec.get("operations")
    if not isinstance(operations, list) or not operations:
        raise SystemExit("patch spec must contain at least one operation")

    prepared: list[PreparedPatch] = []
    seen_paths: set[str] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise SystemExit("patch spec operation must be an object")
        patch = prepare_operation(repo_root, operation)
        if patch.rel_path in seen_paths:
            raise SystemExit(f"patch spec contains duplicate target path: {patch.rel_path}")
        seen_paths.add(patch.rel_path)
        prepared.append(patch)

    for patch in prepared:
        if patch.patch_artifact:
            write_patch_artifact(
                repo_root,
                patch.patch_artifact,
                rel_path=patch.rel_path,
                before=patch.before,
                after=patch.after,
            )
        patch.target_path.write_text(patch.after, encoding="utf-8")
    changed = [patch.rel_path for patch in prepared]
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply a bounded Corgi patch specification.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    spec_path = repo_path(repo_root, args.spec)
    changed = apply_spec(repo_root, args.dispatch_ref, spec_path)
    for rel_path in changed:
        print(rel_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
