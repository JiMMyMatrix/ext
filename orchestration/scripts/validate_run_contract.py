#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

ORCHESTRATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(ORCHESTRATION_ROOT) not in sys.path:
    sys.path.insert(0, str(ORCHESTRATION_ROOT))

from orchestration.harness.artifacts import ArtifactContractError, load_review_artifact


TASK_REQUIRED = [
    "run_ref",
    "objective",
    "scope",
    "non_goals",
    "stop_conditions",
]

STATUS_REQUIRED = [
    "run_ref",
    "current_branch",
    "git_status_short",
    "planned_file_touch_list",
    "read_list",
    "produce_list",
    "scope",
    "non_goals",
    "stop_conditions",
]

REPORT_REQUIRED = [
    "run_ref",
    "summary",
    "claims",
    "evidence",
    "outputs",
    "blocking",
    "next_action",
]

DECISION_VALUES = {"advance", "stay", "block"}


def load_json(path: Path) -> Dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def missing_fields(payload: Dict, required: List[str]) -> List[str]:
    return [field for field in required if field not in payload]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a run contract directory.")
    parser.add_argument("run_dir")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.is_dir():
        print(f"not a directory: {run_dir}", file=sys.stderr)
        return 2

    task_path = run_dir / "task.json"
    status_path = run_dir / "status.json"
    report_path = run_dir / "report.json"
    review_path = run_dir / "review.json"

    failures = []

    for path in [task_path, status_path, report_path]:
        if not path.exists():
            failures.append(f"missing file: {path.name}")

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    try:
        task = load_json(task_path)
        status = load_json(status_path)
        report = load_json(report_path)
    except json.JSONDecodeError as exc:
        print(f"invalid json: {exc}", file=sys.stderr)
        return 1

    for field in missing_fields(task, TASK_REQUIRED):
        failures.append(f"task.json missing field: {field}")

    for field in missing_fields(status, STATUS_REQUIRED):
        failures.append(f"status.json missing field: {field}")

    for field in missing_fields(report, REPORT_REQUIRED):
        failures.append(f"report.json missing field: {field}")

    if task.get("run_ref") != status.get("run_ref") or task.get("run_ref") != report.get("run_ref"):
        failures.append("run_ref mismatch across task/status/report")

    for list_field in [
        "non_goals",
        "stop_conditions",
        "planned_file_touch_list",
        "read_list",
        "produce_list",
        "claims",
        "evidence",
        "outputs",
        "blocking",
    ]:
        payload = status if list_field in status else report
        if list_field in task:
            payload = task
        value = payload.get(list_field)
        if value is not None and not isinstance(value, list):
            failures.append(f"{list_field} must be a list")

    decision = report.get("decision")
    if decision is not None and decision not in DECISION_VALUES:
        failures.append("report.json decision must be one of: advance, stay, block")

    review_required = task.get("review_required")
    if review_required is not None and not isinstance(review_required, bool):
        failures.append("task.json review_required must be a boolean when present")
    if review_required is True and not review_path.exists():
        failures.append("review.json is required when task.json review_required is true")
    if review_path.exists():
        try:
            load_review_artifact(review_path)
        except ArtifactContractError as exc:
            failures.append(str(exc))

    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1

    print("run contract valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
