#!/usr/bin/env python3
"""Run a scratch-only live Codex Executor turn for the practical project exercise."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def tail_text(value: str | bytes | None, limit: int = 4000) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value[-limit:]


def repo_local_path(repo_root: Path, value: str) -> Path:
    rel = Path(value)
    if rel.is_absolute() or ".." in rel.parts:
        raise SystemExit(f"path is not repo-local: {value}")
    return repo_root / rel


def signature(repo_root: Path, rel_path: str) -> dict[str, Any]:
    path = repo_local_path(repo_root, rel_path)
    if not path.exists() or not path.is_file():
        return {"present": False}
    data = path.read_bytes()
    return {
        "present": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


def changed_files(repo_root: Path, before: dict[str, dict[str, Any]], targets: list[str]) -> list[dict[str, str]]:
    changed: list[dict[str, str]] = []
    for rel_path in targets:
        previous = before.get(rel_path, {"present": False})
        current = signature(repo_root, rel_path)
        if not previous.get("present") and current.get("present"):
            changed.append({"path": rel_path, "classification": "created"})
        elif previous.get("present") and current.get("present") and previous.get("sha256") != current.get("sha256"):
            changed.append({"path": rel_path, "classification": "mutated"})
    return changed


def build_prompt(
    *,
    repo_root: Path,
    dispatch_ref: str,
    objective: str,
    accepted_intake_ref: str,
    target_files: list[str],
    required_outputs: list[str],
) -> str:
    accepted = read_json(repo_root / accepted_intake_ref)
    existing = [rel for rel in target_files if (repo_root / rel).exists()]
    missing = [rel for rel in target_files if rel not in existing]
    return "\n".join(
        [
            "You are Corgi Executor, not Governor and not Reviewer.",
            "",
            "Mission:",
            objective.strip(),
            "",
            "Authority and safety:",
            "- You may write only inside the current scratch workspace.",
            "- Do not edit .agent, .git, orchestration files, or hidden runtime artifacts.",
            "- Do not use git commit, push, merge, rebase, reset, or destructive shell commands.",
            "- Make real project-file changes. Do not satisfy this by writing prose-only readouts.",
            "- Keep the app dependency-free and local-first unless the existing project already uses dependencies.",
            "",
            "Declared files you may create or edit:",
            *[f"- {rel}" for rel in target_files],
            "",
            "Outputs that must exist and be newly created or mutated for this dispatch:",
            *[f"- {rel}" for rel in required_outputs],
            "",
            "Current existing declared files:",
            *([f"- {rel}" for rel in existing] if existing else ["- none"]),
            "",
            "Declared files not yet present:",
            *([f"- {rel}" for rel in missing] if missing else ["- none"]),
            "",
            "Accepted intake context:",
            json.dumps(
                {
                    "accepted_intake_ref": accepted_intake_ref,
                    "goal": accepted.get("goal"),
                    "task": accepted.get("task"),
                    "goal_ref": accepted.get("goal_ref"),
                    "goal_step_ref": accepted.get("goal_step_ref"),
                    "goal_step_index": accepted.get("goal_step_index"),
                    "accepted_summary": accepted.get("accepted_summary"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            "",
            f"Dispatch ref: {dispatch_ref}",
            "",
            "When finished, briefly summarize the changed files and the user-visible behavior added.",
        ]
    )


def assert_scratch_only(repo_root: Path) -> None:
    if os.environ.get("ORCHESTRATION_TARGET_WORKSPACE_MODE") != "scratch":
        raise SystemExit("live Executor is allowed only for scratch test workspaces")
    source_root = os.environ.get("ORCHESTRATION_SOURCE_ROOT")
    if source_root and Path(source_root).resolve() == repo_root:
        raise SystemExit("live Executor target repo must not be the Corgi development repo")
    if not str(repo_root).endswith("scratch-workspace") and "scratch-workspaces" not in str(repo_root):
        raise SystemExit(f"live Executor target does not look like a scratch workspace: {repo_root}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live Codex Executor in an isolated scratch workspace.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument("--accepted-intake", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--last-message", required=True)
    parser.add_argument("--target-file", action="append", default=[])
    parser.add_argument("--required-output", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("CORGI_LIVE_EXECUTOR_TIMEOUT_SECONDS", "900")))
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    assert_scratch_only(repo_root)

    target_files = sorted(dict.fromkeys(args.target_file))
    required_outputs = sorted(dict.fromkeys(args.required_output))
    if not target_files or not required_outputs:
        raise SystemExit("live Executor requires target files and required outputs")
    for rel_path in [*target_files, *required_outputs]:
        repo_local_path(repo_root, rel_path)
    undeclared_required = sorted(set(required_outputs) - set(target_files))
    if undeclared_required:
        raise SystemExit("required outputs must be target files: " + ", ".join(undeclared_required))

    codex_bin = os.environ.get("CORGI_CODEX_BIN") or shutil.which("codex")
    if not codex_bin:
        raise SystemExit("codex executable not found for live Executor runtime")

    manifest_path = repo_local_path(repo_root, args.manifest)
    last_message_path = repo_local_path(repo_root, args.last_message)
    last_message_path.parent.mkdir(parents=True, exist_ok=True)
    before = {rel: signature(repo_root, rel) for rel in target_files}
    prompt = build_prompt(
        repo_root=repo_root,
        dispatch_ref=args.dispatch_ref,
        objective=args.objective,
        accepted_intake_ref=args.accepted_intake,
        target_files=target_files,
        required_outputs=required_outputs,
    )
    command = [
        codex_bin,
        "exec",
        "--cd",
        str(repo_root),
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--ephemeral",
        "--output-last-message",
        str(last_message_path),
        prompt,
    ]
    timed_out = False
    timeout_stdout = ""
    timeout_stderr = ""
    try:
        proc = subprocess.run(
            command,
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            timeout=args.timeout_seconds,
        )
        returncode = proc.returncode
        stdout_tail = tail_text(proc.stdout)
        stderr_tail = tail_text(proc.stderr)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        timeout_stdout = tail_text(exc.stdout)
        timeout_stderr = tail_text(exc.stderr)
        returncode = 124
        stdout_tail = timeout_stdout
        stderr_tail = timeout_stderr
    after = {rel: signature(repo_root, rel) for rel in target_files}
    changes = changed_files(repo_root, before, target_files)
    manifest = {
        "schema_version": "corgi.live-executor.v1",
        "created_at": utc_now(),
        "dispatch_ref": args.dispatch_ref,
        "runtime": "codex_exec_live",
        "repo_root": str(repo_root),
        "required_outputs": required_outputs,
        "target_files": target_files,
        "changed_files": changes,
        "codex": {
            "returncode": returncode,
            "timed_out": timed_out,
            "timeout_seconds": args.timeout_seconds,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "last_message_ref": args.last_message,
        },
    }
    write_json(manifest_path, manifest)
    if timed_out:
        raise SystemExit(f"live Executor codex turn timed out after {args.timeout_seconds}s; see {args.manifest}")
    if returncode != 0:
        raise SystemExit(f"live Executor codex turn failed with exit code {returncode}; see {args.manifest}")

    changed_required = {item["path"] for item in changes}
    missing_changed_required = [rel for rel in required_outputs if rel not in changed_required]
    if missing_changed_required:
        raise SystemExit(
            "live Executor did not create or mutate required outputs: "
            + ", ".join(missing_changed_required)
        )
    print(args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
