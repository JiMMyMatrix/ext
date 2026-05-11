#!/usr/bin/env python3
"""Validate that the Pet Life Diary app exposes and applies a species filter."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def validate(repo_root: Path) -> dict[str, Any]:
    app_path = repo_root / "src" / "app.js"
    index_path = repo_root / "index.html"
    failures: list[str] = []
    app_source = app_path.read_text(encoding="utf-8") if app_path.exists() else ""
    index_source = index_path.read_text(encoding="utf-8") if index_path.exists() else ""

    if 'id="species-filter"' not in index_source:
        failures.append("index.html is missing the species filter control")
    if "visibleEntries" not in app_source:
        failures.append("src/app.js is missing the visibleEntries filter helper")
    if 'querySelector("#species-filter")' not in app_source:
        failures.append("src/app.js does not read the species filter control")
    if "addEventListener(\"change\"" not in app_source:
        failures.append("src/app.js does not re-render when the filter changes")
    if ".filter((entry) => entry.species === selectedSpecies)" not in app_source:
        failures.append("src/app.js does not filter entries by selected species")
    if "item.dataset.species = entry.species" not in app_source:
        failures.append("src/app.js does not mark rendered entries with species data")

    visible_helper = re.search(
        r"function visibleEntries\(\)\s*\{(?P<body>.*?)\n\}",
        app_source,
        re.DOTALL,
    )
    if not visible_helper:
        failures.append("src/app.js visibleEntries helper could not be inspected")
    elif "selectedSpecies === \"all\"" not in visible_helper.group("body"):
        failures.append("visibleEntries does not preserve all entries for the all filter")

    return {
        "schema_version": "corgi.pet-diary-filter-validation.v1",
        "status": "pass" if not failures else "fail",
        "checks": {
            "has_filter_control": 'id="species-filter"' in index_source,
            "has_filter_helper": "visibleEntries" in app_source,
            "has_filter_change_listener": "addEventListener(\"change\"" in app_source,
            "filters_by_species": ".filter((entry) => entry.species === selectedSpecies)" in app_source,
            "renders_species_metadata": "item.dataset.species = entry.species" in app_source,
        },
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Pet Life Diary species filter behavior.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report_path = repo_root / args.report
    payload = validate(repo_root)
    write_json(report_path, payload)
    if payload["status"] != "pass":
        raise SystemExit("; ".join(payload["failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
