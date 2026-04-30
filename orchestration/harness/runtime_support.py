#!/usr/bin/env python3
"""Minimal harness runtime helpers for stable eval and scope enforcement."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVED_PYTHON = Path(
    os.environ.get("ORCHESTRATION_APPROVED_PYTHON") or (REPO_ROOT / "abba/.venv/bin/python")
)

FAILURE_INVALID_RUNTIME_ENVIRONMENT = "invalid_runtime_environment"
FAILURE_SCOPE_VIOLATION = "scope_violation"
FAILURE_UNDECLARED_UNTRACKED_OUTPUT = "undeclared_untracked_output"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def relative_path(path: Path, repo_root: Path = REPO_ROOT) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")


def ensure_approved_python_binary() -> Path:
    if not APPROVED_PYTHON.exists():
        raise SystemExit(
            f"{FAILURE_INVALID_RUNTIME_ENVIRONMENT}: expected approved interpreter at "
            f"{relative_path(APPROVED_PYTHON)}"
        )
    return APPROVED_PYTHON


def ensure_running_with_approved_python(script_name: str) -> Path:
    approved = ensure_approved_python_binary()
    current = Path(sys.executable).absolute()
    if current.resolve() != approved.resolve():
        raise SystemExit(
            f"{FAILURE_INVALID_RUNTIME_ENVIRONMENT}: {script_name} must run under "
            f"{relative_path(approved)} (current={current})"
        )
    return approved


@lru_cache(maxsize=1)
def ensure_eval_runtime_ready() -> Path:
    approved = ensure_approved_python_binary()
    probe = subprocess.run(
        [str(approved), "-c", "import numpy, cv2"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        detail = next(
            (
                line.strip()
                for line in (probe.stderr.splitlines() + probe.stdout.splitlines())
                if line.strip()
            ),
            "numpy/cv2 probe failed",
        )
        raise SystemExit(
            f"{FAILURE_INVALID_RUNTIME_ENVIRONMENT}: approved interpreter failed numpy/cv2 probe: {detail}"
        )
    return approved


def _safe_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "run"


def create_eval_session_dir(flow: str, run_ref: str) -> Path:
    stamp = utc_stamp().replace("-", "").replace(":", "")
    session_dir = REPO_ROOT / ".agent" / "runs" / "evals" / _safe_slug(flow) / f"{stamp}__{_safe_slug(run_ref)}"
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_dir


def latest_eval_report(run_root: Path) -> Path:
    candidates = sorted(run_root.glob("eval_*/report.json"))
    if not candidates:
        raise FileNotFoundError(f"no evaluation report produced under {run_root}")
    return candidates[-1]


def run_eval_accuracy(video_path: Path, labels_path: Path, report_dir: Path) -> Path:
    python_bin = ensure_eval_runtime_ready()
    cmd = [
        str(python_bin),
        str(REPO_ROOT / "tools/eval_accuracy.py"),
        "--video",
        str(video_path),
        "--labels-json",
        str(labels_path),
        "--mode",
        "pipeline",
        "--compute-backend",
        "cpu",
        "--pipeline-batch-size",
        "8",
        "--report-dir",
        str(report_dir),
    ]
    subprocess.run(cmd, check=True, cwd=str(REPO_ROOT))
    return latest_eval_report(report_dir)


def git_status_snapshot(repo_root: Path = REPO_ROOT) -> dict[str, str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        check=True,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    snapshot: dict[str, str] = {}
    for raw_line in proc.stdout.splitlines():
        if not raw_line:
            continue
        status = raw_line[:2]
        path = raw_line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        snapshot[path] = status
    return snapshot


def _normalize_paths(paths: Iterable[str]) -> set[str]:
    normalized: set[str] = set()
    for path in paths:
        value = path.strip().lstrip("./")
        if value:
            normalized.add(value.rstrip("/"))
    return normalized


def _path_is_within(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def path_matches_declared(path: str, declared_files: Iterable[str]) -> bool:
    normalized_path = path.lstrip("./")
    for declared in _normalize_paths(declared_files):
        if _path_is_within(normalized_path, declared):
            return True
    return False


def default_scope_ignored_prefixes(dispatch_ref: str | None = None, run_ref: str | None = None) -> list[str]:
    ignored = [".agent/runs/evals"]
    if dispatch_ref:
        ignored.append(relative_path(REPO_ROOT / ".agent" / "dispatches" / Path(dispatch_ref)))
    if run_ref:
        ignored.append(relative_path(REPO_ROOT / ".agent" / "runs" / Path(run_ref)))
    return ignored


def scope_audit(
    before: dict[str, str],
    after: dict[str, str],
    declared_files: Iterable[str],
    ignored_prefixes: Iterable[str] = (),
) -> dict[str, Any]:
    changed_paths = sorted(
        path for path in (set(before) | set(after)) if before.get(path) != after.get(path)
    )
    normalized_ignored = _normalize_paths(ignored_prefixes)
    tracked_changed: list[str] = []
    untracked_created: list[str] = []
    undeclared_tracked: list[str] = []
    undeclared_untracked: list[str] = []

    for path in changed_paths:
        clean_path = path.lstrip("./")
        if any(_path_is_within(clean_path, prefix) for prefix in normalized_ignored):
            continue
        is_untracked = after.get(path) == "??"
        if is_untracked:
            untracked_created.append(clean_path)
        else:
            tracked_changed.append(clean_path)
        if not path_matches_declared(clean_path, declared_files):
            if is_untracked:
                undeclared_untracked.append(clean_path)
            else:
                undeclared_tracked.append(clean_path)

    return {
        "tracked_changed": tracked_changed,
        "untracked_created": untracked_created,
        "undeclared_tracked": undeclared_tracked,
        "undeclared_untracked": undeclared_untracked,
        "scope_ok": not undeclared_tracked and not undeclared_untracked,
    }
