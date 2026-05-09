from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, Iterable


SCHEMA_VERSION = "corgi.executor-authorship.v1"
VALID_CLASSIFICATIONS = {"created", "mutated", "unchanged", "missing"}


def authorship_config(request: Dict[str, Any]) -> Dict[str, Any]:
    raw = request.get("authorship_evidence")
    if isinstance(raw, dict):
        return raw
    if request.get("authorship_evidence_required") is True:
        return {"required": True, "idempotent_output_allowed": []}
    return {"required": False, "idempotent_output_allowed": []}


def authorship_evidence_required(request: Dict[str, Any]) -> bool:
    return authorship_config(request).get("required") is True


def idempotent_output_allowlist(request: Dict[str, Any]) -> set[str]:
    config = authorship_config(request)
    raw = config.get("idempotent_output_allowed")
    if not isinstance(raw, list):
        return set()
    return {item.strip().lstrip("./") for item in raw if isinstance(item, str) and item.strip()}


def normalized_required_outputs(request: Dict[str, Any]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for item in request.get("required_outputs", []):
        if not isinstance(item, str):
            continue
        ref = item.strip().lstrip("./")
        if not ref or ref in seen:
            continue
        refs.append(ref)
        seen.add(ref)
    return refs


def _resolve_repo_local(repo_root: Path, rel_path: str) -> Path:
    raw = Path(rel_path)
    if raw.is_absolute():
        raise SystemExit(f"authorship evidence path must be repo-local: {rel_path}")
    resolved = (repo_root / raw).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise SystemExit(f"authorship evidence path escapes repo root: {rel_path}") from exc
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_signature(repo_root: Path, rel_path: str) -> Dict[str, Any]:
    normalized = rel_path.strip().lstrip("./")
    path = _resolve_repo_local(repo_root, normalized)
    if not path.exists():
        return {
            "path": normalized,
            "present": False,
            "kind": "missing",
            "sha256": None,
            "size": None,
            "mtime_ns": None,
        }

    stat = path.stat()
    if path.is_file():
        kind = "file"
        sha256 = _sha256_file(path)
        size = stat.st_size
    elif path.is_dir():
        kind = "directory"
        sha256 = None
        size = None
    else:
        kind = "other"
        sha256 = None
        size = None
    return {
        "path": normalized,
        "present": True,
        "kind": kind,
        "sha256": sha256,
        "size": size,
        "mtime_ns": stat.st_mtime_ns,
    }


def capture_signatures(repo_root: Path, required_outputs: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    return {
        rel_path: file_signature(repo_root, rel_path)
        for rel_path in normalized_required_outputs({"required_outputs": list(required_outputs)})
    }


def _signature_identity(signature: Dict[str, Any]) -> tuple[Any, ...]:
    if signature.get("present") is not True:
        return (False, None, None, None)
    return (
        True,
        signature.get("kind"),
        signature.get("sha256"),
        signature.get("size"),
    )


def _path_dirty_at_claim(path: str, baseline_status: Dict[str, str]) -> bool:
    normalized = path.strip().lstrip("./")
    for status_path in baseline_status:
        clean_status_path = status_path.strip().lstrip("./")
        if (
            clean_status_path == normalized
            or clean_status_path.startswith(normalized + "/")
            or normalized.startswith(clean_status_path + "/")
        ):
            return True
    return False


def compare_signatures(
    before: Dict[str, Dict[str, Any]],
    after: Dict[str, Dict[str, Any]],
    *,
    baseline_status: Dict[str, str] | None = None,
    idempotent_allowed: set[str] | None = None,
) -> Dict[str, Any]:
    baseline_status = baseline_status or {}
    idempotent_allowed = idempotent_allowed or set()
    output_entries: Dict[str, Any] = {}
    blockers: list[str] = []
    summary = {"created": 0, "mutated": 0, "unchanged": 0, "missing": 0}

    for rel_path in sorted(set(before) | set(after)):
        before_sig = before.get(rel_path) or {
            "path": rel_path,
            "present": False,
            "kind": "missing",
            "sha256": None,
            "size": None,
            "mtime_ns": None,
        }
        after_sig = after.get(rel_path) or before_sig
        before_present = before_sig.get("present") is True
        after_present = after_sig.get("present") is True
        if not after_present:
            classification = "missing"
        elif not before_present:
            classification = "created"
        elif _signature_identity(before_sig) != _signature_identity(after_sig):
            classification = "mutated"
        else:
            classification = "unchanged"

        dirty_at_claim = _path_dirty_at_claim(rel_path, baseline_status)
        idempotent_ok = rel_path in idempotent_allowed
        if classification == "missing":
            blockers.append(f"missing_required_output:{rel_path}")
        if classification == "unchanged" and not idempotent_ok:
            blockers.append(f"unchanged_required_output:{rel_path}")
        if dirty_at_claim and classification not in {"created", "mutated"}:
            blockers.append(f"dirty_at_claim:{rel_path}")

        summary[classification] += 1
        output_entries[rel_path] = {
            "before": before_sig,
            "after": after_sig,
            "classification": classification,
            "dirty_at_claim": dirty_at_claim,
            "idempotent_allowed": idempotent_ok,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "required_outputs": output_entries,
        "summary": summary,
        "blockers": blockers,
        "verified": not blockers,
    }


def build_evidence_payload(
    repo_root: Path,
    request: Dict[str, Any],
    before: Dict[str, Dict[str, Any]],
    after: Dict[str, Dict[str, Any]],
    *,
    baseline_status: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    comparison = compare_signatures(
        before,
        after,
        baseline_status=baseline_status,
        idempotent_allowed=idempotent_output_allowlist(request),
    )
    return {
        **comparison,
        "repo_root": str(repo_root),
        "idempotent_output_allowed": sorted(idempotent_output_allowlist(request)),
    }
