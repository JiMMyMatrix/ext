from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from orchestration.harness.paths import (
    actor_config_ref,
    contract_ref,
    prompt_ref,
    repo_relative,
    resolve_agent_root,
    script_ref,
    utc_now,
    write_json,
    write_text,
)
from orchestration.harness.start_guard import ensure_dispatch_startable
from orchestration.scripts.overlap_worktree import prepare_overlap_worktree, requested_overlap_isolation

HELPER_RUNTIME_PATH = "helper_runtime"
LIVE_SUBAGENT_PATH = "live_subagent"
LIVE_SUBAGENT_MODES = {"guided_agent", "strict_refactor"}
BRIDGE_STAGES = {
    "helper_runtime_no_spawn",
    "awaiting_executor_spawn",
    "executor_spawned",
    "awaiting_reviewer_spawn",
    "reviewer_spawned",
    "review_not_required",
    "helper_review_path",
}
SPAWN_OUTCOMES = {"spawned", "blocked", "failed", "skipped"}


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dispatch_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return resolve_agent_root(repo_root) / "dispatches" / Path(dispatch_ref)


def spawn_bridge_path_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return dispatch_dir_for_ref(repo_root, dispatch_ref) / "spawn_bridge.json"


def executor_handoff_path_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return dispatch_dir_for_ref(repo_root, dispatch_ref) / "executor_handoff.txt"


def reviewer_handoff_path_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return dispatch_dir_for_ref(repo_root, dispatch_ref) / "reviewer_handoff.txt"


def execution_mode_from_request(request: Dict[str, Any]) -> str:
    return request.get("execution_mode") or "manual_artifact_report"


def resolve_execution_path(execution_mode: str) -> str:
    if execution_mode in LIVE_SUBAGENT_MODES:
        return LIVE_SUBAGENT_PATH
    return HELPER_RUNTIME_PATH


def review_artifact_rel_from_request(request: Dict[str, Any], repo_root: Path) -> Optional[str]:
    configured = request.get("review_artifact_path")
    if isinstance(configured, str) and configured.strip():
        return configured
    if request.get("review_required"):
        return repo_relative(
            resolve_agent_root(repo_root) / "reviews" / Path(request["dispatch_ref"]) / "review.json",
            repo_root,
        )
    return None


def _bridge_base(request: Dict[str, Any]) -> Dict[str, Any]:
    execution_mode = execution_mode_from_request(request)
    return {
        "dispatch_ref": request["dispatch_ref"],
        "execution_mode": execution_mode,
        "resolved_path": resolve_execution_path(execution_mode),
        "review_required": bool(request.get("review_required")),
        "bridge_stage": "helper_runtime_no_spawn",
        "last_action": "resolve_dispatch_path",
        "executor_handoff_ref": None,
        "reviewer_handoff_ref": None,
        "overlap_isolation_ref": None,
        "spawn_records": {
            "executor": None,
            "reviewer": None,
        },
        "updated_at": utc_now(),
    }


def _load_request(repo_root: Path, dispatch_ref: str) -> tuple[Path, Dict[str, Any]]:
    dispatch_dir = dispatch_dir_for_ref(repo_root, dispatch_ref)
    request_path = dispatch_dir / "request.json"
    if not request_path.exists():
        raise SystemExit(f"dispatch request does not exist: {repo_relative(request_path, repo_root)}")
    return dispatch_dir, load_json(request_path)


def _load_existing_bridge_or_base(repo_root: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    bridge_path = spawn_bridge_path_for_ref(repo_root, request["dispatch_ref"])
    if bridge_path.exists():
        existing = load_json(bridge_path)
        if existing.get("dispatch_ref") != request["dispatch_ref"]:
            raise SystemExit(
                "existing spawn_bridge.json dispatch_ref does not match request dispatch_ref"
            )
        return existing
    return _bridge_base(request)


def _persist_bridge(repo_root: Path, bridge: Dict[str, Any]) -> Dict[str, Any]:
    bridge["updated_at"] = utc_now()
    bridge_path = spawn_bridge_path_for_ref(repo_root, bridge["dispatch_ref"])
    write_json(bridge_path, bridge)
    payload = dict(bridge)
    payload["bridge_artifact_ref"] = repo_relative(bridge_path, repo_root)
    return payload


def build_executor_handoff(
    request: Dict[str, Any],
    repo_root: Path,
    *,
    overlap_payload: Optional[Dict[str, Any]] = None,
) -> str:
    dispatch_ref = request["dispatch_ref"]
    dispatch_dir = dispatch_dir_for_ref(repo_root, dispatch_ref)
    request_ref = repo_relative(dispatch_dir / "request.json", repo_root)
    lines = [
        "Live executor spawn handoff",
        f"Dispatch ref: {dispatch_ref}",
        f"Execution mode: {execution_mode_from_request(request)}",
        f"Objective: {request.get('objective', '').strip()}",
        "Read first:",
        f"- {prompt_ref('executor.txt', repo_root)}",
        f"- {contract_ref('dispatch.md', repo_root)}",
        f"- {request_ref}",
    ]
    declared_scope = request.get("scope", [])
    if isinstance(declared_scope, list) and declared_scope:
        lines.append("Bounded scope:")
        lines.extend(f"- {item}" for item in declared_scope)
    required_outputs = request.get("required_outputs", [])
    if isinstance(required_outputs, list) and required_outputs:
        lines.append("Required outputs:")
        lines.extend(f"- {item}" for item in required_outputs)
    if overlap_payload is not None:
        lines.extend(
            [
                "Overlap isolation:",
                f"- mode: {overlap_payload.get('mode')}",
                f"- overlap group: {overlap_payload.get('overlap_group')}",
                f"- integration policy: {overlap_payload.get('integration_policy')}",
                f"- lane repo root: {repo_root}",
                f"- isolated worktree: {overlap_payload.get('worktree_path')}",
                f"- ephemeral branch: {overlap_payload.get('ephemeral_branch')}",
                f"- base commit: {overlap_payload.get('base_commit_sha')}",
                "- do not integrate, merge, or write directly to the lane branch",
                "- finalize the isolated candidate before reporting completion:",
                f"  python3 {script_ref('overlap_worktree.py', repo_root)} finalize-candidate --dispatch-ref {dispatch_ref} --root {repo_root}",
            ]
        )
    lines.append(
        "Next action: spawn the executor in the live chat window using "
        f"{actor_config_ref('executor.toml', repo_root)}."
    )
    return "\n".join(lines) + "\n"


def build_reviewer_handoff(request: Dict[str, Any], result: Dict[str, Any], repo_root: Path) -> str:
    dispatch_ref = request["dispatch_ref"]
    dispatch_dir = dispatch_dir_for_ref(repo_root, dispatch_ref)
    request_ref = repo_relative(dispatch_dir / "request.json", repo_root)
    result_ref = repo_relative(dispatch_dir / "result.json", repo_root)
    lines = [
        "Live reviewer spawn handoff",
        f"Dispatch ref: {dispatch_ref}",
        f"Execution mode: {execution_mode_from_request(request)}",
        "Read first:",
        f"- {prompt_ref('reviewer.txt', repo_root)}",
        f"- {contract_ref('dispatch.md', repo_root)}",
        f"- {request_ref}",
        f"- {result_ref}",
    ]
    review_focus = request.get("review_focus", [])
    if isinstance(review_focus, list) and review_focus:
        lines.append("Review focus:")
        lines.extend(f"- {item}" for item in review_focus)
    written = result.get("written_or_updated", [])
    if isinstance(written, list) and written:
        lines.append("Touched or produced artifacts:")
        lines.extend(f"- {item}" for item in written)
    review_ref = review_artifact_rel_from_request(request, repo_root)
    if review_ref:
        lines.append(f"Write or copy review artifact to: {review_ref}")
    lines.append(
        "Next action: spawn the reviewer in the live chat window using "
        f"{actor_config_ref('reviewer.toml', repo_root)}."
    )
    return "\n".join(lines) + "\n"


def resolve_dispatch_path_for_ref(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    _dispatch_dir, request = _load_request(repo_root, dispatch_ref)
    execution_mode = execution_mode_from_request(request)
    resolved_path = resolve_execution_path(execution_mode)
    spawn_required = resolved_path == LIVE_SUBAGENT_PATH
    bridge = _load_existing_bridge_or_base(repo_root, request)
    bridge["last_action"] = "resolve_dispatch_path"
    bridge["bridge_stage"] = "awaiting_executor_spawn" if spawn_required else "helper_runtime_no_spawn"
    persisted = _persist_bridge(repo_root, bridge)
    persisted["spawn_required"] = spawn_required
    persisted["next_action"] = (
        "prepare_executor_spawn" if spawn_required else "no live spawn needed"
    )
    return persisted


def prepare_executor_spawn(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    _dispatch_dir, request = _load_request(repo_root, dispatch_ref)
    bridge = _load_existing_bridge_or_base(repo_root, request)
    if bridge["resolved_path"] == HELPER_RUNTIME_PATH:
        bridge["bridge_stage"] = "helper_runtime_no_spawn"
        bridge["last_action"] = "prepare_executor_spawn"
        persisted = _persist_bridge(repo_root, bridge)
        persisted["spawn_required"] = False
        persisted["next_action"] = "no live spawn needed; helper runtime remains the execution path"
        return persisted

    ensure_dispatch_startable(repo_root, request)
    overlap_payload = None
    if requested_overlap_isolation(request) is not None:
        overlap_payload = prepare_overlap_worktree(repo_root, request)
    handoff_path = executor_handoff_path_for_ref(repo_root, dispatch_ref)
    write_text(
        handoff_path,
        build_executor_handoff(request, repo_root, overlap_payload=overlap_payload),
    )
    bridge["bridge_stage"] = "awaiting_executor_spawn"
    bridge["last_action"] = "prepare_executor_spawn"
    bridge["executor_handoff_ref"] = repo_relative(handoff_path, repo_root)
    bridge["overlap_isolation_ref"] = overlap_payload.get("artifact_ref") if overlap_payload else None
    persisted = _persist_bridge(repo_root, bridge)
    persisted["spawn_required"] = True
    persisted["next_action"] = (
        "spawn executor in the live chat window using "
        + actor_config_ref("executor.toml", repo_root)
    )
    return persisted


def record_executor_spawn(
    repo_root: Path,
    dispatch_ref: str,
    *,
    outcome: str,
    thread_ref: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    if outcome not in SPAWN_OUTCOMES:
        raise SystemExit(f"unsupported executor spawn outcome: {outcome}")
    _dispatch_dir, request = _load_request(repo_root, dispatch_ref)
    bridge = _load_existing_bridge_or_base(repo_root, request)
    bridge["last_action"] = "record_executor_spawn"
    bridge["spawn_records"]["executor"] = {
        "outcome": outcome,
        "thread_ref": thread_ref,
        "notes": notes,
        "recorded_at": utc_now(),
    }
    bridge["bridge_stage"] = "executor_spawned" if outcome == "spawned" else "awaiting_executor_spawn"
    persisted = _persist_bridge(repo_root, bridge)
    persisted["next_action"] = (
        "wait_for_executor_result" if outcome == "spawned" else "executor spawn still required"
    )
    return persisted


def prepare_reviewer_spawn(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    dispatch_dir, request = _load_request(repo_root, dispatch_ref)
    bridge = _load_existing_bridge_or_base(repo_root, request)
    review_required = bool(request.get("review_required"))
    if not review_required:
        bridge["bridge_stage"] = "review_not_required"
        bridge["last_action"] = "prepare_reviewer_spawn"
        persisted = _persist_bridge(repo_root, bridge)
        persisted["spawn_required"] = False
        persisted["next_action"] = "review not required"
        return persisted

    if bridge["resolved_path"] == HELPER_RUNTIME_PATH:
        bridge["bridge_stage"] = "helper_review_path"
        bridge["last_action"] = "prepare_reviewer_spawn"
        persisted = _persist_bridge(repo_root, bridge)
        persisted["spawn_required"] = False
        persisted["next_action"] = "no live reviewer spawn needed; use the existing reviewer helper path"
        return persisted

    result_path = dispatch_dir / "result.json"
    if not result_path.exists():
        raise SystemExit("cannot prepare reviewer spawn before result.json exists")
    result = load_json(result_path)
    handoff_path = reviewer_handoff_path_for_ref(repo_root, dispatch_ref)
    write_text(handoff_path, build_reviewer_handoff(request, result, repo_root))
    bridge["bridge_stage"] = "awaiting_reviewer_spawn"
    bridge["last_action"] = "prepare_reviewer_spawn"
    bridge["reviewer_handoff_ref"] = repo_relative(handoff_path, repo_root)
    persisted = _persist_bridge(repo_root, bridge)
    persisted["spawn_required"] = True
    persisted["next_action"] = (
        "spawn reviewer in the live chat window using "
        + actor_config_ref("reviewer.toml", repo_root)
    )
    return persisted


def record_reviewer_spawn(
    repo_root: Path,
    dispatch_ref: str,
    *,
    outcome: str,
    thread_ref: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    if outcome not in SPAWN_OUTCOMES:
        raise SystemExit(f"unsupported reviewer spawn outcome: {outcome}")
    _dispatch_dir, request = _load_request(repo_root, dispatch_ref)
    bridge = _load_existing_bridge_or_base(repo_root, request)
    bridge["last_action"] = "record_reviewer_spawn"
    bridge["spawn_records"]["reviewer"] = {
        "outcome": outcome,
        "thread_ref": thread_ref,
        "notes": notes,
        "recorded_at": utc_now(),
    }
    bridge["bridge_stage"] = "reviewer_spawned" if outcome == "spawned" else "awaiting_reviewer_spawn"
    persisted = _persist_bridge(repo_root, bridge)
    persisted["next_action"] = (
        "persist review.json, then finalize" if outcome == "spawned" else "reviewer spawn still required"
    )
    return persisted
