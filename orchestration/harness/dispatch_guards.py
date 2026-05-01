from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any, Dict, List

from orchestration.harness.paths import resolve_agent_root, script_ref


def command_argv(spec: Any) -> List[str]:
    if isinstance(spec, str):
        return shlex.split(spec)
    if not isinstance(spec, dict):
        return []
    argv = spec.get("argv")
    if isinstance(argv, str):
        return shlex.split(argv)
    if isinstance(argv, list) and all(isinstance(item, str) and item for item in argv):
        return argv
    return []


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def artifact_only_executor_readout_request(
    repo_root: Path,
    request: Dict[str, Any],
    *,
    result: Dict[str, Any] | None = None,
    state: Dict[str, Any] | None = None,
    run_dir: Path | None = None,
    produced_refs: List[str] | None = None,
) -> bool:
    execution_mode = request.get("execution_mode") or "manual_artifact_report"
    if execution_mode != "command_chain":
        return False

    payload = request.get("execution_payload")
    if not isinstance(payload, dict):
        return False
    notes = payload.get("notes")
    if not isinstance(notes, list) or "artifact_only_executor_readout" not in notes:
        return False
    commands = payload.get("commands")
    if not isinstance(commands, list) or len(commands) != 1:
        return False
    if script_ref("executor_write_readout.py", repo_root) not in command_argv(commands[0]):
        return False

    executor_run = request.get("executor_run")
    if not isinstance(executor_run, dict):
        return False
    run_ref = executor_run.get("run_ref")
    if not isinstance(run_ref, str) or not run_ref.strip():
        return False

    if result is not None:
        if result.get("status") != "completed" or result.get("blocker"):
            return False
        if result.get("scope_respected") is not True or result.get("runtime_behavior_changed") is not False:
            return False
        executor_run_refs = result.get("executor_run_refs")
        if not isinstance(executor_run_refs, list) or run_ref not in executor_run_refs:
            return False

    if state is not None and (state.get("status") != "completed" or state.get("run_ref") != run_ref):
        return False

    required_outputs = request.get("required_outputs")
    if not isinstance(required_outputs, list) or not required_outputs:
        return False

    produced_refs = list(produced_refs or [])
    if result is not None:
        written_or_updated = result.get("written_or_updated")
        if not isinstance(written_or_updated, list) or not written_or_updated:
            return False
        produced_refs.extend(written_or_updated)

    all_refs = [
        ref
        for ref in [*produced_refs, *required_outputs]
        if isinstance(ref, str) and ref.strip()
    ]
    if not all_refs:
        return False

    checked_run_dir = run_dir or resolve_agent_root(repo_root) / "runs" / Path(run_ref)
    return all(path_is_inside(repo_root / ref, checked_run_dir) for ref in all_refs)
