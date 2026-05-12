from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from orchestration.harness.authorship_evidence import (
    file_signature,
    idempotent_output_allowlist,
    normalized_required_outputs,
)


RECOVERY_MANIFEST_SCHEMA_VERSION = "corgi.recovery_manifest.v1"
RECOVERY_RESULT_SCHEMA_VERSION = "corgi.recovery_result.v1"
MAX_RECOVERY_BLOB_BYTES = 5 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_relative(path: Path, repo_root: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve()))


def normalize_repo_rel(raw_path: str) -> str:
    rel_path = raw_path.strip()
    while rel_path.startswith("./"):
        rel_path = rel_path[2:]
    return rel_path


def resolve_repo_local(repo_root: Path, raw_path: str) -> Path:
    rel_path = normalize_repo_rel(raw_path)
    if not rel_path:
        raise ValueError("path is empty")
    path = Path(rel_path)
    if path.is_absolute():
        raise ValueError(f"path must be repo-local: {raw_path}")
    resolved = (repo_root.resolve() / path).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise ValueError(f"path escapes repo root: {raw_path}") from exc
    return resolved


def recovery_required_outputs(request: Dict[str, Any]) -> list[str]:
    idempotent = idempotent_output_allowlist(request)
    return [path for path in normalized_required_outputs(request) if path not in idempotent]


def _blob_filename(rel_path: str) -> str:
    digest = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:24]
    name = Path(rel_path).name or "output"
    return f"{digest}-{name}.baseline"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _signature_identity(signature: Dict[str, Any] | None) -> tuple[Any, ...]:
    if not isinstance(signature, dict) or signature.get("present") is not True:
        return (False, None, None, None)
    return (
        True,
        signature.get("kind"),
        signature.get("sha256"),
        signature.get("size"),
    )


def _expected_action_for_baseline(baseline: Dict[str, Any]) -> str:
    if baseline.get("present") is not True:
        return "delete_created"
    return "restore_baseline"


def _current_signature_map(payload: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    raw_outputs = payload.get("required_outputs")
    if not isinstance(raw_outputs, dict):
        return {}
    mapped: Dict[str, Dict[str, Any]] = {}
    for rel_path, entry in raw_outputs.items():
        if not isinstance(rel_path, str) or not isinstance(entry, dict):
            continue
        after = entry.get("after")
        if isinstance(after, dict):
            mapped[normalize_repo_rel(rel_path)] = after
    return mapped


def _baseline_signature_map(payload: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    raw_outputs = payload.get("required_outputs")
    if not isinstance(raw_outputs, dict):
        raw_outputs = payload.get("signatures")
    if not isinstance(raw_outputs, dict):
        return {}
    mapped: Dict[str, Dict[str, Any]] = {}
    for rel_path, signature in raw_outputs.items():
        if not isinstance(rel_path, str) or not isinstance(signature, dict):
            continue
        mapped[normalize_repo_rel(rel_path)] = signature
    return mapped


def load_current_signatures(repo_root: Path, raw_ref: str) -> Dict[str, Any]:
    path = resolve_repo_local(repo_root, raw_ref)
    if not path.is_file():
        raise ValueError(f"current signatures artifact does not exist: {raw_ref}")
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("current signatures artifact must be a JSON object")
    return payload


def create_recovery_manifest(
    repo_root: Path,
    request: Dict[str, Any],
    *,
    run_dir: Path,
    baseline_signatures: Dict[str, Dict[str, Any]],
    baseline_signatures_ref: str,
) -> Dict[str, Any]:
    blob_dir = run_dir / "recovery_blobs"
    outputs: Dict[str, Dict[str, Any]] = {}

    for rel_path in recovery_required_outputs(request):
        signature = baseline_signatures.get(rel_path) or file_signature(repo_root, rel_path)
        entry: Dict[str, Any] = {
            "path": rel_path,
            "baseline": signature,
            "baseline_blob_ref": None,
            "planned_action": "delete_created",
            "rollback_available": True,
            "reason": "baseline_absent",
        }

        if signature.get("present") is True:
            entry["planned_action"] = "restore_baseline"
            entry["rollback_available"] = False
            entry["reason"] = "baseline_unavailable"
            if signature.get("kind") == "file":
                source = resolve_repo_local(repo_root, rel_path)
                size = signature.get("size")
                if isinstance(size, int) and size <= MAX_RECOVERY_BLOB_BYTES and source.is_file() and not source.is_symlink():
                    blob_path = blob_dir / _blob_filename(rel_path)
                    blob_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, blob_path)
                    entry["baseline_blob_ref"] = repo_relative(blob_path, repo_root)
                    entry["rollback_available"] = True
                    entry["reason"] = "baseline_blob_captured"
                elif isinstance(size, int) and size > MAX_RECOVERY_BLOB_BYTES:
                    entry["reason"] = "baseline_too_large"
                else:
                    entry["reason"] = "baseline_not_regular_file"
            else:
                entry["reason"] = f"unsupported_baseline_kind:{signature.get('kind')}"

        outputs[rel_path] = entry

    return {
        "schema_version": RECOVERY_MANIFEST_SCHEMA_VERSION,
        "created_at": utc_now(),
        "work_ref": request.get("work_ref"),
        "dispatch_ref": request.get("dispatch_ref"),
        "attempt_number": request.get("attempt_number"),
        "plan_version": request.get("plan_version"),
        "required_outputs": recovery_required_outputs(request),
        "idempotent_outputs_skipped": sorted(idempotent_output_allowlist(request)),
        "baseline_signatures_ref": baseline_signatures_ref,
        "outputs": outputs,
    }


def write_recovery_manifest(
    repo_root: Path,
    request: Dict[str, Any],
    *,
    run_dir: Path,
    baseline_signatures: Dict[str, Dict[str, Any]],
    baseline_signatures_ref: str,
) -> tuple[Dict[str, Any], str]:
    baseline_path = resolve_repo_local(repo_root, baseline_signatures_ref)
    if not baseline_path.exists():
        write_json(
            baseline_path,
            {
                "schema_version": "corgi.recovery_baseline_signatures.v1",
                "created_at": utc_now(),
                "dispatch_ref": request.get("dispatch_ref"),
                "required_outputs": baseline_signatures,
            },
        )
    manifest = create_recovery_manifest(
        repo_root,
        request,
        run_dir=run_dir,
        baseline_signatures=baseline_signatures,
        baseline_signatures_ref=baseline_signatures_ref,
    )
    manifest_path = run_dir / "recovery_manifest.json"
    write_json(manifest_path, manifest)
    return manifest, repo_relative(manifest_path, repo_root)


def load_recovery_manifest(repo_root: Path, manifest_ref: str) -> Dict[str, Any]:
    path = resolve_repo_local(repo_root, manifest_ref)
    if not path.is_file():
        raise ValueError(f"recovery manifest does not exist: {manifest_ref}")
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("recovery manifest must be a JSON object")
    return payload


def validate_recovery_manifest(
    repo_root: Path,
    request: Dict[str, Any],
    manifest: Dict[str, Any],
    *,
    current_signatures: Dict[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    if manifest.get("schema_version") != RECOVERY_MANIFEST_SCHEMA_VERSION:
        failures.append(
            f"recovery_manifest schema_version must be {RECOVERY_MANIFEST_SCHEMA_VERSION}"
        )
    expected_dispatch_ref = (
        request.get("recovery_of_dispatch_ref")
        or request.get("revision_of_dispatch_ref")
        or request.get("dispatch_ref")
    )
    expected_by_field = {
        "work_ref": request.get("work_ref"),
        "dispatch_ref": expected_dispatch_ref,
        "attempt_number": request.get("attempt_number"),
        "plan_version": request.get("plan_version"),
    }
    for field, expected in expected_by_field.items():
        if expected is not None and manifest.get(field) != expected:
            failures.append(f"recovery_manifest {field} mismatch")

    if request.get("parallel_set_ref") and not isinstance(request.get("overlap_isolation"), dict):
        failures.append("recovery is disabled for parallel dispatches without overlap isolation")

    expected_outputs = recovery_required_outputs(request)
    expected_set = set(expected_outputs)
    current_by_path = _current_signature_map(current_signatures)
    baseline_ref = manifest.get("baseline_signatures_ref")
    baseline_by_path: Dict[str, Dict[str, Any]] = {}
    if isinstance(baseline_ref, str) and baseline_ref.strip():
        try:
            baseline_by_path = _baseline_signature_map(load_json(resolve_repo_local(repo_root, baseline_ref)))
        except Exception as exc:
            failures.append(f"recovery_manifest baseline signatures could not be read: {exc}")
    else:
        failures.append("recovery_manifest baseline_signatures_ref must be a non-empty repo-local path")

    manifest_outputs = manifest.get("outputs")
    if not isinstance(manifest_outputs, dict):
        failures.append("recovery_manifest outputs must be an object")
        return failures

    declared = manifest.get("required_outputs")
    if declared != expected_outputs:
        failures.append("recovery_manifest required_outputs mismatch")

    for rel_path in expected_outputs:
        if rel_path not in manifest_outputs:
            failures.append(f"recovery_manifest missing required output: {rel_path}")

    for raw_path, entry in manifest_outputs.items():
        if not isinstance(raw_path, str) or normalize_repo_rel(raw_path) not in expected_set:
            failures.append(f"recovery_manifest path is not an allowed recovery output: {raw_path}")
            continue
        if not isinstance(entry, dict):
            failures.append(f"recovery_manifest output entry must be an object: {raw_path}")
            continue
        try:
            resolve_repo_local(repo_root, raw_path)
        except ValueError as exc:
            failures.append(f"recovery_manifest invalid output path {raw_path}: {exc}")
        action = entry.get("planned_action")
        if action not in {"delete_created", "restore_baseline", "noop"}:
            failures.append(f"recovery_manifest invalid planned action for {raw_path}")
        baseline = entry.get("baseline")
        if not isinstance(baseline, dict):
            failures.append(f"recovery_manifest missing baseline signature for {raw_path}")
            baseline = {}
        expected_baseline = baseline_by_path.get(normalize_repo_rel(raw_path))
        if expected_baseline is None:
            failures.append(f"recovery_manifest baseline signatures missing required output: {raw_path}")
        elif _signature_identity(baseline) != _signature_identity(expected_baseline):
            failures.append(f"recovery_manifest baseline signature mismatch for {raw_path}")
        expected_action = _expected_action_for_baseline(baseline)
        if action != expected_action:
            failures.append(
                f"recovery_manifest planned action for {raw_path} must be {expected_action}"
            )
        if action == "noop":
            failures.append(f"recovery_manifest noop is not allowed for {raw_path}")
        if action == "restore_baseline":
            if baseline.get("kind") != "file":
                failures.append(f"recovery_manifest baseline for {raw_path} must be a file")
            blob_ref = entry.get("baseline_blob_ref")
            if not isinstance(blob_ref, str) or not blob_ref.strip():
                failures.append(f"recovery_manifest missing baseline blob for {raw_path}")
            else:
                try:
                    blob_path = resolve_repo_local(repo_root, blob_ref)
                except ValueError as exc:
                    failures.append(f"recovery_manifest invalid baseline blob for {raw_path}: {exc}")
                else:
                    if not blob_path.is_file():
                        failures.append(f"recovery_manifest baseline blob missing for {raw_path}")
                    else:
                        expected_sha = baseline.get("sha256")
                        expected_size = baseline.get("size")
                        actual_size = blob_path.stat().st_size
                        actual_sha = _sha256_file(blob_path)
                        if actual_sha != expected_sha or actual_size != expected_size:
                            failures.append(
                                f"recovery_manifest baseline blob does not match baseline for {raw_path}"
                            )
        if entry.get("rollback_available") is False and action != "noop":
            failures.append(f"recovery_manifest rollback unavailable for {raw_path}")
        current_expected = current_by_path.get(normalize_repo_rel(raw_path))
        if current_expected is not None:
            current_actual = file_signature(repo_root, raw_path)
            if _signature_identity(current_actual) != _signature_identity(current_expected):
                failures.append(
                    f"recovery_manifest current output changed since failed attempt: {raw_path}"
                )

    return failures


def apply_recovery_manifest(
    repo_root: Path,
    manifest: Dict[str, Any],
    *,
    current_signatures: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        return {
            "schema_version": RECOVERY_RESULT_SCHEMA_VERSION,
            "created_at": utc_now(),
            "verified": False,
            "summary": {"deleted": 0, "restored": 0, "skipped": 0, "blocked": 1},
            "outputs": {},
            "blockers": ["recovery_manifest outputs must be an object"],
        }

    result_outputs: Dict[str, Dict[str, Any]] = {}
    blockers: list[str] = []
    summary = {"deleted": 0, "restored": 0, "skipped": 0, "blocked": 0}
    current_by_path = _current_signature_map(current_signatures)

    for rel_path, entry in outputs.items():
        if not isinstance(entry, dict):
            blockers.append(f"invalid_recovery_entry:{rel_path}")
            summary["blocked"] += 1
            continue
        action = entry.get("planned_action")
        before = file_signature(repo_root, rel_path)
        status = "skipped"
        try:
            current_expected = current_by_path.get(normalize_repo_rel(rel_path))
            if current_expected is not None and _signature_identity(before) != _signature_identity(current_expected):
                raise ValueError("current output changed since failed attempt")
            target = resolve_repo_local(repo_root, rel_path)
            if action == "delete_created":
                if target.exists():
                    if target.is_file() or target.is_symlink():
                        target.unlink()
                    elif target.is_dir():
                        target.rmdir()
                    else:
                        raise ValueError("target is not a removable file or empty directory")
                status = "deleted"
                summary["deleted"] += 1
            elif action == "restore_baseline":
                blob_ref = entry.get("baseline_blob_ref")
                if not isinstance(blob_ref, str) or not blob_ref.strip():
                    raise ValueError("missing baseline blob")
                blob_path = resolve_repo_local(repo_root, blob_ref)
                if not blob_path.is_file():
                    raise ValueError("baseline blob missing")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(blob_path, target)
                status = "restored"
                summary["restored"] += 1
            elif action == "noop":
                status = "skipped"
                summary["skipped"] += 1
            else:
                raise ValueError(f"unsupported action: {action}")
        except Exception as exc:
            status = "blocked"
            summary["blocked"] += 1
            blockers.append(f"recovery_failed:{rel_path}:{exc}")
        after = file_signature(repo_root, rel_path)
        result_outputs[rel_path] = {
            "action": action,
            "status": status,
            "before": before,
            "after": after,
        }

    return {
        "schema_version": RECOVERY_RESULT_SCHEMA_VERSION,
        "created_at": utc_now(),
        "work_ref": manifest.get("work_ref"),
        "dispatch_ref": manifest.get("dispatch_ref"),
        "attempt_number": manifest.get("attempt_number"),
        "plan_version": manifest.get("plan_version"),
        "verified": not blockers,
        "summary": summary,
        "outputs": result_outputs,
        "blockers": blockers,
    }
