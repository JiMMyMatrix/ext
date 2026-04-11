#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

OVERLAP_ISOLATION_MODE = "git_worktree"
INTEGRATION_POLICIES = {"choose_one", "can_stack"}
ISOLATION_ACTIVE_STATUSES = {"prepared", "candidate_ready"}
ISOLATION_UNRESOLVED_STATUSES = {"prepared", "candidate_ready", "rebase_needed", "stale"}
ISOLATION_TERMINAL_STATUSES = {"integrated", "superseded", "discarded", "cleaned"}
AUXILIARY_PREFIXES = (
    ".agent/dispatches/",
    ".agent/governor/",
    ".agent/reviews/",
    ".agent/runs/",
    ".agent/smoke/",
    ".agent/worktrees/",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_git(repo_root: Path, *argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *argv],
        cwd=str(repo_root),
        check=check,
        text=True,
        capture_output=True,
    )


def run_git_stdout(repo_root: Path, *argv: str) -> str:
    return run_git(repo_root, *argv).stdout.strip()


def relative_path(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root))


def normalize_rel_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip("/")


def path_is_auxiliary(rel_path: str) -> bool:
    normalized = normalize_rel_path(rel_path)
    return any(normalized == prefix.rstrip("/") or normalized.startswith(prefix) for prefix in AUXILIARY_PREFIXES)


def path_is_covered(rel_path: str, coverage: List[str]) -> bool:
    normalized = normalize_rel_path(rel_path)
    for reserved in coverage:
        reserved_norm = normalize_rel_path(reserved)
        if not reserved_norm:
            continue
        if normalized == reserved_norm or normalized.startswith(reserved_norm + "/"):
            return True
    return False


def lane_worktree_has_substantive_changes(repo_root: Path) -> bool:
    status = run_git(repo_root, "status", "--short", "--untracked-files=all").stdout
    for raw_line in status.splitlines():
        if len(raw_line) < 4:
            continue
        rel_path = raw_line[3:]
        if " -> " in rel_path:
            rel_path = rel_path.split(" -> ", 1)[1]
        if path_is_auxiliary(rel_path):
            continue
        return True
    return False


def request_scope_reservations(request: Dict[str, Any]) -> List[str]:
    values = request.get("scope_reservations")
    if not isinstance(values, list):
        return []
    out: List[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = normalize_rel_path(value)
        if normalized and normalized not in out:
            out.append(normalized)
    return out


def isolated_worktree_status_paths(worktree_path: Path) -> List[str]:
    status = run_git(worktree_path, "status", "--short", "--untracked-files=all").stdout
    paths: List[str] = []
    for raw_line in status.splitlines():
        if len(raw_line) < 4:
            continue
        rel_path = raw_line[3:]
        if " -> " in rel_path:
            rel_path = rel_path.split(" -> ", 1)[1]
        normalized = normalize_rel_path(rel_path)
        if normalized:
            paths.append(normalized)
    return paths


def ensure_isolated_candidate_scoped(repo_root: Path, dispatch_ref: str, request: Dict[str, Any], worktree_path: Path) -> None:
    scope = request_scope_reservations(request)
    if not scope:
        raise SystemExit("isolated candidate scope is unknown; scope_reservations are required")

    workflow_drift: List[str] = []
    scope_violations: List[str] = []
    for rel_path in isolated_worktree_status_paths(worktree_path):
        if rel_path.startswith(".agent/"):
            workflow_drift.append(rel_path)
            continue
        if path_is_auxiliary(rel_path):
            continue
        if not path_is_covered(rel_path, scope):
            scope_violations.append(rel_path)

    blockers: List[str] = []
    blockers.extend(f"isolated_workflow_drift:{path}" for path in workflow_drift)
    blockers.extend(f"isolated_scope_violation:{path}" for path in scope_violations)
    if blockers:
        raise SystemExit(f"dispatch {dispatch_ref} cannot finalize isolated candidate: {'; '.join(blockers)}")


def load_governor_acceptance(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    decision_path = dispatch_dir_for_ref(repo_root, dispatch_ref) / "governor_decision.json"
    if not decision_path.exists():
        raise SystemExit("isolated candidate integration requires an accepted governor_decision.json")
    decision = load_json(decision_path)
    if decision.get("dispatch_ref") != dispatch_ref or decision.get("decision") != "accept":
        raise SystemExit("isolated candidate integration requires governor_decision.json decision = accept")
    return decision


def load_completed_result(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    result_path = dispatch_dir_for_ref(repo_root, dispatch_ref) / "result.json"
    if not result_path.exists():
        raise SystemExit("isolated candidate integration requires a completed result.json")
    result = load_json(result_path)
    if result.get("dispatch_ref") != dispatch_ref or result.get("status") != "completed" or result.get("blocker"):
        raise SystemExit("isolated candidate integration requires result.json status = completed with no blocker")
    return result


def dispatch_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return repo_root / ".agent" / "dispatches" / Path(dispatch_ref)


def overlap_artifact_path_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return dispatch_dir_for_ref(repo_root, dispatch_ref) / "overlap_isolation.json"


def candidate_patch_path_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return dispatch_dir_for_ref(repo_root, dispatch_ref) / "candidate.patch"


def worktree_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return repo_root / ".agent" / "worktrees" / Path(dispatch_ref) / "repo"


def requested_overlap_isolation(request: Dict[str, Any]) -> Optional[Dict[str, str]]:
    payload = request.get("overlap_isolation")
    if not isinstance(payload, dict):
        return None
    mode = payload.get("mode")
    overlap_group = payload.get("overlap_group")
    integration_policy = payload.get("integration_policy", "choose_one")
    if not isinstance(mode, str) or not mode.strip():
        return None
    if not isinstance(overlap_group, str) or not overlap_group.strip():
        return None
    if not isinstance(integration_policy, str) or not integration_policy.strip():
        return None
    return {
        "mode": mode.strip(),
        "overlap_group": overlap_group.strip(),
        "integration_policy": integration_policy.strip(),
    }


def overlap_isolation_active(request: Dict[str, Any]) -> bool:
    spec = requested_overlap_isolation(request)
    return bool(spec and spec.get("mode") == OVERLAP_ISOLATION_MODE)


def sanitize_branch_name(dispatch_ref: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._/-]+", "-", dispatch_ref.strip().replace("\\", "/"))
    normalized = normalized.strip("-/") or "dispatch"
    branch = f"isolated/{normalized}"
    return branch[:120].rstrip("/") or "isolated/dispatch"


def current_branch(repo_root: Path) -> str:
    return run_git_stdout(repo_root, "branch", "--show-current")


def load_overlap_artifact(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    path = overlap_artifact_path_for_ref(repo_root, dispatch_ref)
    if not path.exists():
        raise SystemExit(f"overlap isolation artifact missing: {relative_path(path, repo_root)}")
    payload = load_json(path)
    if payload.get("dispatch_ref") != dispatch_ref:
        raise SystemExit("existing overlap_isolation.json dispatch_ref does not match")
    return payload


def _persist_artifact(repo_root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload["updated_at"] = utc_now()
    artifact_path = overlap_artifact_path_for_ref(repo_root, payload["dispatch_ref"])
    write_json(artifact_path, payload)
    out = dict(payload)
    out["artifact_ref"] = relative_path(artifact_path, repo_root)
    return out


def _request_for_dispatch(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    request_path = dispatch_dir_for_ref(repo_root, dispatch_ref) / "request.json"
    if not request_path.exists():
        raise SystemExit(f"request.json missing for dispatch: {dispatch_ref}")
    return load_json(request_path)


def _candidate_group_records(
    repo_root: Path,
    *,
    lane: str,
    overlap_group: str,
    exclude_dispatch_ref: Optional[str] = None,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    queue_root = repo_root / ".agent" / "dispatches"
    if not queue_root.exists():
        return records
    for artifact_path in sorted(queue_root.rglob("overlap_isolation.json")):
        payload = load_json(artifact_path)
        if payload.get("lane") != lane:
            continue
        if payload.get("overlap_group") != overlap_group:
            continue
        if exclude_dispatch_ref and payload.get("dispatch_ref") == exclude_dispatch_ref:
            continue
        records.append(payload)
    return records


def prepare_overlap_worktree(repo_root: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    spec = requested_overlap_isolation(request)
    if not spec or spec["mode"] != OVERLAP_ISOLATION_MODE:
        raise SystemExit("dispatch does not request git-worktree overlap isolation")

    dispatch_ref = request["dispatch_ref"]
    artifact_path = overlap_artifact_path_for_ref(repo_root, dispatch_ref)
    if artifact_path.exists():
        payload = load_json(artifact_path)
        worktree_path = Path(str(payload.get("worktree_path") or ""))
        if not worktree_path.exists():
            worktree_path.parent.mkdir(parents=True, exist_ok=True)
            ephemeral_branch = str(payload.get("ephemeral_branch") or "").strip()
            base_commit_sha = str(payload.get("base_commit_sha") or "").strip()
            if not ephemeral_branch or not base_commit_sha:
                raise SystemExit("existing overlap isolation artifact is missing worktree bootstrap fields")
            run_git(repo_root, "worktree", "add", str(worktree_path), ephemeral_branch)
        return _persist_artifact(repo_root, payload)

    lane_branch = current_branch(repo_root)
    base_commit_sha = run_git_stdout(repo_root, "rev-parse", "HEAD")
    worktree_path = worktree_dir_for_ref(repo_root, dispatch_ref)
    ephemeral_branch = sanitize_branch_name(dispatch_ref)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    run_git(repo_root, "worktree", "add", "-b", ephemeral_branch, str(worktree_path), base_commit_sha)

    payload = {
        "dispatch_ref": dispatch_ref,
        "originating_dispatch_ref": dispatch_ref,
        "lane": request.get("lane"),
        "lane_branch": lane_branch,
        "lane_repo_root": str(repo_root),
        "mode": spec["mode"],
        "overlap_group": spec["overlap_group"],
        "integration_policy": spec["integration_policy"],
        "base_commit_sha": base_commit_sha,
        "ephemeral_branch": ephemeral_branch,
        "worktree_path": str(worktree_path),
        "worktree_ref": relative_path(worktree_path, repo_root),
        "candidate_artifact_ref": None,
        "candidate_commit_sha": None,
        "integrated_commit_sha": None,
        "status": "prepared",
        "prepared_at": utc_now(),
        "cleanup_completed_at": None,
        "cleanup_reason": None,
    }
    return _persist_artifact(repo_root, payload)


def finalize_overlap_candidate(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    payload = load_overlap_artifact(repo_root, dispatch_ref)
    if payload.get("status") not in {"prepared", "candidate_ready"}:
        raise SystemExit("isolated candidate cannot be finalized from the current status")
    request = _request_for_dispatch(repo_root, dispatch_ref)
    worktree_path = Path(payload["worktree_path"])
    if not worktree_path.exists():
        raise SystemExit("isolated worktree does not exist")
    if current_branch(worktree_path) != payload.get("ephemeral_branch"):
        raise SystemExit("isolated candidate must be finalized from the recorded ephemeral branch")

    ensure_isolated_candidate_scoped(repo_root, dispatch_ref, request, worktree_path)

    status = run_git_stdout(worktree_path, "status", "--short", "--untracked-files=all")
    if status.strip():
        run_git(worktree_path, "add", "-A")
        cached = run_git(worktree_path, "diff", "--cached", "--quiet", check=False)
        if cached.returncode != 0:
            run_git(worktree_path, "commit", "-m", f"candidate:{dispatch_ref}")

    head_sha = run_git_stdout(worktree_path, "rev-parse", "HEAD")
    if head_sha == payload["base_commit_sha"]:
        raise SystemExit("isolated candidate has no committed changes relative to base")

    patch_path = candidate_patch_path_for_ref(repo_root, dispatch_ref)
    diff = run_git(
        worktree_path,
        "diff",
        "--binary",
        f"{payload['base_commit_sha']}..{head_sha}",
    ).stdout
    if not diff.strip():
        raise SystemExit("isolated candidate patch is empty")
    patch_path.write_text(diff, encoding="utf-8")

    payload["candidate_commit_sha"] = head_sha
    payload["candidate_artifact_ref"] = relative_path(patch_path, repo_root)
    payload["candidate_changed_files"] = [
        item
        for item in run_git(
            worktree_path,
            "diff",
            "--name-only",
            f"{payload['base_commit_sha']}..{head_sha}",
        ).stdout.splitlines()
        if item.strip()
    ]
    payload["status"] = "candidate_ready"
    payload["candidate_finalized_at"] = utc_now()
    return _persist_artifact(repo_root, payload)


def _run_validators(repo_root: Path, validators: List[str]) -> None:
    for command in validators:
        if not isinstance(command, str) or not command.strip():
            continue
        subprocess.run(
            ["bash", "-lc", command],
            cwd=str(repo_root),
            check=True,
            text=True,
            capture_output=True,
        )


def integrate_overlap_candidate(repo_root: Path, dispatch_ref: str) -> Dict[str, Any]:
    normalized_root = str(repo_root.resolve()).replace("\\", "/")
    if "/.agent/worktrees/" in normalized_root:
        raise SystemExit("isolated candidate integration must not run from the isolated worktree")
    payload = load_overlap_artifact(repo_root, dispatch_ref)
    request = _request_for_dispatch(repo_root, dispatch_ref)
    load_completed_result(repo_root, dispatch_ref)
    load_governor_acceptance(repo_root, dispatch_ref)
    if payload.get("status") != "candidate_ready":
        raise SystemExit("isolated candidate must be candidate_ready before integration")
    patch_ref = payload.get("candidate_artifact_ref")
    if not isinstance(patch_ref, str) or not patch_ref.strip():
        raise SystemExit("isolated candidate is not ready for integration")

    recorded_lane_root = str(payload.get("lane_repo_root") or "").strip()
    if recorded_lane_root and Path(recorded_lane_root).resolve() != repo_root.resolve():
        raise SystemExit("isolated candidate integration must run from the recorded lane repo root")
    if repo_root.resolve() == Path(payload["worktree_path"]).resolve():
        raise SystemExit("isolated candidate integration must not run from the isolated worktree")
    if current_branch(repo_root) != payload.get("lane_branch"):
        raise SystemExit("current branch does not match the recorded lane branch for isolated integration")

    current_head = run_git_stdout(repo_root, "rev-parse", "HEAD")
    if current_head != payload.get("base_commit_sha"):
        same_group = _candidate_group_records(
            repo_root,
            lane=str(payload.get("lane") or ""),
            overlap_group=str(payload.get("overlap_group") or ""),
            exclude_dispatch_ref=dispatch_ref,
        )
        integrated_peer = next(
            (record for record in same_group if record.get("status") == "integrated"),
            None,
        )
        if payload.get("integration_policy") == "choose_one" and integrated_peer is not None:
            payload["status"] = "superseded"
            payload["superseded_by_dispatch_ref"] = integrated_peer["dispatch_ref"]
        elif payload.get("integration_policy") == "can_stack":
            payload["status"] = "rebase_needed"
        else:
            payload["status"] = "stale"
        _persist_artifact(repo_root, payload)
        raise SystemExit(f"isolated candidate cannot integrate from stale base: {payload['status']}")

    if lane_worktree_has_substantive_changes(repo_root):
        raise SystemExit("lane branch worktree must be clean before isolated integration")

    patch_path = repo_root / patch_ref
    if not patch_path.exists():
        raise SystemExit(f"candidate patch missing: {patch_ref}")

    run_git(repo_root, "apply", "--index", "--3way", str(patch_path))
    validators = [cmd for cmd in request.get("required_validators", []) if isinstance(cmd, str) and cmd.strip()]
    try:
        _run_validators(repo_root, validators)
    except subprocess.CalledProcessError as exc:
        run_git(repo_root, "apply", "-R", "--index", str(patch_path))
        output = (exc.stderr or exc.stdout or "").strip()
        raise SystemExit(output or "post-integration validation failed") from exc

    run_git(repo_root, "commit", "-m", f"integrate isolated candidate {dispatch_ref}")
    payload["status"] = "integrated"
    payload["integrated_commit_sha"] = run_git_stdout(repo_root, "rev-parse", "HEAD")
    payload["integrated_at"] = utc_now()
    payload["post_integration_validators"] = validators
    persisted = _persist_artifact(repo_root, payload)
    if payload.get("integration_policy") == "choose_one":
        _mark_choose_one_peers_superseded(
            repo_root,
            lane=str(payload.get("lane") or ""),
            overlap_group=str(payload.get("overlap_group") or ""),
            integrated_dispatch_ref=dispatch_ref,
        )
    lane = str(payload.get("lane") or "").strip()
    if lane:
        command = [
            sys.executable,
            str(Path(__file__).resolve().with_name("governor_record_transition.py")),
            "--lane",
            lane,
            "--source",
            "overlap_worktree.integrate",
            "--transition",
            "continue_internal",
            "--next-action-kind",
            "replan",
            "--next-action-ref",
            dispatch_ref,
            "--next-action-summary",
            "integration completed; decide whether the lane is merge-ready or needs another bounded step",
            "--dispatch-ref",
            dispatch_ref,
            "--evidence-ref",
            relative_path(overlap_artifact_path_for_ref(repo_root, dispatch_ref), repo_root),
            "--root",
            str(repo_root),
        ]
        subprocess.run(
            command,
            cwd=str(Path(__file__).resolve().parents[2]),
            check=True,
            capture_output=True,
            text=True,
        )
    return persisted


def discard_overlap_candidate(repo_root: Path, dispatch_ref: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload = load_overlap_artifact(repo_root, dispatch_ref)
    payload["status"] = "discarded"
    payload["discard_reason"] = reason or "discarded_by_governor"
    payload["discarded_at"] = utc_now()
    return _persist_artifact(repo_root, payload)


def _mark_choose_one_peers_superseded(
    repo_root: Path,
    *,
    lane: str,
    overlap_group: str,
    integrated_dispatch_ref: str,
) -> None:
    for peer in _candidate_group_records(
        repo_root,
        lane=lane,
        overlap_group=overlap_group,
        exclude_dispatch_ref=integrated_dispatch_ref,
    ):
        if peer.get("integration_policy") != "choose_one":
            continue
        if peer.get("status") not in ISOLATION_ACTIVE_STATUSES | {"stale", "rebase_needed"}:
            continue
        peer["status"] = "superseded"
        peer["superseded_by_dispatch_ref"] = integrated_dispatch_ref
        peer["superseded_at"] = utc_now()
        _persist_artifact(repo_root, peer)


def cleanup_overlap_worktree(repo_root: Path, dispatch_ref: str, *, force: bool = False) -> Dict[str, Any]:
    payload = load_overlap_artifact(repo_root, dispatch_ref)
    if not force and payload.get("status") not in {"integrated", "superseded", "discarded", "stale"}:
        raise SystemExit("isolated worktree cleanup requires an integrated, superseded, discarded, or stale candidate")

    worktree_path = Path(payload["worktree_path"])
    if worktree_path.exists():
        run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))

    branch_name = payload.get("ephemeral_branch")
    if isinstance(branch_name, str) and branch_name.strip():
        run_git(repo_root, "branch", "-D", branch_name, check=False)

    payload["cleanup_completed_at"] = utc_now()
    payload["cleanup_reason"] = "force" if force else "terminal_state_cleanup"
    payload["status"] = "cleaned" if payload.get("status") in ISOLATION_TERMINAL_STATUSES else payload.get("status")
    return _persist_artifact(repo_root, payload)


def lane_overlap_blockers(repo_root: Path, lane: str) -> List[str]:
    blockers: List[str] = []
    queue_root = repo_root / ".agent" / "dispatches"
    if not queue_root.exists():
        return blockers
    for artifact_path in sorted(queue_root.rglob("overlap_isolation.json")):
        payload = load_json(artifact_path)
        if payload.get("lane") != lane:
            continue
        status = payload.get("status")
        if status in ISOLATION_UNRESOLVED_STATUSES:
            blockers.append(f"overlap_isolation_pending:{payload.get('dispatch_ref')}")
    return blockers


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare, finalize, integrate, or clean up isolated overlap worktrees.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ["prepare", "finalize-candidate", "integrate", "cleanup", "discard"]:
        sub = subparsers.add_parser(name)
        sub.add_argument("--dispatch-ref", required=True)
        sub.add_argument("--root", default=".")
        if name == "discard":
            sub.add_argument("--reason")
        if name == "cleanup":
            sub.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    repo_root = Path(args.root).resolve()

    if args.command == "prepare":
        payload = prepare_overlap_worktree(repo_root, _request_for_dispatch(repo_root, args.dispatch_ref))
    elif args.command == "finalize-candidate":
        payload = finalize_overlap_candidate(repo_root, args.dispatch_ref)
    elif args.command == "integrate":
        payload = integrate_overlap_candidate(repo_root, args.dispatch_ref)
    elif args.command == "discard":
        payload = discard_overlap_candidate(repo_root, args.dispatch_ref, getattr(args, "reason", None))
    else:
        payload = cleanup_overlap_worktree(repo_root, args.dispatch_ref, force=bool(getattr(args, "force", False)))

    print(payload["artifact_ref"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
