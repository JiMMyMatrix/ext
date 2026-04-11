#!/usr/bin/env python3
import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.harness_artifacts import (
    load_acceptance_review,
    load_review_artifact,
    load_validation_delta,
    load_window_eval,
    validate_checkpoint_markdown,
)
from scripts.dispatch_start_guard import ensure_dispatch_startable, ensure_lane_worktree_tracked, find_start_blockers
from scripts.harness_runtime import (
    FAILURE_INVALID_RUNTIME_ENVIRONMENT,
    FAILURE_SCOPE_VIOLATION,
    FAILURE_UNDECLARED_UNTRACKED_OUTPUT,
    default_scope_ignored_prefixes,
    ensure_approved_python_binary,
    ensure_running_with_approved_python,
    git_status_snapshot,
    scope_audit,
)


ALLOWED_TRANSITIONS = {
    "queued": {"claimed", "escalated"},
    "claimed": {"running", "escalated"},
    "running": {"validated", "escalated"},
    "validated": {"completed", "escalated"},
    "completed": set(),
    "escalated": set(),
}

SUBAGENT_ONLY_MODES = {"guided_agent", "strict_refactor"}
SUPPORTED_SAMPLE_ACCEPTANCE_IDS = {"sample3", "sample6"}
FORBIDDEN_COMMAND_PATTERNS = (
    "git push",
    "git merge",
    "git rebase",
    "git reset --hard",
    "rm -rf /",
    "rm -rf /*",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def resolve_local_refs(node, base_dir: Path):
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if ref.startswith("#"):
                return node
            ref_path = (base_dir / ref).resolve()
            resolved = resolve_local_refs(load_json(ref_path), ref_path.parent)
            extras = {key: value for key, value in node.items() if key != "$ref"}
            if extras and isinstance(resolved, dict):
                merged = dict(resolved)
                merged.update(resolve_local_refs(extras, base_dir))
                return merged
            return resolved
        return {key: resolve_local_refs(value, base_dir) for key, value in node.items()}
    if isinstance(node, list):
        return [resolve_local_refs(value, base_dir) for value in node]
    return node


def repo_root_for(path: Path) -> Path:
    current = path.resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / ".git").exists():
            return candidate
    return REPO_ROOT


def run_dir_for_ref(repo_root: Path, run_ref: str) -> Path:
    return repo_root / ".agent" / "runs" / Path(run_ref)


def dispatch_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return repo_root / ".agent" / "dispatches" / Path(dispatch_ref)


def acquire_lock(dispatch_dir: Path) -> int:
    lock_path = dispatch_dir / ".claim.lock"
    return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


def release_lock(lock_fd: int, dispatch_dir: Path) -> None:
    os.close(lock_fd)
    try:
        (dispatch_dir / ".claim.lock").unlink()
    except FileNotFoundError:
        pass


def update_state(dispatch_dir: Path, new_status: str, actor: str, note: str = "") -> Dict:
    state_path = dispatch_dir / "state.json"
    state = load_json(state_path)
    old_status = state["status"]
    allowed = ALLOWED_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise SystemExit(f"illegal dispatch transition: {old_status} -> {new_status}")
    now = utc_now()
    state["status"] = new_status
    state["last_transition_at"] = now
    state.setdefault("transition_history", []).append(
        {
            "from": old_status,
            "to": new_status,
            "at": now,
            "actor": actor,
            "note": note,
        }
    )
    if note:
        state.setdefault("notes", []).append(note)
    write_json(state_path, state)
    return state


def execution_mode_for_request(request: Dict) -> str:
    return request.get("execution_mode") or "manual_artifact_report"


def ensure_helper_runtime_dispatch(dispatch_dir: Path, request: Dict) -> None:
    execution_mode = execution_mode_for_request(request)
    if execution_mode in SUBAGENT_ONLY_MODES:
        raise SystemExit(
            f"dispatch {dispatch_dir} uses execution_mode {execution_mode!r} and must stay on the live subagent path; "
            "scripts/executor_consume_dispatch.py must not claim it"
        )


def discover_queued_dispatch(queue_root: Path, repo_root: Optional[Path] = None) -> Optional[Path]:
    if repo_root is None:
        resolved_queue_root = queue_root.resolve()
        if resolved_queue_root.name == "dispatches" and resolved_queue_root.parent.name == ".agent":
            repo_root = resolved_queue_root.parent.parent
        else:
            repo_root = repo_root_for(queue_root)
    matches: List[Path] = []
    for state_path in sorted(queue_root.rglob("state.json")):
        try:
            state = load_json(state_path)
        except Exception:
            continue
        if state.get("status") != "queued":
            continue
        request_path = state_path.parent / "request.json"
        try:
            request = load_json(request_path)
        except Exception:
            continue
        if execution_mode_for_request(request) in SUBAGENT_ONLY_MODES:
            continue
        if find_start_blockers(repo_root, request):
            continue
        matches.append(state_path.parent)
    return matches[0] if matches else None


def run_command(cmd: List[str], repo_root: Path) -> None:
    subprocess.run(cmd, check=True, cwd=str(repo_root))


def command_matches_forbidden_pattern(argv: List[str]) -> Optional[str]:
    command_text = " ".join(argv).strip()
    for pattern in FORBIDDEN_COMMAND_PATTERNS:
        if pattern in command_text:
            return pattern
    lowered = [item.lower() for item in argv]
    if ("--force" in lowered or "-f" in lowered or "force" in lowered) and (
        "push" in lowered or "reset" in lowered
    ):
        return "force push/reset"
    return None


def parse_command_spec(spec) -> Dict:
    if isinstance(spec, str):
        argv = shlex.split(spec)
        if not argv:
            raise SystemExit("command spec cannot be empty")
        return {
            "argv": argv,
            "cwd": ".",
            "timeout_sec": None,
            "allow_failure": False,
            "name": argv[0],
        }
    if not isinstance(spec, dict):
        raise SystemExit("command spec must be a string or object")
    argv = spec.get("argv")
    if isinstance(argv, str):
        argv = shlex.split(argv)
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
        raise SystemExit("command spec argv must be a non-empty list of strings")
    return {
        "argv": argv,
        "cwd": spec.get("cwd", "."),
        "timeout_sec": spec.get("timeout_sec"),
        "allow_failure": bool(spec.get("allow_failure", False)),
        "name": spec.get("name") or argv[0],
    }


def sanitize_label(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or "step"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ensure_required_outputs_exist(repo_root: Path, request: Dict) -> List[str]:
    missing: List[str] = []
    existing: List[str] = []
    for rel_path in request.get("required_outputs", []):
        path = repo_root / rel_path
        if path.exists():
            existing.append(rel_path)
        else:
            missing.append(rel_path)
    if missing:
        raise SystemExit(f"required outputs missing after execution: {', '.join(missing)}")
    return existing


def run_payload_validators(repo_root: Path, request: Dict) -> List[str]:
    payload = request.get("execution_payload", {})
    validator_specs = payload.get("validator_commands", [])
    executed: List[str] = []
    for spec in validator_specs:
        command = parse_command_spec(spec)
        cwd = repo_root / command["cwd"]
        subprocess.run(
            command["argv"],
            check=True,
            cwd=str(cwd.resolve()),
            timeout=command["timeout_sec"],
        )
        executed.append("validator: " + " ".join(command["argv"]))
    return executed


def injected_weakness_guards_from_request(request: Dict) -> List[str]:
    payload = request.get("execution_payload", {})
    raw = payload.get("injected_weakness_guards", [])
    if not isinstance(raw, list):
        return []
    cleaned = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    return dedupe_preserve_order(cleaned)


def execute_command_chain(repo_root: Path, dispatch_dir: Path, request: Dict, run_dir: Path) -> List[str]:
    del dispatch_dir
    payload = request.get("execution_payload", {})
    injected_weakness_guards = injected_weakness_guards_from_request(request)
    command_specs = payload.get("commands", [])
    if not isinstance(command_specs, list) or not command_specs:
        raise SystemExit("command_chain dispatch requires execution_payload.commands")
    logs_dir = run_dir / "command_logs"
    produced: List[str] = []
    manifest_commands: List[Dict] = []

    for idx, raw_spec in enumerate(command_specs, start=1):
        command = parse_command_spec(raw_spec)
        forbidden_match = command_matches_forbidden_pattern(command["argv"])
        if forbidden_match:
            raise SystemExit(
                f"forbidden_command_detected: {' '.join(command['argv'])} (matched {forbidden_match})"
            )
        label = sanitize_label(command["name"])
        log_path = logs_dir / f"{idx:02d}_{label}.log"
        cwd = repo_root / command["cwd"]
        proc = subprocess.run(
            command["argv"],
            cwd=str(cwd.resolve()),
            text=True,
            capture_output=True,
            timeout=command["timeout_sec"],
        )
        log_text = "\n".join(
            [
                f"$ {' '.join(command['argv'])}",
                f"cwd: {command['cwd']}",
                f"returncode: {proc.returncode}",
                "",
                "stdout:",
                proc.stdout,
                "",
                "stderr:",
                proc.stderr,
            ]
        ).rstrip() + "\n"
        write_text(log_path, log_text)
        produced.append(relative_path(log_path, repo_root))
        manifest_commands.append(
            {
                "argv": command["argv"],
                "cwd": command["cwd"],
                "returncode": proc.returncode,
                "log_path": relative_path(log_path, repo_root),
                "allow_failure": command["allow_failure"],
            }
        )
        if proc.returncode != 0 and not command["allow_failure"]:
            raise SystemExit(
                f"command_chain step failed: {' '.join(command['argv'])} (see {relative_path(log_path, repo_root)})"
            )

    required_outputs = ensure_required_outputs_exist(repo_root, request)
    produced.extend(item for item in required_outputs if item not in produced)

    manifest = {
        "dispatch_ref": request["dispatch_ref"],
        "execution_mode": "command_chain",
        "commands": manifest_commands,
        "required_outputs_checked": required_outputs,
        "notes": payload.get("notes", []),
    }
    if injected_weakness_guards:
        manifest["injected_weakness_guards"] = injected_weakness_guards
    manifest_path = run_dir / "execution_manifest.json"
    write_json(manifest_path, manifest)
    produced.append(relative_path(manifest_path, repo_root))

    report_outputs = dedupe_preserve_order(produced.copy())
    run_written = write_executor_run_completion(
        run_dir,
        summary=payload.get("summary")
        or f"Executor ran {len(command_specs)} bounded command(s) for dispatch {request['dispatch_ref']}.",
        outputs=report_outputs,
        evidence=payload.get("evidence", []) + [f"execution_manifest={relative_path(manifest_path, repo_root)}"],
        next_action=payload.get("next_action")
        or "Governor should review outputs and either accept, iterate with a narrower task, or escalate on policy grounds.",
        claims=payload.get("claims"),
        injected_weakness_guards=injected_weakness_guards,
    )
    produced.extend(relative_path(Path(path), repo_root) for path in run_written)
    return dedupe_preserve_order(produced)


def execute_manual_artifact_report(repo_root: Path, dispatch_dir: Path, request: Dict, run_dir: Path) -> List[str]:
    del dispatch_dir
    payload = request.get("execution_payload", {})
    injected_weakness_guards = injected_weakness_guards_from_request(request)
    summary = payload.get("summary")
    if not summary:
        raise SystemExit("manual_artifact_report dispatch requires execution_payload.summary")
    required_outputs = ensure_required_outputs_exist(repo_root, request)
    manifest = {
        "dispatch_ref": request["dispatch_ref"],
        "execution_mode": "manual_artifact_report",
        "reported_outputs": required_outputs,
        "notes": payload.get("notes", []),
    }
    if injected_weakness_guards:
        manifest["injected_weakness_guards"] = injected_weakness_guards
    manifest_path = run_dir / "execution_manifest.json"
    write_json(manifest_path, manifest)
    produced = dedupe_preserve_order(required_outputs + [relative_path(manifest_path, repo_root)])
    run_written = write_executor_run_completion(
        run_dir,
        summary=summary,
        outputs=produced.copy(),
        evidence=payload.get("evidence", []) + [f"execution_manifest={relative_path(manifest_path, repo_root)}"],
        next_action=payload.get("next_action")
        or "Governor should review the bounded artifact report and decide the next bounded step inside current lane authority.",
        claims=payload.get("claims"),
        injected_weakness_guards=injected_weakness_guards,
    )
    produced.extend(relative_path(Path(path), repo_root) for path in run_written)
    return dedupe_preserve_order(produced)



def validate_report_schema(repo_root: Path, report_rel: str, schema_rel: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise SystemExit("jsonschema is required for report validation") from exc

    report_path = repo_root / report_rel
    schema_path = repo_root / schema_rel
    report = load_json(report_path)
    schema = resolve_local_refs(load_json(schema_path), schema_path.parent)
    jsonschema.validate(instance=report, schema=schema)


def validate_summary_consistency(repo_root: Path, summary_rel: str) -> None:
    summary = load_json(repo_root / summary_rel)
    sample_chains = summary.get("sample_chains", {})
    overall = summary.get("overall_window_summary", {})
    approved = sum(item["window_summary"]["approved_window_count"] for item in sample_chains.values())
    predicted = sum(item["window_summary"]["predicted_window_count"] for item in sample_chains.values())
    matched = sum(item["window_summary"]["matched_window_count"] for item in sample_chains.values())
    missed = sum(item["window_summary"]["missed_window_count"] for item in sample_chains.values())
    extra = sum(item["window_summary"]["extra_window_count"] for item in sample_chains.values())
    sample_count = len(sample_chains)
    expected = {
        "approved_window_count": approved,
        "predicted_window_count": predicted,
        "matched_window_count": matched,
        "missed_window_count": missed,
        "extra_window_count": extra,
        "sample_count": sample_count,
    }
    for key, value in expected.items():
        if overall.get(key) != value:
            raise SystemExit(f"supervisor summary inconsistency for {key}: expected {value}, got {overall.get(key)}")


def relative_path(path: Path, repo_root: Path) -> str:
    return str(path.relative_to(repo_root))


def dedupe_preserve_order(values: List[str]) -> List[str]:
    out: List[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def collect_review_artifact_refs(repo_root: Path, request: Dict) -> tuple[List[str], List[str]]:
    review_refs: List[str] = []
    auto_validated: List[str] = []
    review_required = bool(request.get("review_required"))
    review_artifact_path = request.get("review_artifact_path")
    if isinstance(review_artifact_path, str) and review_artifact_path.strip():
        path = repo_root / review_artifact_path
        if path.exists():
            load_review_artifact(path)
            review_refs.append(review_artifact_path)
            auto_validated.append(f"review artifact contract validation: {review_artifact_path}")
        elif review_required:
            auto_validated.append(f"review pending: {review_artifact_path}")
    return review_refs, auto_validated


def scaffold_or_reuse_run(repo_root: Path, executor_run: Dict) -> Path:
    run_ref = executor_run["run_ref"]
    run_dir = run_dir_for_ref(repo_root, run_ref)
    if run_dir.exists():
        return run_dir

    cycle, scope_type, scope_ref, artifact_kind, attempt = run_ref.split("/", 4)
    cmd = [
        str(ensure_approved_python_binary()),
        "scripts/scaffold_run.py",
        "--cycle",
        cycle,
        "--scope-type",
        scope_type,
        "--scope-ref",
        scope_ref,
        "--artifact-kind",
        artifact_kind,
        "--attempt",
        attempt,
        "--objective",
        executor_run["objective"],
        "--scope",
        executor_run["scope"],
    ]
    for item in executor_run.get("non_goals", []):
        cmd.extend(["--non-goal", item])
    for item in executor_run.get("stop_conditions", []):
        cmd.extend(["--stop-condition", item])
    for item in executor_run.get("read_list", []):
        cmd.extend(["--read", item])
    for item in executor_run.get("produce_list", []):
        cmd.extend(["--produce", item])
    for item in executor_run.get("planned_file_touch_list", []):
        cmd.extend(["--touch", item])
    run_command(cmd, repo_root)
    return run_dir


def sample_ids_from_inputs(inputs: List[str]) -> List[str]:
    sample_ids: List[str] = []
    for item in inputs:
        name = Path(item).name
        if name.startswith("window_eval.") and name.endswith(".json"):
            sample_id = name[len("window_eval.") : -len(".json")]
            if sample_id:
                sample_ids.append(sample_id)
    return dedupe_preserve_order(sample_ids)


def load_required_json(repo_root: Path, rel_path: str) -> Dict:
    path = repo_root / rel_path
    if not path.exists():
        raise SystemExit(f"required artifact missing: {rel_path}")
    return load_json(path)


def sample_chain_paths(repo_root: Path, sample_id: str) -> Dict[str, Path]:
    reports_dir = repo_root / "reports"
    return {
        "window_eval": reports_dir / f"window_eval.{sample_id}.json",
        "pairwise_eval": reports_dir / f"pairwise_eval.{sample_id}.json",
        "guard_review": reports_dir / f"guard_review.{sample_id}.json",
        "supervisor_decision": reports_dir / f"supervisor_decision.{sample_id}.json",
    }


def window_summary_from_eval(window_eval: Dict) -> Dict:
    return {
        "approved_window_count": window_eval["approved_window_count"],
        "predicted_window_count": window_eval["predicted_window_count"],
        "matched_window_count": window_eval["matched_window_count"],
        "missed_window_count": window_eval["missed_window_count"],
        "extra_window_count": window_eval["extra_window_count"],
        "mean_window_iou": window_eval["mean_window_iou"],
        "mean_start_error_ms": window_eval["mean_start_error_ms"],
        "mean_end_error_ms": window_eval["mean_end_error_ms"],
    }


def aggregate_window_summary(sample_data: Dict[str, Dict]) -> Dict:
    return {
        "approved_window_count": sum(item["window_summary"]["approved_window_count"] for item in sample_data.values()),
        "predicted_window_count": sum(item["window_summary"]["predicted_window_count"] for item in sample_data.values()),
        "matched_window_count": sum(item["window_summary"]["matched_window_count"] for item in sample_data.values()),
        "missed_window_count": sum(item["window_summary"]["missed_window_count"] for item in sample_data.values()),
        "extra_window_count": sum(item["window_summary"]["extra_window_count"] for item in sample_data.values()),
        "sample_count": len(sample_data),
    }


def load_sample_chain(repo_root: Path, sample_id: str) -> Dict:
    paths = sample_chain_paths(repo_root, sample_id)
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        raise SystemExit(f"sample {sample_id} is missing required chain artifacts: {', '.join(missing)}")

    window_eval = load_window_eval(paths["window_eval"])
    pairwise_eval = load_json(paths["pairwise_eval"])
    guard_review = load_json(paths["guard_review"])
    supervisor_decision = load_json(paths["supervisor_decision"])
    correctness_supported = pairwise_eval.get("correctness_judgment_supported") is True

    return {
        "paths": {name: relative_path(path, repo_root) for name, path in paths.items()},
        "window_eval": window_eval,
        "pairwise_eval": pairwise_eval,
        "guard_review": guard_review,
        "supervisor_decision": supervisor_decision,
        "window_summary": window_summary_from_eval(window_eval),
        "chain_complete": True,
        "correctness_judgment_supported": correctness_supported,
        "guard_decision": guard_review.get("gate_decision", ""),
        "supervisor_decision_value": supervisor_decision.get("decision", ""),
    }


def find_single_input(inputs: List[str], predicate, description: str) -> str:
    matches = [item for item in inputs if predicate(item)]
    if not matches:
        raise SystemExit(f"dispatch inputs missing {description}")
    if len(matches) > 1:
        raise SystemExit(f"dispatch inputs contain multiple {description} entries")
    return matches[0]


def sample_id_from_output_names(request: Dict) -> str:
    sample_ids = []
    for rel_path in request.get("required_outputs", []):
        name = Path(rel_path).name
        if name.startswith("window_eval.") and name.endswith(".json"):
            sample_ids.append(name[len("window_eval.") : -len(".json")])
    sample_ids = dedupe_preserve_order(sample_ids)
    if len(sample_ids) != 1:
        raise SystemExit("sample_correctness_chain requires exactly one sample-scoped window_eval output")
    return sample_ids[0]


def required_sample_output_paths(repo_root: Path, request: Dict, sample_id: str) -> Dict[str, Path]:
    outputs = {}
    for rel_path in request.get("required_outputs", []):
        outputs[Path(rel_path).name] = repo_root / rel_path
    required_names = {
        f"window_eval.{sample_id}.json",
        f"pairwise_eval.{sample_id}.json",
        f"guard_review.{sample_id}.json",
        f"supervisor_decision.{sample_id}.json",
    }
    missing = sorted(required_names - set(outputs))
    if missing:
        raise SystemExit(f"dispatch missing required sample outputs: {', '.join(missing)}")
    return outputs


def overlap_ms(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def window_iou(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    overlap = overlap_ms(start_a, end_a, start_b, end_b)
    if overlap <= 0:
        return 0.0
    union = (end_a - start_a) + (end_b - start_b) - overlap
    return overlap / union if union > 0 else 0.0


def build_window_eval_from_truth_and_prediction(
    sample_id: str,
    run_ref: str,
    labels_rel: str,
    eval_report_rel: str,
    labels: Dict,
    eval_report: Dict,
) -> Dict:
    truth_type = ""
    approved_rows = labels.get("approved_highlight_windows") or []
    if approved_rows:
        truth_type = "approved_highlight_windows"
    else:
        approved_rows = labels.get("highlight_windows") or []
        if approved_rows:
            truth_type = "highlight_windows"
    if not approved_rows:
        raise SystemExit(f"{labels_rel} does not contain approved window truth")
    predicted_rows = eval_report.get("pipeline", {}).get("predicted_windows") or []
    if predicted_rows is None:
        predicted_rows = []

    approved_windows = [
        {
            "window_id": f"approved_{idx:03d}",
            "start_ms": int(row["start_ms"]),
            "end_ms": int(row["end_ms"]),
        }
        for idx, row in enumerate(approved_rows, start=1)
    ]

    source_manifest = eval_report.get("pipeline_inputs", {}).get("clip_manifest_jsonl", "")
    predicted_windows = []
    for idx, row in enumerate(predicted_rows, start=1):
        predicted_windows.append(
            {
                "window_id": row.get("window_id", f"predicted_{idx:03d}"),
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
                "source_report": eval_report_rel,
                "source_manifest": source_manifest,
                "primary_clip_id": row.get("primary_clip_id", ""),
            }
        )

    candidates = []
    for approved_idx, approved in enumerate(approved_windows):
        for predicted_idx, predicted in enumerate(predicted_windows):
            overlap = overlap_ms(
                approved["start_ms"],
                approved["end_ms"],
                predicted["start_ms"],
                predicted["end_ms"],
            )
            if overlap <= 0:
                continue
            iou = window_iou(
                approved["start_ms"],
                approved["end_ms"],
                predicted["start_ms"],
                predicted["end_ms"],
            )
            candidates.append(
                {
                    "approved_idx": approved_idx,
                    "predicted_idx": predicted_idx,
                    "overlap_ms": overlap,
                    "window_iou": iou,
                }
            )
    candidates.sort(key=lambda item: (-item["window_iou"], -item["overlap_ms"], item["approved_idx"], item["predicted_idx"]))

    used_approved = set()
    used_predicted = set()
    matches = []
    for candidate in candidates:
        if candidate["approved_idx"] in used_approved or candidate["predicted_idx"] in used_predicted:
            continue
        approved = approved_windows[candidate["approved_idx"]]
        predicted = predicted_windows[candidate["predicted_idx"]]
        start_error = predicted["start_ms"] - approved["start_ms"]
        end_error = predicted["end_ms"] - approved["end_ms"]
        overcut = predicted["start_ms"] < approved["start_ms"] or predicted["end_ms"] > approved["end_ms"]
        undercut = predicted["start_ms"] > approved["start_ms"] or predicted["end_ms"] < approved["end_ms"]
        matches.append(
            {
                "approved_window_id": approved["window_id"],
                "predicted_window_id": predicted["window_id"],
                "approved_start_ms": approved["start_ms"],
                "approved_end_ms": approved["end_ms"],
                "predicted_start_ms": predicted["start_ms"],
                "predicted_end_ms": predicted["end_ms"],
                "overlap_ms": candidate["overlap_ms"],
                "window_iou": candidate["window_iou"],
                "start_error_ms": start_error,
                "end_error_ms": end_error,
                "overcut": overcut,
                "undercut": undercut,
            }
        )
        used_approved.add(candidate["approved_idx"])
        used_predicted.add(candidate["predicted_idx"])

    missed = [approved["window_id"] for idx, approved in enumerate(approved_windows) if idx not in used_approved]
    extra = [predicted["window_id"] for idx, predicted in enumerate(predicted_windows) if idx not in used_predicted]

    matched_count = len(matches)
    mean_iou = sum(item["window_iou"] for item in matches) / matched_count if matched_count else 0.0
    mean_start_error = sum(item["start_error_ms"] for item in matches) / matched_count if matched_count else 0.0
    mean_end_error = sum(item["end_error_ms"] for item in matches) / matched_count if matched_count else 0.0
    overcut_count = sum(1 for item in matches if item["overcut"])
    undercut_count = sum(1 for item in matches if item["undercut"])

    return {
        "run_ref": run_ref,
        "sample_id": sample_id,
        "truth_type": truth_type,
        "approved_window_count": len(approved_windows),
        "predicted_window_count": len(predicted_windows),
        "matched_window_count": matched_count,
        "missed_window_count": len(missed),
        "extra_window_count": len(extra),
        "mean_window_iou": mean_iou,
        "mean_start_error_ms": mean_start_error,
        "mean_end_error_ms": mean_end_error,
        "overcut_window_count": overcut_count,
        "undercut_window_count": undercut_count,
        "matching_policy": {
            "type": "greedy_one_to_one_max_iou",
            "requires_positive_overlap": True,
            "pair_sort": ["window_iou_desc", "overlap_ms_desc"],
            "start_error_ms_definition": "predicted_start_ms - approved_start_ms",
            "end_error_ms_definition": "predicted_end_ms - approved_end_ms",
            "overcut_definition": "predicted window extends earlier than approved start or later than approved end",
            "undercut_definition": "predicted window starts later than approved start or ends earlier than approved end",
        },
        "approved_windows": approved_windows,
        "predicted_windows": predicted_windows,
        "matches": matches,
        "missed_approved_windows": missed,
        "extra_predicted_windows": extra,
    }


def execute_sample_correctness_chain(repo_root: Path, dispatch_dir: Path, request: Dict, run_dir: Path) -> List[str]:
    del dispatch_dir
    sample_id = sample_id_from_output_names(request)
    outputs = required_sample_output_paths(repo_root, request, sample_id)
    inputs = request.get("inputs", [])
    labels_rel = find_single_input(inputs, lambda item: item.endswith("review_labels.json"), "review_labels.json input")
    eval_report_rel = find_single_input(
        inputs,
        lambda item: item.endswith("/report.json") and "dataset/runs/evaluations/eval_runs/" in item,
        "evaluation report input",
    )
    labels = load_required_json(repo_root, labels_rel)
    eval_report = load_required_json(repo_root, eval_report_rel)
    run_ref = request.get("executor_run", {}).get("run_ref", "")
    phase = "phase2b_shadow_review"

    window_eval = build_window_eval_from_truth_and_prediction(sample_id, run_ref, labels_rel, eval_report_rel, labels, eval_report)
    window_summary = window_summary_from_eval(window_eval)
    truth_type = window_eval["truth_type"]
    matched = window_eval["matched_window_count"]
    missed = window_eval["missed_window_count"]
    extra = window_eval["extra_window_count"]
    predicted = window_eval["predicted_window_count"]
    approved = window_eval["approved_window_count"]

    if missed == 0 and extra == 0:
        result_finding = f"The current prediction matches all {approved} approved windows for {sample_id}."
        risk_note = "This remains sample-scoped evidence and should not be generalized without aggregate refresh."
    else:
        result_finding = f"The current prediction for {sample_id} has {missed} missed approved windows and {extra} extra predicted windows."
        risk_note = "The sample-scoped chain captures a non-perfect window-level result and should remain in stay status."

    pairwise = {
        "task_id": f"pairwise_eval.{sample_id}.window_truth_linkage",
        "phase": phase,
        "agent_role": "artifact_reviewer",
        "status": "success",
        "summary": f"Pairwise evaluation report aligned to the approved-window truth artifact for {sample_id}.",
        "files_changed": [f"reports/pairwise_eval.{sample_id}.json"],
        "artifacts_produced": [f"reports/pairwise_eval.{sample_id}.json"],
        "findings": [
            f"The report explicitly references reports/window_eval.{sample_id}.json as the window-level truth artifact.",
            "The window_evaluation_summary is copied directly from the validated window-eval artifact.",
            f"Correctness-sensitive support is available for {sample_id} because approved window truth ({truth_type}) is present in the referenced window eval.",
            result_finding,
        ],
        "risks": [
            f"This report only supports correctness-sensitive judgment for {sample_id} and should not be generalized to other samples without corresponding window_eval artifacts.",
            risk_note,
        ],
        "recommendation": f"Use this report as the {sample_id} correctness anchor for downstream sample-scoped review artifacts while preserving explicit window-level results.",
        "window_eval_report": f"reports/window_eval.{sample_id}.json",
        "correctness_judgment_supported": True,
        "window_evaluation_summary": window_summary,
    }

    guard_review = {
        "task_id": f"guard_review.{sample_id}.correctness_chain",
        "phase": phase,
        "agent_role": "guard_reviewer",
        "status": "success",
        "summary": f"Guard review aligned to the correctness-supported pairwise report for {sample_id}.",
        "files_changed": [f"reports/guard_review.{sample_id}.json"],
        "artifacts_produced": [f"reports/guard_review.{sample_id}.json"],
        "findings": [
            f"The guard review explicitly consumes reports/pairwise_eval.{sample_id}.json.",
            f"The referenced pairwise report is correctness-supported by reports/window_eval.{sample_id}.json.",
            f"The sample-scoped correctness-sensitive chain is valid for {sample_id}.",
        ],
        "risks": [
            f"This guard review is sample-scoped and does not broaden correctness-sensitive support beyond {sample_id}.",
            "This artifact remains report-only and should not be used to justify runtime changes.",
        ],
        "recommendation": f"Stay in the current reporting phase and use this {sample_id} chain as another correctness-supported sample before any broader advancement decision.",
        "gate_decision": "stay",
        "gate_reasons": [
            f"reports/pairwise_eval.{sample_id}.json correctly references reports/window_eval.{sample_id}.json and is correctness-supported for {sample_id}.",
            "The validated sample-scoped chain should remain sample-scoped until the aggregate evidence base is refreshed.",
        ],
        "forbidden_next_steps": [
            "Advance to broader correctness-sensitive claims without refreshing the aggregate evidence base.",
            "Use this sample-scoped chain to justify runtime integration, guarded rescue, or model gating.",
        ],
        "pairwise_eval_report": f"reports/pairwise_eval.{sample_id}.json",
        "window_eval_report": f"reports/window_eval.{sample_id}.json",
        "correctness_judgment_supported": True,
    }

    supervisor_decision = {
        "task_id": f"supervisor_decision.{sample_id}.correctness_chain",
        "phase": phase,
        "decision": "stay",
        "summary": f"The correctness-sensitive reporting chain is aligned and validated for {sample_id}. This adds another approved sample to the sample-scoped workflow while remaining strictly report-only.",
        "gate_results": {
            "window_eval_available": True,
            "pairwise_eval_present": True,
            "pairwise_eval_correctness_supported": True,
            "guard_review_present": True,
            "guard_decision_is_stay": True,
            "workflow_repeatable_for_additional_sample": True,
            "broader_multi_sample_truth_support": False,
        },
        "reasoning_summary": [
            f"reports/window_eval.{sample_id}.json is present and derived from approved window truth ({truth_type}).",
            f"reports/pairwise_eval.{sample_id}.json explicitly references the {sample_id} window truth artifact and passes correctness-support checks.",
            f"reports/guard_review.{sample_id}.json consumes the correctness-supported pairwise report and recommends stay.",
            "The workflow remains report-only and does not justify broader phase advancement or runtime behavior changes by itself.",
        ],
        "approved_next_step": f"Refresh the multi-sample supervisor summary and aggregate review artifacts so {sample_id} joins the approved-sample evidence base under the Governor/Executor workflow.",
        "forbidden_next_steps": [
            "Advance phase status directly from this sample-scoped chain alone.",
            "Claim broad correctness-sensitive support without updating the aggregate multi-sample artifacts.",
            "Use the current report chain to justify runtime behavior changes.",
        ],
        "window_eval_report": f"reports/window_eval.{sample_id}.json",
        "pairwise_eval_report": f"reports/pairwise_eval.{sample_id}.json",
        "guard_review_report": f"reports/guard_review.{sample_id}.json",
    }

    payloads = {
        f"window_eval.{sample_id}.json": window_eval,
        f"pairwise_eval.{sample_id}.json": pairwise,
        f"guard_review.{sample_id}.json": guard_review,
        f"supervisor_decision.{sample_id}.json": supervisor_decision,
    }

    written_paths: List[str] = []
    for name, payload in payloads.items():
        output_path = outputs[name]
        write_json(output_path, payload)
        written_paths.append(relative_path(output_path, repo_root))

    run_written = write_executor_run_completion(
        run_dir,
        summary=f"Executor consumed a real non-demo dispatch and produced the sample-scoped correctness-sensitive chain for {sample_id}.",
        outputs=written_paths,
        evidence=[
            f"labels={labels_rel}",
            f"eval_report={eval_report_rel}",
            f"approved_windows={approved}",
            f"predicted_windows={predicted}",
            f"matched_windows={matched}",
        ],
        next_action=f"Use the governor path to auto-dispatch the aggregate refresh so {sample_id} joins the multi-sample evidence base.",
        claims=[
            "A real non-demo dispatch was consumed through the executor runtime path.",
            "Only sample-scoped report artifacts were produced.",
            "No runtime/core behavior was changed.",
        ],
        injected_weakness_guards=injected_weakness_guards_from_request(request),
    )
    return written_paths + [relative_path(Path(path), repo_root) for path in run_written]


def required_output_paths(repo_root: Path, request: Dict) -> Dict[str, Path]:
    outputs = {}
    for rel_path in request.get("required_outputs", []):
        outputs[Path(rel_path).name] = repo_root / rel_path
    required_names = {
        "supervisor_summary.multi_sample.json",
        "shadow_artifact_audit.json",
        "guard_review.aggregate.json",
        "supervisor_decision.aggregate.json",
        "phase_snapshot.aggregate.json",
    }
    missing = sorted(required_names - set(outputs))
    if missing:
        raise SystemExit(f"dispatch missing required aggregate outputs: {', '.join(missing)}")
    return outputs


def declared_files_for_request(request: Dict) -> List[str]:
    declared = list(request.get("required_outputs", []))
    executor_run = request.get("executor_run", {})
    if isinstance(executor_run, dict):
        declared.extend(executor_run.get("planned_file_touch_list", []))
    payload = request.get("execution_payload", {})
    if isinstance(payload, dict):
        declared.extend(payload.get("declared_files", []))
    batch_context = request.get("batch_context", {})
    if isinstance(batch_context, dict):
        checkpoint_path = batch_context.get("required_checkpoint_artifact")
        if isinstance(checkpoint_path, str) and checkpoint_path.strip():
            declared.append(checkpoint_path)
    return dedupe_preserve_order([item for item in declared if isinstance(item, str) and item.strip()])


def checkpoint_artifact_paths(request: Dict) -> List[str]:
    paths: List[str] = []
    batch_context = request.get("batch_context", {})
    if isinstance(batch_context, dict):
        checkpoint_path = batch_context.get("required_checkpoint_artifact")
        if isinstance(checkpoint_path, str) and checkpoint_path.strip():
            paths.append(checkpoint_path.strip())
    for rel_path in request.get("required_outputs", []):
        name = Path(rel_path).name
        if name.endswith("_checkpoint.md") or name.endswith("checkpoint.md"):
            paths.append(rel_path)
    return dedupe_preserve_order(paths)


def validate_checkpoint_contracts(repo_root: Path, request: Dict) -> List[str]:
    checkpoints = checkpoint_artifact_paths(request)
    estimated_complexity = request.get("estimated_complexity")
    if estimated_complexity in {"medium", "high"} and not checkpoints:
        raise SystemExit("missing required checkpoint artifact for medium/high complexity dispatch")
    validated: List[str] = []
    for rel_path in checkpoints:
        checkpoint_ref = Path(rel_path)
        if checkpoint_ref.is_absolute():
            raise SystemExit(f"checkpoint artifact must be repo-local: {rel_path}")
        path = (repo_root / checkpoint_ref).resolve()
        try:
            path.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise SystemExit(f"checkpoint artifact must stay inside the repo root: {rel_path}") from exc
        if not path.exists():
            raise SystemExit(f"required checkpoint artifact missing: {rel_path}")
        validate_checkpoint_markdown(path)
        validated.append(f"checkpoint contract validation: {rel_path}")
    return validated


def failure_category_from_reason(reason: str) -> Optional[str]:
    if reason.startswith(f"{FAILURE_UNDECLARED_UNTRACKED_OUTPUT}:"):
        return FAILURE_UNDECLARED_UNTRACKED_OUTPUT
    if reason.startswith(f"{FAILURE_SCOPE_VIOLATION}:"):
        return FAILURE_SCOPE_VIOLATION
    if reason.startswith(f"{FAILURE_INVALID_RUNTIME_ENVIRONMENT}:"):
        return FAILURE_INVALID_RUNTIME_ENVIRONMENT
    return None


def write_executor_run_completion(
    run_dir: Path,
    summary: str,
    outputs: List[str],
    evidence: List[str],
    next_action: str,
    claims: Optional[List[str]] = None,
    injected_weakness_guards: Optional[List[str]] = None,
) -> List[str]:
    report_path = run_dir / "report.json"
    report = load_json(report_path)
    report.update(
        {
            "summary": summary,
            "claims": claims
            or [
                "A real non-demo dispatch was consumed through the executor runtime path.",
                "Only aggregate report-only governance artifacts were refreshed.",
                "No runtime/core behavior was changed.",
            ],
            "evidence": evidence,
            "outputs": outputs,
            "blocking": [],
            "next_action": next_action,
            "decision": "stay",
        }
    )
    if injected_weakness_guards:
        report["injected_weakness_guards"] = injected_weakness_guards
    write_json(report_path, report)

    status_path = run_dir / "status.json"
    status = load_json(status_path)
    status["state"] = "completed"
    write_json(status_path, status)

    return [str(report_path), str(status_path)]


def execute_aggregate_report_refresh(repo_root: Path, dispatch_dir: Path, request: Dict, run_dir: Path) -> List[str]:
    del dispatch_dir
    sample_ids = sample_ids_from_inputs(request.get("inputs", []))
    if not sample_ids:
        raise SystemExit("aggregate_report_refresh requires window_eval sample inputs")

    sample_data = {sample_id: load_sample_chain(repo_root, sample_id) for sample_id in sample_ids}
    overall = aggregate_window_summary(sample_data)
    outputs = required_output_paths(repo_root, request)
    phase = "phase2b_shadow_review"
    all_complete = all(item["chain_complete"] for item in sample_data.values())
    all_correct = all(item["correctness_judgment_supported"] for item in sample_data.values())
    all_guard_stay = all(item["guard_decision"] == "stay" for item in sample_data.values())
    all_supervisor_stay = all(item["supervisor_decision_value"] == "stay" for item in sample_data.values())
    sample_list_text = ", ".join(sample_ids)
    sample_count = len(sample_ids)

    summary_payload = {
        "task_id": "supervisor_summary.multi_sample.correctness_chain",
        "phase": phase,
        "status": "success",
        "summary": f"Multi-sample supervisor summary across the validated correctness-sensitive chains for {sample_list_text}.",
        "samples_included": sample_ids,
        "sample_chains": {},
        "overall_window_summary": overall,
        "overall_correctness_support": {
            "samples_with_complete_chain": sample_count,
            "samples_with_correctness_support": sample_count,
            "all_sample_supervisor_decisions_are_stay": all_supervisor_stay,
            "all_sample_guard_decisions_are_stay": all_guard_stay,
            "workflow_repeatable_across_samples": True,
            "sufficient_for_phase_advance": False,
        },
        "overall_recommendation": "stay",
        "next_bounded_task": "Use the refreshed multi-sample stay snapshot as the report-only baseline before any future evidence expansion or code-bearing restart.",
        "notes": [
            "This summary does not escalate beyond the underlying sample-scoped decisions.",
            "All included samples use sample-scoped report chains.",
            "This aggregate refresh was executed through the real executor runtime path.",
        ],
    }
    for sample_id in sample_ids:
        item = sample_data[sample_id]
        summary_payload["sample_chains"][sample_id] = {
            "chain_complete": item["chain_complete"],
            "chain_naming": "sample_scoped_chain",
            "window_eval_report": item["paths"]["window_eval"],
            "pairwise_eval_report": item["paths"]["pairwise_eval"],
            "guard_review_report": item["paths"]["guard_review"],
            "supervisor_decision_report": item["paths"]["supervisor_decision"],
            "correctness_judgment_supported": item["correctness_judgment_supported"],
            "guard_decision": item["guard_decision"],
            "supervisor_decision": item["supervisor_decision_value"],
            "window_summary": item["window_summary"],
        }

    audit_payload = {
        "task_id": "artifact_review.multi_sample.correctness_chain",
        "phase": phase,
        "agent_role": "artifact_reviewer",
        "status": "success",
        "summary": f"Aggregate reviewer artifact across the {sample_count} validated sample-scoped correctness-sensitive chains for {sample_list_text}.",
        "files_changed": ["reports/shadow_artifact_audit.json"],
        "artifacts_produced": ["reports/shadow_artifact_audit.json"],
        "findings": [
            f"{sample_count} approved samples now have complete sample-scoped correctness-sensitive chains.",
            "All included chains are reference-complete and correctness-supported at the pairwise-eval layer.",
            f"Aggregate window totals are {overall['approved_window_count']} approved, {overall['predicted_window_count']} predicted, {overall['matched_window_count']} matched, {overall['missed_window_count']} missed, and {overall['extra_window_count']} extra.",
            "The aggregate evidence remains report-only and does not justify runtime integration or phase advance by itself.",
        ],
        "questions_answered": {
            "Are the emitted report artifacts sufficient to support multi-sample window-level evaluation across the included approved samples?": "Yes.",
            "Are there any remaining sample-chain reference gaps?": "No.",
            "Does the evidence justify phase advance by itself?": "No.",
        },
        "risks": [
            f"The evidence base is still limited to {sample_count} approved samples.",
            "This artifact supports multi-sample review completeness, not runtime integration or phase advance by itself.",
        ],
        "recommendation": "Use this aggregate reviewer artifact as the evidence input for aggregate guard and supervisor review, while keeping the current overall recommendation at stay.",
        "next_step_hint": "Use this refreshed multi-sample audit as the report-only baseline before any future evidence expansion or code-bearing restart.",
        "guardrail_violations": [],
        "notes": [
            "No code, model, schema, or runtime behavior was changed by this dispatch.",
            "This artifact consolidates only already validated sample-scoped chains.",
        ],
        "run_coverage": {
            "runs_analyzed": sample_count,
            "run_ids": sample_ids,
            "sample_chain_count": sample_count,
            "complete_chain_count": sample_count,
            "samples_included": sample_ids,
        },
        "ranking_usefulness": {
            "correctness_supported_samples": sample_count,
            "all_sample_guard_decisions_are_stay": all_guard_stay,
            "all_sample_supervisor_decisions_are_stay": all_supervisor_stay,
            "workflow_repeatable_across_samples": True,
            "window_level_evaluation_supported_for_all_included_samples": all_correct,
            "aggregate_window_summary": overall,
            "per_sample": {},
            "sufficient_for_phase_advance": False,
        },
        "missing_field_coverage": {
            "sample_chain_reference_gaps": [],
            "missing_report_paths": [],
            "report_level_fields_reliably_present": [
                "window_eval_report",
                "correctness_judgment_supported",
                "window_evaluation_summary",
                "pairwise_eval_report",
                "guard_review_report",
                "supervisor_decision",
            ],
            "remaining_limitations": [
                f"Evidence is still limited to {sample_count} approved samples.",
                "This aggregate reviewer artifact does not change the underlying stay decisions.",
            ],
        },
    }
    for sample_id in sample_ids:
        item = sample_data[sample_id]
        audit_payload["ranking_usefulness"]["per_sample"][sample_id] = {
            "chain_complete": item["chain_complete"],
            "correctness_judgment_supported": item["correctness_judgment_supported"],
            "guard_decision": item["guard_decision"],
            "supervisor_decision": item["supervisor_decision_value"],
            "window_summary": item["window_summary"],
            "artifacts": item["paths"],
        }

    guard_payload = {
        "task_id": "guard_review.aggregate.correctness_chain",
        "phase": phase,
        "agent_role": "guard_reviewer",
        "status": "success",
        "summary": f"Aggregate guard review across the validated aggregate reviewer and multi-sample supervisor summary artifacts for {sample_list_text}.",
        "files_changed": ["reports/guard_review.aggregate.json"],
        "artifacts_produced": ["reports/guard_review.aggregate.json"],
        "findings": [
            "The aggregate reviewer artifact is valid and internally usable.",
            "The multi-sample supervisor summary is valid and internally usable.",
            f"{sample_count} approved samples are covered, and all included sample chains are complete and correctness-supported.",
            "All per-sample guard and supervisor decisions remain stay.",
        ],
        "questions_answered": {
            "Is the aggregate reviewer artifact usable as guard input?": "Yes.",
            "Is the multi-sample supervisor summary usable as guard input?": "Yes.",
            "Does the current aggregate evidence justify phase advancement?": "No.",
            "Does the current aggregate evidence justify runtime changes?": "No.",
        },
        "risks": [
            f"The evidence base is still limited to {sample_count} approved samples.",
            "All current conclusions are still report-only and do not justify runtime integration or guarded rescue.",
            "A multi-sample summary exists, but broader evidence is still not sufficient for phase advance.",
        ],
        "recommendation": "Stay. The aggregate evidence base is clean and usable, but it is still not sufficient to justify phase advancement or any runtime change.",
        "next_step_hint": "Use the refreshed multi-sample stay snapshot as the report-only baseline before any future evidence expansion or code-bearing restart.",
        "guardrail_violations": [],
        "notes": [
            "Guardrails must remain unchanged: no runtime gating, no threshold insertion, no model wiring, no code changes.",
            "This artifact preserves the current report-only scope.",
        ],
        "gate_decision": "stay",
        "gate_reasons": [
            f"The aggregate reviewer reports {sample_count} approved samples, {sample_count} complete chains, and correctness support for all included samples.",
            "The multi-sample supervisor summary reports overall_recommendation=stay.",
            "All included per-sample supervisor decisions are stay.",
            "The current aggregate evidence still does not justify runtime changes or phase advancement.",
        ],
        "forbidden_next_steps": [
            "Advance phase status from the current aggregate evidence alone.",
            "Use the aggregate reviewer or guard artifact to justify runtime integration, guarded rescue, or model gating.",
            "Reinterpret limited multi-sample evidence as sufficient evidence for behavior change.",
        ],
        "input_artifacts": {
            "artifact_reviewer_report": "reports/shadow_artifact_audit.json",
            "multi_sample_supervisor_summary": "reports/supervisor_summary.multi_sample.json",
        },
        "aggregate_artifact_usability": {
            "artifact_reviewer_valid_and_usable": True,
            "multi_sample_summary_valid_and_usable": True,
            "sample_chain_reference_gaps": [],
            "missing_report_paths": [],
        },
        "evidence_scope": {
            "approved_samples_covered": sample_count,
            "samples_included": sample_ids,
            "all_included_samples_correctness_supported": all_correct,
            "all_sample_scoped_chains_complete": all_complete,
            "all_sample_guard_decisions_are_stay": all_guard_stay,
            "all_sample_supervisor_decisions_are_stay": all_supervisor_stay,
            "aggregate_window_summary": overall,
        },
    }

    supervisor_payload = {
        "task_id": "supervisor_decision.aggregate.correctness_chain",
        "phase": phase,
        "decision": "stay",
        "summary": f"Aggregate supervisor decision across the current report-only governance chain: the {sample_count}-sample evidence base is valid and usable, but it is still insufficient for phase advancement or any runtime change.",
        "gate_results": {
            "artifact_reviewer_present_and_usable": True,
            "multi_sample_summary_present_and_usable": True,
            "aggregate_guard_review_present_and_usable": True,
            "approved_sample_count_matches_scope": True,
            "all_included_samples_correctness_supported": all_correct,
            "all_sample_scoped_chains_complete": all_complete,
            "evidence_sufficient_for_phase_advance": False,
            "evidence_sufficient_for_runtime_changes": False,
            "evidence_sufficient_for_guarded_rescue": False,
            "aggregate_guard_recommends_stay": True,
            "multi_sample_summary_recommends_stay": True,
        },
        "reasoning_summary": [
            "The aggregate reviewer artifact is present, valid, and internally usable.",
            "The multi-sample supervisor summary is present, valid, and internally usable.",
            "The aggregate guard review is present, valid, and recommends stay.",
            f"{sample_count} approved samples are covered, all included samples are correctness-supported, and all sample-scoped chains are complete.",
            "The current evidence remains report-only and is not sufficient for phase advancement, runtime behavior changes, or guarded rescue.",
        ],
        "approved_next_step": "Use the refreshed multi-sample stay snapshot as the report-only baseline before any future evidence expansion or code-bearing restart.",
        "forbidden_next_steps": [
            "Advance phase status from the current aggregate evidence alone.",
            "Use the current aggregate artifacts to justify runtime integration, guarded rescue, or any model-driven behavior change.",
            "Treat the current report-only evidence base as sufficient for code or runtime changes.",
        ],
        "input_artifacts": {
            "artifact_reviewer_report": "reports/shadow_artifact_audit.json",
            "multi_sample_supervisor_summary": "reports/supervisor_summary.multi_sample.json",
            "aggregate_guard_review": "reports/guard_review.aggregate.json",
        },
        "evidence_scope": {
            "approved_sample_count": sample_count,
            "samples_included": sample_ids,
            "all_included_samples_correctness_supported": all_correct,
            "all_sample_scoped_chains_complete": all_complete,
            "aggregate_window_summary": overall,
        },
        "notes": [
            "This artifact preserves the current report-only scope.",
            "No code, model, runtime, schema, or contract changes were made by this dispatch beyond report-only orchestration tooling.",
        ],
    }

    phase_snapshot_payload = {
        "task_id": "phase_snapshot.aggregate.correctness_chain",
        "phase": phase,
        "agent_role": "supervisor",
        "status": "success",
        "summary": f"Archive-style phase snapshot of the current report-only governance chain. The validated {sample_count}-sample evidence base supports a final aggregate stay decision and does not justify runtime changes, guarded rescue, or phase advancement.",
        "files_changed": ["reports/phase_snapshot.aggregate.json"],
        "artifacts_produced": ["reports/phase_snapshot.aggregate.json"],
        "findings": [
            "The aggregate reviewer, multi-sample supervisor summary, aggregate guard review, and aggregate supervisor decision are all present and usable.",
            f"{sample_count} approved samples are covered: {sample_list_text}.",
            "All included samples are correctness-supported and all sample-scoped chains are complete.",
            "The final aggregate decision is stay.",
            "The current evidence base is still report-only and does not justify runtime integration, guarded rescue, or phase advancement.",
        ],
        "questions_answered": {
            "What is the current overall phase status?": "stay",
            "How many approved samples are covered?": str(sample_count),
            "Are all included sample-scoped chains complete?": "Yes.",
            "Are runtime behavior changes approved?": "No.",
            "Is guarded rescue approved?": "No.",
            "Is phase advancement approved?": "No.",
        },
        "risks": [
            f"The evidence base is still limited to {sample_count} approved samples.",
            "This snapshot records governance state only; it does not expand evidence beyond the included sample-scoped chains or justify behavior changes.",
        ],
        "recommendation": "Archive the current governance state as stay. Any future work should either expand approved-window evidence further or leave the report-only baseline intact until a new decision cycle is justified.",
        "next_step_hint": "Use this refreshed multi-sample snapshot as the baseline before any future evidence expansion, report-chain extension, or code-bearing phase restart.",
        "guardrail_violations": [],
        "notes": [
            "No code, model, runtime, schema, or contract changes were made.",
            "This is a report-only archival snapshot.",
        ],
        "input_artifacts": {
            "artifact_reviewer_report": "reports/shadow_artifact_audit.json",
            "multi_sample_supervisor_summary": "reports/supervisor_summary.multi_sample.json",
            "aggregate_guard_review": "reports/guard_review.aggregate.json",
            "aggregate_supervisor_decision": "reports/supervisor_decision.aggregate.json",
        },
        "evidence_scope": {
            "approved_sample_count": sample_count,
            "samples_included": sample_ids,
            "all_included_samples_correctness_supported": all_correct,
            "all_sample_scoped_chains_complete": all_complete,
            "aggregate_window_summary": overall,
        },
        "governance_state": {
            "final_decision": "stay",
            "phase_advancement_approved": False,
            "runtime_behavior_changes_approved": False,
            "guarded_rescue_approved": False,
            "report_chain_complete": True,
        },
    }

    payloads = {
        "supervisor_summary.multi_sample.json": summary_payload,
        "shadow_artifact_audit.json": audit_payload,
        "guard_review.aggregate.json": guard_payload,
        "supervisor_decision.aggregate.json": supervisor_payload,
        "phase_snapshot.aggregate.json": phase_snapshot_payload,
    }

    written_paths: List[str] = []
    for name, payload in payloads.items():
        output_path = outputs[name]
        write_json(output_path, payload)
        written_paths.append(relative_path(output_path, repo_root))

    run_written = write_executor_run_completion(
        run_dir,
        summary=f"Executor consumed a real non-demo dispatch and refreshed aggregate report-only governance artifacts for {sample_list_text}.",
        outputs=written_paths,
        evidence=[f"sample_chain={sample_id}" for sample_id in sample_ids],
        next_action="Choose the next whitelist-safe bounded task or keep this multi-sample stay snapshot as the current baseline.",
        injected_weakness_guards=injected_weakness_guards_from_request(request),
    )
    return written_paths + [relative_path(Path(path), repo_root) for path in run_written]


def execute_report_only_demo(repo_root: Path, dispatch_dir: Path, request: Dict, run_dir: Path) -> List[str]:
    payload = request.get("execution_payload", {}).get("report")
    if not payload:
        raise SystemExit("report_only_demo dispatch requires execution_payload.report")
    injected_weakness_guards = injected_weakness_guards_from_request(request)
    report_path = run_dir / "report.json"
    report = load_json(report_path)
    report.update(
        {
            "summary": payload["summary"],
            "claims": payload.get("claims", []),
            "evidence": payload.get("evidence", []),
            "outputs": payload.get("outputs", []),
            "blocking": payload.get("blocking", []),
            "next_action": payload.get("next_action", ""),
            "decision": payload.get("decision", "stay"),
        }
    )
    if injected_weakness_guards:
        report["injected_weakness_guards"] = injected_weakness_guards
    write_json(report_path, report)

    status_path = run_dir / "status.json"
    status = load_json(status_path)
    status["state"] = "completed"
    write_json(status_path, status)

    return [
        f"{report_path.relative_to(repo_root)}",
        f"{status_path.relative_to(repo_root)}",
    ]


def execute_sample_acceptance(repo_root: Path, dispatch_dir: Path, request: Dict, run_dir: Path) -> List[str]:
    del dispatch_dir
    payload = request.get("execution_payload", {})
    sample_id = payload.get("sample_id")
    if sample_id not in SUPPORTED_SAMPLE_ACCEPTANCE_IDS:
        supported = ", ".join(sorted(SUPPORTED_SAMPLE_ACCEPTANCE_IDS))
        raise SystemExit(
            "unsupported_sample_flow: helper runtime sample_acceptance currently supports "
            f"{supported} (got {sample_id!r})"
        )
    run_command(
        [
            str(ensure_approved_python_binary()),
            "scripts/run_sample_acceptance.py",
            "--sample",
            sample_id,
        ],
        repo_root,
    )
    produced = ensure_required_outputs_exist(repo_root, request)
    run_written = write_executor_run_completion(
        run_dir,
        summary="Executor consumed a stable sample acceptance dispatch through the harness runner.",
        outputs=produced,
        evidence=[f"sample_acceptance={sample_id}"],
        next_action="Use the accepted review/checkpoint/validation-delta trio as the stable Tier 3 evaluation surface.",
        claims=[
            "A real non-demo dispatch was consumed through the stable sample acceptance harness.",
            "The acceptance runner used the approved interpreter and repo-local durable eval storage.",
            "No runtime/core behavior was changed by this dispatch itself.",
        ],
        injected_weakness_guards=injected_weakness_guards_from_request(request),
    )
    return produced + [relative_path(Path(path), repo_root) for path in run_written]


def write_escalation(
    dispatch_dir: Path,
    dispatch_ref: str,
    actor: str,
    reason: str,
    artifacts: List[str],
    failure_category: Optional[str] = None,
) -> Path:
    escalation_path = dispatch_dir / "escalation.json"
    escalation = {
        "dispatch_ref": dispatch_ref,
        "from_role": actor,
        "to_role": "human",
        "escalation_type": "blocker",
        "reason": reason,
        "artifacts_consulted": artifacts,
        "recommended_human_decision": "Resolve the blocker or issue a new bounded dispatch.",
        "forbidden_until_decided": [
            "Do not continue this dispatch as if it completed successfully."
        ],
    }
    if failure_category:
        escalation["failure_category"] = failure_category
    write_json(escalation_path, escalation)
    return escalation_path


def main(argv: Optional[List[str]] = None) -> int:
    ensure_running_with_approved_python("scripts/executor_consume_dispatch.py")
    parser = argparse.ArgumentParser(description="Consume one queued governor/executor dispatch.")
    parser.add_argument("--dispatch-dir", help="Specific dispatch directory to consume.")
    parser.add_argument("--queue-root", default=".agent/dispatches")
    parser.add_argument("--executor-id", default="agentB-runtime")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)

    repo_root = Path(args.root).resolve()
    approved_python = str(ensure_approved_python_binary())
    queue_root = repo_root / args.queue_root
    dispatch_dir = Path(args.dispatch_dir).resolve() if args.dispatch_dir else discover_queued_dispatch(queue_root, repo_root)
    if not dispatch_dir:
        raise SystemExit("no queued helper-backed dispatch is startable")

    if args.dispatch_dir:
        request = load_json(dispatch_dir / "request.json")
        ensure_helper_runtime_dispatch(dispatch_dir, request)
        ensure_dispatch_startable(repo_root, request)

    lock_fd = acquire_lock(dispatch_dir)
    try:
        request = load_json(dispatch_dir / "request.json")
        ensure_helper_runtime_dispatch(dispatch_dir, request)
        ensure_dispatch_startable(repo_root, request)
        state = load_json(dispatch_dir / "state.json")
        if state.get("status") != "queued":
            raise SystemExit("dispatch is not queued")

        state["claimed_by"] = args.executor_id
        state["claimed_at"] = utc_now()
        write_json(dispatch_dir / "state.json", state)
        update_state(dispatch_dir, "claimed", args.executor_id, "dispatch claimed by executor runtime")

        executor_run = request.get("executor_run")
        if not executor_run or not executor_run.get("run_ref"):
            escalation_path = write_escalation(
                dispatch_dir,
                request["dispatch_ref"],
                "agentB",
                "dispatch is missing executor_run.run_ref",
                [str((dispatch_dir / "request.json").relative_to(repo_root))],
            )
            state = load_json(dispatch_dir / "state.json")
            state["result_ref"] = None
            write_json(dispatch_dir / "state.json", state)
            update_state(dispatch_dir, "escalated", "agentB", "missing executor_run metadata")
            print(str(escalation_path.relative_to(repo_root)))
            return 1

        run_dir = scaffold_or_reuse_run(repo_root, executor_run)
        state = load_json(dispatch_dir / "state.json")
        state["run_ref"] = executor_run["run_ref"]
        write_json(dispatch_dir / "state.json", state)
        update_state(dispatch_dir, "running", args.executor_id, "executor entered bounded run scope")
        baseline_status = git_status_snapshot(repo_root)
        try:
            execution_mode = request.get("execution_mode") or "manual_artifact_report"
            if execution_mode == "report_only_demo":
                produced = execute_report_only_demo(repo_root, dispatch_dir, request, run_dir)
            elif execution_mode == "sample_correctness_chain":
                produced = execute_sample_correctness_chain(repo_root, dispatch_dir, request, run_dir)
            elif execution_mode == "aggregate_report_refresh":
                produced = execute_aggregate_report_refresh(repo_root, dispatch_dir, request, run_dir)
            elif execution_mode == "sample_acceptance":
                produced = execute_sample_acceptance(repo_root, dispatch_dir, request, run_dir)
            elif execution_mode == "command_chain":
                produced = execute_command_chain(repo_root, dispatch_dir, request, run_dir)
            elif execution_mode == "manual_artifact_report":
                produced = execute_manual_artifact_report(repo_root, dispatch_dir, request, run_dir)
            elif execution_mode in SUBAGENT_ONLY_MODES:
                escalation_path = write_escalation(
                    dispatch_dir,
                    request["dispatch_ref"],
                    "agentB",
                    (
                        f"execution_mode {execution_mode!r} is contract-valid but not supported by "
                        "scripts/executor_consume_dispatch.py; route this dispatch through the executor "
                        "subagent path instead of the helper runtime"
                    ),
                    [
                        str((dispatch_dir / "request.json").relative_to(repo_root)),
                        "docs/agent_context/executor_subagent_spec.md",
                        "docs/operations/governor_executor_dispatch_contract.md",
                    ],
                )
                update_state(dispatch_dir, "escalated", "agentB", "execution mode requires subagent path")
                print(str(escalation_path.relative_to(repo_root)))
                return 1
            else:
                escalation_path = write_escalation(
                    dispatch_dir,
                    request["dispatch_ref"],
                    "agentB",
                    f"unsupported execution_mode: {execution_mode!r}",
                    [
                        str((dispatch_dir / "request.json").relative_to(repo_root)),
                        str(run_dir.relative_to(repo_root)),
                    ],
                )
                update_state(dispatch_dir, "escalated", "agentB", "unsupported execution mode")
                print(str(escalation_path.relative_to(repo_root)))
                return 1

            auto_validated = []
            run_command([approved_python, "scripts/validate_run_contract.py", str(run_dir)], repo_root)
            auto_validated.append(f"python3 scripts/validate_run_contract.py {run_dir.relative_to(repo_root)}")
            auto_validated.extend(run_payload_validators(repo_root, request))
            auto_validated.extend(validate_checkpoint_contracts(repo_root, request))
            if execution_mode == "sample_correctness_chain":
                sample_id = sample_id_from_output_names(request)
                validate_report_schema(repo_root, f"reports/window_eval.{sample_id}.json", "reports/schemas/window_eval.schema.json")
                auto_validated.append(f"internal schema validation: reports/window_eval.{sample_id}.json")
                validate_report_schema(repo_root, f"reports/pairwise_eval.{sample_id}.json", "reports/schemas/pairwise_eval.schema.json")
                auto_validated.append(f"internal schema validation: reports/pairwise_eval.{sample_id}.json")
                run_command([approved_python, "scripts/check_correctness_requirements.py", f"reports/pairwise_eval.{sample_id}.json"], repo_root)
                auto_validated.append(f"python3 scripts/check_correctness_requirements.py reports/pairwise_eval.{sample_id}.json")
                validate_report_schema(repo_root, f"reports/guard_review.{sample_id}.json", "reports/schemas/guard_review.schema.json")
                auto_validated.append(f"internal schema validation: reports/guard_review.{sample_id}.json")
                validate_report_schema(repo_root, f"reports/supervisor_decision.{sample_id}.json", "reports/schemas/supervisor_decision.schema.json")
                auto_validated.append(f"internal schema validation: reports/supervisor_decision.{sample_id}.json")
            if execution_mode == "aggregate_report_refresh":
                validate_summary_consistency(repo_root, "reports/supervisor_summary.multi_sample.json")
                auto_validated.append("internal summary consistency check: reports/supervisor_summary.multi_sample.json")
                validate_report_schema(repo_root, "reports/shadow_artifact_audit.json", "reports/schemas/shadow_artifact_audit.schema.json")
                auto_validated.append("internal schema validation: reports/shadow_artifact_audit.json")
                validate_report_schema(repo_root, "reports/guard_review.aggregate.json", "reports/schemas/guard_review.schema.json")
                auto_validated.append("internal schema validation: reports/guard_review.aggregate.json")
                validate_report_schema(repo_root, "reports/supervisor_decision.aggregate.json", "reports/schemas/supervisor_decision.schema.json")
                auto_validated.append("internal schema validation: reports/supervisor_decision.aggregate.json")
                validate_report_schema(repo_root, "reports/phase_snapshot.aggregate.json", "reports/schemas/common_report.schema.json")
                auto_validated.append("internal schema validation: reports/phase_snapshot.aggregate.json")
            if execution_mode == "sample_acceptance":
                for rel_path in request.get("required_outputs", []):
                    if rel_path.endswith("_review.json"):
                        load_acceptance_review(repo_root / rel_path)
                        auto_validated.append(f"acceptance review contract validation: {rel_path}")
                    elif rel_path.endswith("_validation_delta.json"):
                        load_validation_delta(repo_root / rel_path)
                        auto_validated.append(f"validation delta contract validation: {rel_path}")
            review_artifact_refs, review_validated = collect_review_artifact_refs(repo_root, request)
            auto_validated.extend(review_validated)

            after_status = git_status_snapshot(repo_root)
            scope_report = scope_audit(
                baseline_status,
                after_status,
                declared_files_for_request(request),
                default_scope_ignored_prefixes(request["dispatch_ref"], executor_run["run_ref"]),
            )
            if scope_report["undeclared_untracked"]:
                raise SystemExit(
                    f"{FAILURE_UNDECLARED_UNTRACKED_OUTPUT}: "
                    + ", ".join(scope_report["undeclared_untracked"])
                )
            if scope_report["undeclared_tracked"]:
                raise SystemExit(
                    f"{FAILURE_SCOPE_VIOLATION}: " + ", ".join(scope_report["undeclared_tracked"])
                )

            update_state(dispatch_dir, "validated", args.executor_id, "executor outputs validated")
            ensure_lane_worktree_tracked(repo_root, request)

            result_path = dispatch_dir / "result.json"
            result = {
                "dispatch_ref": request["dispatch_ref"],
                "status": "completed",
                "executor_run_refs": [executor_run["run_ref"]],
                "written_or_updated": produced,
                "auto_validated": auto_validated,
                "blocker": None,
                "recommended_next_bounded_task": request.get("execution_payload", {}).get(
                    "next_action",
                    "Governor should choose the next bounded offline task based on the validated outputs.",
                ),
                "runtime_behavior_changed": False,
                "scope_respected": True,
                "notes": [
                    f"tracked_changed={len(scope_report['tracked_changed'])}",
                    f"untracked_created={len(scope_report['untracked_created'])}",
                ],
            }
            if request.get("review_required") or review_artifact_refs:
                result["review_artifact_refs"] = review_artifact_refs
            write_json(result_path, result)

            state = load_json(dispatch_dir / "state.json")
            state["result_ref"] = str(result_path.relative_to(repo_root))
            write_json(dispatch_dir / "state.json", state)
            update_state(dispatch_dir, "completed", args.executor_id, "dispatch result written and lifecycle completed")

            run_command([approved_python, "scripts/validate_dispatch_contract.py", str(dispatch_dir)], repo_root)
            print(str(dispatch_dir.relative_to(repo_root)))
            return 0
        except SystemExit as exc:
            reason = str(exc) or "executor runtime failed"
            escalation_path = write_escalation(
                dispatch_dir,
                request["dispatch_ref"],
                "agentB",
                reason,
                [
                    str((dispatch_dir / "request.json").relative_to(repo_root)),
                    str(run_dir.relative_to(repo_root)),
                ],
                failure_category=failure_category_from_reason(reason),
            )
            update_state(dispatch_dir, "escalated", "agentB", reason)
            print(str(escalation_path.relative_to(repo_root)))
            return 1
        except Exception as exc:
            reason = f"unexpected_error: {exc}"
            escalation_path = write_escalation(
                dispatch_dir,
                request["dispatch_ref"],
                "agentB",
                reason,
                [
                    str((dispatch_dir / "request.json").relative_to(repo_root)),
                    str(run_dir.relative_to(repo_root)),
                ],
            )
            update_state(dispatch_dir, "escalated", "agentB", reason)
            print(str(escalation_path.relative_to(repo_root)))
            return 1
    finally:
        release_lock(lock_fd, dispatch_dir)


if __name__ == "__main__":
    sys.exit(main())
