#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

TRANSITION_TYPES = {"continue_internal", "interrupt_human"}
ALLOWED_HUMAN_STOP_REASONS = {
    "merge_ready",
    "lane_complete",
    "material_blocker",
    "missing_permission",
    "missing_resource",
    "human_decision_required",
    "safety_boundary",
}
BLOCKER_STOP_REASONS = {
    "material_blocker",
    "missing_permission",
    "missing_resource",
    "human_decision_required",
    "safety_boundary",
}
ALLOWED_CONTINUE_ACTIONS = {
    "emit_dispatch",
    "route_review",
    "integrate_candidate",
    "rerun_validation",
    "structured_blocker",
    "replan",
}
DEFAULT_COMPLETION_MODE = "merge_ready_only"
SUPPORTED_COMPLETION_MODES = {DEFAULT_COMPLETION_MODE}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def relative_path(path: Path, repo_root: Path) -> str:
    return str(path.resolve().relative_to(repo_root.resolve()))


def governor_state_dir(repo_root: Path, lane: str) -> Path:
    return repo_root / ".agent" / "governor" / lane


def proposed_transition_path(repo_root: Path, lane: str) -> Path:
    return governor_state_dir(repo_root, lane) / "proposed_transition.json"


def lane_completion_rules_path(repo_root: Path) -> Path:
    return repo_root / "docs" / "governance" / "lane_completion_rules.json"


def load_lane_completion_rules(repo_root: Path) -> Dict[str, Any]:
    path = lane_completion_rules_path(repo_root)
    if not path.exists():
        return {
            "default_completion_mode": DEFAULT_COMPLETION_MODE,
            "lanes": {},
        }
    payload = load_json(path)
    if not isinstance(payload, dict):
        return {
            "default_completion_mode": DEFAULT_COMPLETION_MODE,
            "lanes": {},
        }
    return payload


def lane_completion_rule(repo_root: Path, lane: str) -> Dict[str, Any]:
    rules = load_lane_completion_rules(repo_root)
    lane_rules = rules.get("lanes")
    lane_payload = lane_rules.get(lane) if isinstance(lane_rules, dict) else {}
    if not isinstance(lane_payload, dict):
        lane_payload = {}

    mode = lane_payload.get("completion_mode", rules.get("default_completion_mode", DEFAULT_COMPLETION_MODE))
    if mode not in SUPPORTED_COMPLETION_MODES:
        mode = DEFAULT_COMPLETION_MODE

    return {
        "completion_mode": mode,
        "rules_ref": relative_path(lane_completion_rules_path(repo_root), repo_root),
    }


def _string_list(values: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    for value in values or []:
        if not isinstance(value, str):
            continue
        stripped = value.strip()
        if stripped and stripped not in out:
            out.append(stripped)
    return out


def build_transition_payload(
    *,
    repo_root: Path,
    lane: str,
    source: str,
    transition: str,
    requested_stop_reason: Optional[str] = None,
    next_action_kind: Optional[str] = None,
    next_action_ref: Optional[str] = None,
    next_action_summary: Optional[str] = None,
    dispatch_ref: Optional[str] = None,
    decision_ref: Optional[str] = None,
    evidence_refs: Optional[List[str]] = None,
    blocker: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if transition not in TRANSITION_TYPES:
        raise ValueError(f"transition must be one of: {', '.join(sorted(TRANSITION_TYPES))}")

    payload: Dict[str, Any] = {
        "lane": lane,
        "source": source,
        "created_at": utc_now(),
        "transition": transition,
        "requested_stop_reason": None,
        "dispatch_ref": dispatch_ref,
        "decision_ref": decision_ref,
        "evidence_refs": _string_list(evidence_refs),
        "next_action": None,
        "blocker": None,
        "completion_rule": lane_completion_rule(repo_root, lane),
    }

    if transition == "continue_internal":
        if next_action_kind not in ALLOWED_CONTINUE_ACTIONS:
            raise ValueError(f"continue_internal requires next_action.kind in: {', '.join(sorted(ALLOWED_CONTINUE_ACTIONS))}")
        payload["next_action"] = {
            "kind": next_action_kind,
            "ref": next_action_ref.strip() if isinstance(next_action_ref, str) and next_action_ref.strip() else None,
            "summary": next_action_summary.strip()
            if isinstance(next_action_summary, str) and next_action_summary.strip()
            else "",
        }
        return payload

    if requested_stop_reason not in ALLOWED_HUMAN_STOP_REASONS:
        raise ValueError(
            "requested_stop_reason must be one of: " + ", ".join(sorted(ALLOWED_HUMAN_STOP_REASONS))
        )
    payload["requested_stop_reason"] = requested_stop_reason

    if requested_stop_reason in BLOCKER_STOP_REASONS:
        if not isinstance(blocker, dict):
            raise ValueError("blocker metadata is required for blocker-style human interrupts")
        category = blocker.get("category")
        summary = blocker.get("summary")
        artifact_refs = _string_list(blocker.get("artifact_refs"))
        forbidden_until_resolved = _string_list(blocker.get("forbidden_until_resolved"))
        if not isinstance(category, str) or not category.strip():
            raise ValueError("blocker.category must be a non-empty string")
        if not isinstance(summary, str) or not summary.strip():
            raise ValueError("blocker.summary must be a non-empty string")
        if not artifact_refs:
            raise ValueError("blocker.artifact_refs must contain at least one artifact ref")
        payload["blocker"] = {
            "category": category.strip(),
            "summary": summary.strip(),
            "artifact_refs": artifact_refs,
            "forbidden_until_resolved": forbidden_until_resolved,
        }

    return payload


def record_transition(repo_root: Path, payload: Dict[str, Any]) -> Path:
    lane = payload["lane"]
    path = proposed_transition_path(repo_root, lane)
    write_json(path, payload)
    return path


def load_transition(repo_root: Path, lane: str) -> Optional[Dict[str, Any]]:
    path = proposed_transition_path(repo_root, lane)
    if not path.exists():
        return None
    payload = load_json(path)
    if payload.get("lane") != lane:
        raise SystemExit("proposed_transition.json lane does not match requested lane")
    return payload
