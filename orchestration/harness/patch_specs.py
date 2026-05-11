from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from orchestration.harness.paths import resolve_paths

PATCH_SPEC_SCHEMA_VERSION = "corgi.patch-spec.v1"


class PatchSpecError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def repo_path(repo_root: Path, rel_path: str, *, label: str = "patch spec path") -> Path:
    if Path(rel_path).is_absolute():
        raise PatchSpecError(f"{label} must be repo-relative: {rel_path}")
    candidate = (repo_root / rel_path).resolve()
    try:
        candidate.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise PatchSpecError(f"{label} escapes repo root: {rel_path}") from exc
    return candidate


def validate_dispatch_ref(dispatch_ref: str) -> None:
    if not isinstance(dispatch_ref, str) or not dispatch_ref.strip() or dispatch_ref != dispatch_ref.strip():
        raise PatchSpecError("dispatch_ref must be a non-empty relative artifact ref")
    if "\\" in dispatch_ref:
        raise PatchSpecError("dispatch_ref must use forward-slash artifact refs")
    if Path(dispatch_ref).is_absolute():
        raise PatchSpecError("dispatch_ref must be relative")
    parts = dispatch_ref.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise PatchSpecError("dispatch_ref must not contain empty, dot, or parent segments")


def dispatch_family_dir(repo_root: Path, family: str, dispatch_ref: str) -> Path:
    validate_dispatch_ref(dispatch_ref)
    agent_root = resolve_paths(repo_root).agent_root
    family_root = (agent_root / family).resolve()
    candidate = (family_root / Path(*dispatch_ref.split("/"))).resolve()
    try:
        candidate.relative_to(family_root)
    except ValueError as exc:
        raise PatchSpecError(f"dispatch_ref escapes .agent/{family}: {dispatch_ref}") from exc
    return candidate


def dispatch_request_path(repo_root: Path, dispatch_ref: str) -> Path:
    return dispatch_family_dir(repo_root, "dispatches", dispatch_ref) / "request.json"


def load_dispatch_request(repo_root: Path, dispatch_ref: str) -> dict[str, Any]:
    request_path = dispatch_request_path(repo_root, dispatch_ref)
    if not request_path.exists():
        raise PatchSpecError(f"dispatch request artifact missing for patch spec: {dispatch_ref}")
    return load_json(request_path)


def file_signature(path: Path) -> dict[str, Any]:
    source = path.read_bytes()
    return {
        "sha256": hashlib.sha256(source).hexdigest(),
        "size": len(source),
    }


def operation_for_text_replacement(
    repo_root: Path,
    *,
    rel_path: str,
    old_text: str,
    new_text: str,
    patch_artifact_ref: str,
    forbidden_text: str | None = None,
    expected_replacements: int = 1,
) -> dict[str, Any]:
    target = repo_path(repo_root, rel_path, label="patch operation path")
    if not target.exists():
        raise PatchSpecError(f"patch target is missing: {rel_path}")
    signature = file_signature(target)
    operation: dict[str, Any] = {
        "path": rel_path,
        "old_text": old_text,
        "new_text": new_text,
        "expected_replacements": expected_replacements,
        "patch_artifact": patch_artifact_ref,
        "before_sha256": signature["sha256"],
        "before_size": signature["size"],
    }
    if forbidden_text:
        operation["forbidden_text"] = forbidden_text
    return operation


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def declared_patch_targets(request: dict[str, Any]) -> set[str]:
    executor_run = request.get("executor_run") if isinstance(request.get("executor_run"), dict) else {}
    declared = set(_string_list(request.get("required_outputs")))
    declared.update(_string_list(executor_run.get("planned_file_touch_list")))
    return declared


def validate_patch_artifact_ref(repo_root: Path, dispatch_ref: str, artifact_ref: str) -> None:
    artifact_path = repo_path(repo_root, artifact_ref, label="patch_artifact")
    expected_root = dispatch_family_dir(repo_root, "patches", dispatch_ref)
    try:
        artifact_path.relative_to(expected_root)
    except ValueError as exc:
        raise PatchSpecError(
            f"patch_artifact must live under {expected_root}"
        ) from exc


def validate_patch_spec_path(repo_root: Path, dispatch_ref: str, spec_path: Path) -> None:
    expected_root = dispatch_family_dir(repo_root, "patch_specs", dispatch_ref)
    try:
        spec_path.resolve().relative_to(expected_root)
    except ValueError as exc:
        raise PatchSpecError(f"patch spec must live under {expected_root}") from exc


def validate_patch_operation(
    repo_root: Path,
    dispatch_ref: str,
    operation: dict[str, Any],
    *,
    request: dict[str, Any] | None,
) -> str:
    rel_path = operation.get("path")
    old_text = operation.get("old_text")
    new_text = operation.get("new_text")
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise PatchSpecError("patch operation missing path")
    if not isinstance(old_text, str) or not old_text:
        raise PatchSpecError(f"patch operation for {rel_path} missing old_text")
    if not isinstance(new_text, str) or not new_text:
        raise PatchSpecError(f"patch operation for {rel_path} missing new_text")
    if old_text == new_text:
        raise PatchSpecError(f"patch operation for {rel_path} is a no-op")

    expected_replacements = operation.get("expected_replacements", 1)
    if not isinstance(expected_replacements, int) or expected_replacements < 1:
        raise PatchSpecError(f"patch operation for {rel_path} has invalid expected_replacements")

    target_path = repo_path(repo_root, rel_path, label="patch operation path")
    if not target_path.exists():
        raise PatchSpecError(f"patch target is missing: {rel_path}")

    patch_artifact = operation.get("patch_artifact")
    if not isinstance(patch_artifact, str) or not patch_artifact.strip():
        raise PatchSpecError(f"patch operation for {rel_path} missing patch_artifact")
    validate_patch_artifact_ref(repo_root, dispatch_ref, patch_artifact)

    before_sha256 = operation.get("before_sha256")
    before_size = operation.get("before_size")
    if not isinstance(before_sha256, str) or not before_sha256:
        raise PatchSpecError(f"patch operation for {rel_path} missing before_sha256")
    if not isinstance(before_size, int) or before_size < 0:
        raise PatchSpecError(f"patch operation for {rel_path} missing before_size")
    current = file_signature(target_path)
    if current["sha256"] != before_sha256 or current["size"] != before_size:
        raise PatchSpecError(f"patch operation for {rel_path} is stale")

    if request is not None and rel_path not in declared_patch_targets(request):
        raise PatchSpecError(f"patch operation path is not declared by dispatch: {rel_path}")

    return rel_path


def validate_patch_spec_payload(
    repo_root: Path,
    payload: dict[str, Any],
    *,
    dispatch_ref: str,
    request: dict[str, Any] | None = None,
    require_executor_proposed: bool = True,
) -> None:
    if payload.get("schema_version") != PATCH_SPEC_SCHEMA_VERSION:
        raise PatchSpecError(f"patch spec schema_version must be {PATCH_SPEC_SCHEMA_VERSION}")
    if payload.get("dispatch_ref") != dispatch_ref:
        raise PatchSpecError("patch spec dispatch_ref does not match")
    if require_executor_proposed and payload.get("proposed_by") != "executor":
        raise PatchSpecError("patch spec proposed_by must be executor")
    operations = payload.get("operations")
    if not isinstance(operations, list) or not operations:
        raise PatchSpecError("patch spec must contain at least one operation")

    seen_paths: set[str] = set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise PatchSpecError("patch spec operation must be an object")
        rel_path = validate_patch_operation(
            repo_root,
            dispatch_ref,
            operation,
            request=request,
        )
        if rel_path in seen_paths:
            raise PatchSpecError(f"patch spec contains duplicate target path: {rel_path}")
        seen_paths.add(rel_path)
