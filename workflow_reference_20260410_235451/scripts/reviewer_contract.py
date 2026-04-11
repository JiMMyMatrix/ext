#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class ReviewerContractViolation(RuntimeError):
    """Raised when reviewer execution crosses the advisory-only boundary."""


def relative_path(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root))


def resolve_review_artifact_path(repo_root: Path, dispatch_ref: str, configured: Optional[str]) -> Path:
    if isinstance(configured, str) and configured.strip():
        rel_path = Path(configured.strip())
    else:
        rel_path = Path(".agent") / "reviews" / Path(dispatch_ref) / "review.json"
    if rel_path.is_absolute():
        raise ReviewerContractViolation("reviewer_contract_violation:review_artifact_path must be repo-local")
    normalized = Path(str(rel_path))
    if normalized.parts[:2] != (".agent", "reviews"):
        raise ReviewerContractViolation(
            "reviewer_contract_violation:review_artifact_path must stay under .agent/reviews/"
        )
    if normalized.name != "review.json":
        raise ReviewerContractViolation(
            "reviewer_contract_violation:review_artifact_path must end with review.json"
        )
    return repo_root / normalized


def _read_file_bytes(path: Path) -> Optional[bytes]:
    if not path.exists() or not path.is_file():
        return None
    return path.read_bytes()


def _restore_path(repo_root: Path, path: Path, snapshot: Optional[bytes]) -> None:
    if snapshot is None:
        if (repo_root / ".git").exists():
            rel_path = relative_path(path, repo_root)
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", rel_path],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
            )
            if tracked.returncode == 0:
                blob = subprocess.run(
                    ["git", "show", f"HEAD:{rel_path}"],
                    cwd=str(repo_root),
                    check=True,
                    capture_output=True,
                ).stdout
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(blob)
                return
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(snapshot)


def _git_visible_worktree_paths(repo_root: Path) -> list[str]:
    if not (repo_root / ".git").exists():
        return []
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--ignored=no"],
        cwd=str(repo_root),
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[str] = []
    for raw_line in proc.stdout.splitlines():
        if not raw_line:
            continue
        path_text = raw_line[3:]
        if " -> " in path_text:
            _old, path_text = path_text.split(" -> ", 1)
        if path_text:
            paths.append(path_text)
    return paths


def _snapshot_paths(repo_root: Path, rel_paths: Iterable[str]) -> Dict[str, Optional[bytes]]:
    return {rel_path: _read_file_bytes(repo_root / rel_path) for rel_path in sorted(set(rel_paths))}


def _dispatch_file_rel_paths(repo_root: Path, dispatch_dir: Path) -> list[str]:
    if not dispatch_dir.exists():
        return []
    return [relative_path(path, repo_root) for path in dispatch_dir.rglob("*") if path.is_file()]


def capture_reviewer_guard_snapshot(repo_root: Path, dispatch_dir: Path) -> Dict[str, Dict[str, Optional[bytes]]]:
    return {
        "dispatch_files": _snapshot_paths(repo_root, _dispatch_file_rel_paths(repo_root, dispatch_dir)),
        "visible_worktree": _snapshot_paths(repo_root, _git_visible_worktree_paths(repo_root)),
    }


def enforce_reviewer_guard(
    repo_root: Path,
    dispatch_dir: Path,
    review_path: Path,
    snapshot: Dict[str, Dict[str, Optional[bytes]]],
) -> None:
    allowed_rel = relative_path(review_path, repo_root)
    dispatch_before = snapshot["dispatch_files"]
    dispatch_after_paths = _dispatch_file_rel_paths(repo_root, dispatch_dir)
    visible_before = snapshot["visible_worktree"]
    visible_after_paths = _git_visible_worktree_paths(repo_root)

    changed_paths: dict[str, Optional[bytes]] = {}

    for rel_path in sorted(set(dispatch_before) | set(dispatch_after_paths)):
        if rel_path == allowed_rel:
            continue
        current = _read_file_bytes(repo_root / rel_path)
        if current != dispatch_before.get(rel_path):
            changed_paths[rel_path] = dispatch_before.get(rel_path)

    for rel_path in sorted(set(visible_before) | set(visible_after_paths)):
        if rel_path == allowed_rel:
            continue
        current = _read_file_bytes(repo_root / rel_path)
        if current != visible_before.get(rel_path):
            changed_paths.setdefault(rel_path, visible_before.get(rel_path))

    if not changed_paths:
        return

    for rel_path, before_bytes in changed_paths.items():
        _restore_path(repo_root, repo_root / rel_path, before_bytes)

    first_rel = sorted(changed_paths)[0]
    raise ReviewerContractViolation(f"reviewer_contract_violation:{first_rel}")
