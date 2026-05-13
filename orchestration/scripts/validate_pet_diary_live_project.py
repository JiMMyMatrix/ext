#!/usr/bin/env python3
"""Lightweight validation for live Pet Life Diary scratch-project steps."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def add_check(checks: list[dict[str, Any]], failures: list[str], name: str, passed: bool, detail: str = "") -> None:
    checks.append({"name": name, "status": "pass" if passed else "fail", "detail": detail})
    if not passed:
        failures.append(f"{name}: {detail or 'failed'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a live Pet Life Diary scratch project.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--required-output", action="append", default=[])
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    report_path = repo_root / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    required_outputs = sorted(dict.fromkeys(args.required_output))
    for rel_path in required_outputs:
        path = repo_root / rel_path
        exists = path.exists() and path.is_file()
        add_check(checks, failures, f"required_output_exists:{rel_path}", exists)
        if exists:
            size = path.stat().st_size
            add_check(checks, failures, f"required_output_non_empty:{rel_path}", size > 0, f"{size} bytes")

    index_path = repo_root / "index.html"
    app_path = repo_root / "src" / "app.js"
    styles_path = repo_root / "src" / "styles.css"
    readme_path = repo_root / "README.md"
    pets_path = repo_root / "data" / "sample-pets.json"

    if index_path.exists():
        index = read_text(index_path).lower()
        add_check(checks, failures, "index_links_app_js", "src/app.js" in index)
        add_check(checks, failures, "index_links_styles", "src/styles.css" in index)
        add_check(
            checks,
            failures,
            "index_has_app_surface",
            any(marker in index for marker in ["diary", "journal", "pet", "routine", "search", "filter"]),
        )
    if app_path.exists():
        app = read_text(app_path)
        add_check(
            checks,
            failures,
            "app_has_interaction_logic",
            any(marker in app for marker in ["addEventListener", "localStorage", "render", "filter", "export"]),
        )
    if styles_path.exists():
        styles = read_text(styles_path)
        add_check(checks, failures, "styles_has_selectors", "{" in styles and "}" in styles)
    if readme_path.exists():
        readme = read_text(readme_path).lower()
        add_check(
            checks,
            failures,
            "readme_describes_demo",
            "pet" in readme and any(marker in readme for marker in ["diary", "journal", "demo"]),
        )
    if pets_path.exists():
        try:
            payload = json.loads(read_text(pets_path))
        except json.JSONDecodeError as exc:
            add_check(checks, failures, "sample_pets_valid_json", False, str(exc))
        else:
            count = len(payload) if isinstance(payload, list) else len(payload.get("pets", [])) if isinstance(payload, dict) else 0
            add_check(checks, failures, "sample_pets_non_empty", count > 0, f"{count} pets")

    report = {
        "schema_version": "corgi.pet_diary_live_project_validation.v1",
        "status": "pass" if not failures else "fail",
        "required_outputs": required_outputs,
        "checks": checks,
        "failures": failures,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit("; ".join(failures))
    print(args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
