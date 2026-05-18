#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_FILES = [
    "README.md",
    "index.html",
    "src/app.js",
    "src/state.js",
    "src/entries.js",
    "src/pets.js",
    "src/analytics.js",
    "src/storage.js",
    "src/ui.js",
    "src/fixtures.js",
    "src/styles.css",
    "data/sample-pets.json",
    "data/sample-entries.json",
    "tests/product-validation.js",
]


def read_text(root: Path, rel_path: str) -> str:
    return (root / rel_path).read_text(encoding="utf-8")


def line_count(root: Path, rel_path: str) -> int:
    return len(read_text(root, rel_path).splitlines())


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str = "") -> None:
    checks.append({"name": name, "status": "pass" if passed else "fail", "detail": detail})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--min-lines", type=int, default=3000)
    parser.add_argument("--require-utilities", action="store_true")
    parser.add_argument("--require-routines", action="store_true")
    parser.add_argument("--require-portfolio", action="store_true")
    args = parser.parse_args()

    root = Path(args.repo_root)
    report_path = root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    line_counts: dict[str, int] = {}

    for rel_path in REQUIRED_FILES:
        exists = (root / rel_path).exists()
        add_check(checks, f"file_exists:{rel_path}", exists)
        if not exists:
            failures.append(f"missing {rel_path}")
            continue
        line_counts[rel_path] = line_count(root, rel_path)

    total_lines = sum(line_counts.values())
    add_check(
        checks,
        "product_scale_line_count",
        total_lines >= args.min_lines,
        f"{total_lines} lines across required files",
    )
    if total_lines < args.min_lines:
        failures.append(f"expected at least {args.min_lines} lines, found {total_lines}")

    if (root / "index.html").exists():
        index = read_text(root, "index.html")
        for marker in [
            "data-app-shell",
            "view-dashboard",
            "view-timeline",
            "view-pets",
            "view-insights",
            "data-entry-form",
            "data-filter-species",
            "import-export-panel",
        ]:
            passed = marker in index
            add_check(checks, f"index_marker:{marker}", passed)
            if not passed:
                failures.append(f"index.html missing {marker}")

    js_markers = {
        "src/app.js": ["loadState", "renderAll", "bindNavigation"],
        "src/state.js": ["localStorage", "exportState", "resetState"],
        "src/entries.js": ["createEntryFromForm", "visibleEntries", "entryMatchesFilters", "userEntryRank"],
        "src/ui.js": ["renderTimeline", "renderComposer", "bindActions", "renderInsights"],
        "src/analytics.js": ["calculateMetrics", "insightsForState"],
        "src/storage.js": ["copyText", "downloadJson"],
        "src/fixtures.js": ["samplePets", "sampleEntries", "entry-150"],
    }
    for rel_path, markers in js_markers.items():
        if not (root / rel_path).exists():
            continue
        source = read_text(root, rel_path)
        for marker in markers:
            passed = marker in source
            add_check(checks, f"{rel_path}:{marker}", passed)
            if not passed:
                failures.append(f"{rel_path} missing {marker}")

    data_counts: dict[str, int] = {}
    for rel_path, minimum in [("data/sample-pets.json", 10), ("data/sample-entries.json", 150)]:
        if not (root / rel_path).exists():
            continue
        try:
            payload = json.loads(read_text(root, rel_path))
        except json.JSONDecodeError as exc:
            failures.append(f"{rel_path} invalid JSON: {exc}")
            add_check(checks, f"{rel_path}:valid_json", False, str(exc))
            continue
        count = len(payload) if isinstance(payload, list) else 0
        data_counts[rel_path] = count
        passed = count >= minimum
        add_check(checks, f"{rel_path}:minimum_records", passed, f"{count} records")
        if not passed:
            failures.append(f"{rel_path} expected at least {minimum} records, found {count}")

    if args.require_utilities:
        utility_markers = {
            "index.html": ["data-import-json", "data-action=\"import-json\""],
            "src/state.js": ["importState", "assertRecordList"],
            "src/ui.js": ["importState", "data-action=\"import-json\""],
            "src/styles.css": ["import-tools"],
            "README.md": ["Diary utilities"],
            "tests/product-validation.js": ["utilityReadiness"],
        }
        for rel_path, markers in utility_markers.items():
            if not (root / rel_path).exists():
                failures.append(f"{rel_path} missing for utility validation")
                add_check(checks, f"utility_file:{rel_path}", False)
                continue
            source = read_text(root, rel_path)
            for marker in markers:
                passed = marker in source
                add_check(checks, f"utility_marker:{rel_path}:{marker}", passed)
                if not passed:
                    failures.append(f"{rel_path} missing utility marker {marker}")

    if args.require_routines:
        routine_markers = {
            "index.html": ["view-routines", "data-routine-board"],
            "src/state.js": ["routines:"],
            "src/ui.js": ["renderRoutineBoard"],
            "src/styles.css": ["routine-board"],
            "README.md": ["Care routines"],
        }
        for rel_path, markers in routine_markers.items():
            if not (root / rel_path).exists():
                failures.append(f"{rel_path} missing for routine validation")
                add_check(checks, f"routine_file:{rel_path}", False)
                continue
            source = read_text(root, rel_path)
            for marker in markers:
                passed = marker in source
                add_check(checks, f"routine_marker:{rel_path}:{marker}", passed)
                if not passed:
                    failures.append(f"{rel_path} missing routine marker {marker}")

    if args.require_portfolio:
        portfolio_markers = {
            "README.md": ["Demo readiness checklist", "Portfolio narrative"],
            "docs/product-spec.md": ["Product promise", "Demo acceptance"],
            "tests/product-validation.js": ["portfolio readiness"],
        }
        for rel_path, markers in portfolio_markers.items():
            if not (root / rel_path).exists():
                failures.append(f"{rel_path} missing for portfolio validation")
                add_check(checks, f"portfolio_file:{rel_path}", False)
                continue
            source = read_text(root, rel_path)
            for marker in markers:
                passed = marker in source
                add_check(checks, f"portfolio_marker:{rel_path}:{marker}", passed)
                if not passed:
                    failures.append(f"{rel_path} missing portfolio marker {marker}")

    report = {
        "schema_version": "corgi.pet_diary_product_validation.v1",
        "status": "pass" if not failures else "fail",
        "total_lines": total_lines,
        "min_lines": args.min_lines,
        "require_utilities": bool(args.require_utilities),
        "require_routines": bool(args.require_routines),
        "require_portfolio": bool(args.require_portfolio),
        "line_counts": line_counts,
        "data_counts": data_counts,
        "checks": checks,
        "failures": failures,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
