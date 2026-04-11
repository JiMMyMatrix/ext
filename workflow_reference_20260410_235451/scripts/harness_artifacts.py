#!/usr/bin/env python3
"""Minimal contract-aware artifact readers for the harness."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.harness_runtime import read_json


WINDOW_EVAL_REQUIRED_KEY_PATHS = [
    "approved_window_count",
    "predicted_window_count",
    "matched_window_count",
    "missed_window_count",
    "extra_window_count",
    "mean_window_iou",
    "approved_windows",
    "predicted_windows",
    "missed_approved_windows",
    "extra_predicted_windows",
]

ACCEPTANCE_REVIEW_REQUIRED_KEY_PATHS = [
    "task_id",
    "phase",
    "status",
    "summary",
    "files_changed",
    "artifacts_produced",
    "truth_surface",
    "sample_summaries",
    "recommendation",
]

VALIDATION_DELTA_REQUIRED_KEY_PATHS = [
    "task_id",
    "before",
    "after",
    "delta",
]

REVIEW_ARTIFACT_REQUIRED_KEY_PATHS = [
    "dispatch_ref",
    "reviewer_role",
    "verdict",
    "validator_assessment",
    "scope_assessment",
    "findings",
    "residual_risks",
    "recommendation",
]

REVIEW_ARTIFACT_FORBIDDEN_CONTROL_FIELDS = {
    "decision",
    "recommended_next_action",
    "recommended_next_bounded_task",
    "next_action",
    "merge_ready",
    "scope_reservations",
    "depends_on_dispatches",
    "execution_mode",
    "claimed_by",
    "result_ref",
    "review_ref",
}

CHECKPOINT_REQUIRED_SECTIONS = [
    "# Checkpoint:",
    "## Status",
    "## Completed items",
    "## Remaining items (if partial)",
    "## Artifacts produced",
    "## Issues encountered",
    "## Executor assessment",
]


class ArtifactContractError(ValueError):
    """Raised when an artifact fails a minimal harness contract."""


def _error(contract_name: str, path: Path, key_path: str, detail: str) -> ArtifactContractError:
    return ArtifactContractError(f"{contract_name} contract failed for {path}: {key_path}: {detail}")


def _read_key_path(payload: Any, key_path: str, contract_name: str, path: Path) -> Any:
    current = payload
    traversed: list[str] = []
    for key in key_path.split("."):
        traversed.append(key)
        current_path = ".".join(traversed)
        if not isinstance(current, dict):
            raise _error(contract_name, path, current_path, "expected object while traversing")
        if key not in current:
            raise _error(contract_name, path, current_path, "missing required key")
        current = current[key]
    return current


def load_json_contract(path: Path, contract_name: str, required_key_paths: Iterable[str]) -> dict[str, Any]:
    payload = read_json(path)
    for key_path in required_key_paths:
        _read_key_path(payload, key_path, contract_name, path)
    return payload


def load_window_eval(path: Path) -> dict[str, Any]:
    return load_json_contract(path, "window_eval", WINDOW_EVAL_REQUIRED_KEY_PATHS)


def load_acceptance_review(path: Path) -> dict[str, Any]:
    return load_json_contract(path, "acceptance_review", ACCEPTANCE_REVIEW_REQUIRED_KEY_PATHS)


def load_validation_delta(path: Path) -> dict[str, Any]:
    return load_json_contract(path, "validation_delta", VALIDATION_DELTA_REQUIRED_KEY_PATHS)


def load_review_artifact(path: Path) -> dict[str, Any]:
    payload = load_json_contract(path, "review_artifact", REVIEW_ARTIFACT_REQUIRED_KEY_PATHS)
    verdict = payload.get("verdict")
    if verdict not in {"pass", "request_changes", "inconclusive"}:
        raise _error("review_artifact", path, "verdict", "must be pass, request_changes, or inconclusive")
    for field in ["validator_assessment", "scope_assessment", "findings", "residual_risks"]:
        value = payload.get(field)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise _error("review_artifact", path, field, "expected list of strings")
    recommendation = payload.get("recommendation")
    if not isinstance(recommendation, str) or not recommendation.strip():
        raise _error("review_artifact", path, "recommendation", "expected non-empty string")
    forbidden = sorted(REVIEW_ARTIFACT_FORBIDDEN_CONTROL_FIELDS.intersection(payload))
    if forbidden:
        raise _error(
            "review_artifact",
            path,
            ",".join(forbidden),
            "review artifact must stay advisory-only and must not contain workflow control fields",
        )
    return payload


def build_review_labels_from_window_eval(truth_report_path: Path, video_path: Path) -> dict[str, Any]:
    truth_report = load_window_eval(truth_report_path)
    approved_windows = truth_report.get("approved_windows", [])
    if not isinstance(approved_windows, list):
        raise _error("window_eval", truth_report_path, "approved_windows", "expected list")
    return {
        "metadata": {
            "video": str(video_path),
            "labels_schema_version": 4,
            "sample_review_decision": "pending",
            "merge_interval_ms": 7000,
            "clip_duration_target_ms": 10000,
            "clip_duration_is_soft": True,
            "source_truth_report": str(truth_report_path),
        },
        "events": [],
        "highlight_windows": [],
        "approved_highlights": [],
        "approved_highlight_windows": [
            {
                "start_ms": int(row["start_ms"]),
                "end_ms": int(row["end_ms"]),
            }
            for row in approved_windows
            if isinstance(row, dict) and "start_ms" in row and "end_ms" in row
        ],
        "human_assertions": {
            "must_include_windows": [],
            "must_exclude_windows": [],
        },
    }


def validate_checkpoint_markdown(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for section in CHECKPOINT_REQUIRED_SECTIONS:
        if section not in text:
            raise _error("checkpoint_markdown", path, section, "missing required section")
    return text
