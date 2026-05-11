#!/usr/bin/env python3
"""Write an Executor-authored patch specification for a bounded dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness.patch_specs import (  # noqa: E402
    PATCH_SPEC_SCHEMA_VERSION,
    PatchSpecError,
    load_dispatch_request,
    operation_for_text_replacement,
    repo_path,
    validate_patch_spec_path,
    validate_patch_spec_payload,
    write_json,
)


PET_DIARY_BUGFIX_OLD_SNIPPET = """\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tinput.value = "";
\trenderEntries();
"""

PET_DIARY_BUGFIX_NEW_SNIPPET = """\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tdiaryEntries.push({
\t\ttext,
\t\tcreatedAt: "Just now",
\t});
\tinput.value = "";
\trenderEntries();
"""

PET_DIARY_FILTER_INDEX_OLD = """\t\t\t<form id="diary-form" class="entry-form">
\t\t\t\t<label for="diary-entry-input">New diary entry</label>
\t\t\t\t<input id="diary-entry-input" name="entry" placeholder="Mochi learned a new trick" />
\t\t\t\t<button type="submit">Add entry</button>
\t\t\t</form>
\t\t\t<ul id="diary-entry-list" class="entry-list" aria-live="polite"></ul>
"""

PET_DIARY_FILTER_INDEX_NEW = """\t\t\t<section class="filter-panel" aria-label="Filter diary entries">
\t\t\t\t<label for="species-filter">Filter entries by species</label>
\t\t\t\t<select id="species-filter" name="species-filter">
\t\t\t\t\t<option value="all">All pets</option>
\t\t\t\t\t<option value="Corgi">Corgi</option>
\t\t\t\t\t<option value="Cat">Cat</option>
\t\t\t\t</select>
\t\t\t</section>
\t\t\t<form id="diary-form" class="entry-form">
\t\t\t\t<label for="diary-entry-input">New diary entry</label>
\t\t\t\t<input id="diary-entry-input" name="entry" placeholder="Mochi learned a new trick" />
\t\t\t\t<button type="submit">Add entry</button>
\t\t\t</form>
\t\t\t<ul id="diary-entry-list" class="entry-list" aria-live="polite"></ul>
"""

PET_DIARY_FILTER_APP_OLD = """const diaryEntries = [
\t{
\t\ttext: "Mochi practiced a spin trick.",
\t\tcreatedAt: "Yesterday",
\t\tspecies: "Corgi",
\t},
\t{
\t\ttext: "Nori inspected every grocery bag.",
\t\tcreatedAt: "Today",
\t\tspecies: "Cat",
\t},
];

const form = document.querySelector("#diary-form");
const input = document.querySelector("#diary-entry-input");
const list = document.querySelector("#diary-entry-list");

function renderEntries() {
\tif (!list) {
\t\treturn;
\t}
\tlist.innerHTML = "";
\tfor (const entry of diaryEntries) {
\t\tconst item = document.createElement("li");
\t\titem.className = "entry-card";
\t\titem.textContent = entry.text + " - " + entry.createdAt;
\t\tlist.append(item);
\t}
}

form?.addEventListener("submit", (event) => {
\tevent.preventDefault();
\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tdiaryEntries.push({
\t\ttext,
\t\tcreatedAt: "Just now",
\t\tspecies: "Corgi",
\t});
\tinput.value = "";
\trenderEntries();
});

renderEntries();
"""

PET_DIARY_FILTER_APP_NEW = """const diaryEntries = [
\t{
\t\ttext: "Mochi practiced a spin trick.",
\t\tcreatedAt: "Yesterday",
\t\tspecies: "Corgi",
\t},
\t{
\t\ttext: "Nori inspected every grocery bag.",
\t\tcreatedAt: "Today",
\t\tspecies: "Cat",
\t},
];

const form = document.querySelector("#diary-form");
const input = document.querySelector("#diary-entry-input");
const list = document.querySelector("#diary-entry-list");
const speciesFilter = document.querySelector("#species-filter");

function visibleEntries() {
\tconst selectedSpecies = speciesFilter?.value ?? "all";
\tif (selectedSpecies === "all") {
\t\treturn diaryEntries;
\t}
\treturn diaryEntries.filter((entry) => entry.species === selectedSpecies);
}

function renderEntries() {
\tif (!list) {
\t\treturn;
\t}
\tlist.innerHTML = "";
\tfor (const entry of visibleEntries()) {
\t\tconst item = document.createElement("li");
\t\titem.className = "entry-card";
\t\titem.dataset.species = entry.species;
\t\titem.textContent = entry.text + " - " + entry.createdAt + " - " + entry.species;
\t\tlist.append(item);
\t}
}

speciesFilter?.addEventListener("change", () => {
\trenderEntries();
});

form?.addEventListener("submit", (event) => {
\tevent.preventDefault();
\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tdiaryEntries.push({
\t\ttext,
\t\tcreatedAt: "Just now",
\t\tspecies: speciesFilter?.value === "Cat" ? "Cat" : "Corgi",
\t});
\tinput.value = "";
\trenderEntries();
});

renderEntries();
"""

PET_DIARY_FILTER_PARTIAL_APP_NEW = """const diaryEntries = [
\t{
\t\ttext: "Mochi practiced a spin trick.",
\t\tcreatedAt: "Yesterday",
\t\tspecies: "Corgi",
\t},
\t{
\t\ttext: "Nori inspected every grocery bag.",
\t\tcreatedAt: "Today",
\t\tspecies: "Cat",
\t},
];

const form = document.querySelector("#diary-form");
const input = document.querySelector("#diary-entry-input");
const list = document.querySelector("#diary-entry-list");
const speciesFilter = document.querySelector("#species-filter");

function renderEntries() {
\tif (!list) {
\t\treturn;
\t}
\tlist.innerHTML = "";
\tfor (const entry of diaryEntries) {
\t\tconst item = document.createElement("li");
\t\titem.className = "entry-card";
\t\titem.dataset.species = entry.species;
\t\titem.textContent = entry.text + " - " + entry.createdAt + " - " + entry.species;
\t\tlist.append(item);
\t}
}

speciesFilter?.addEventListener("change", () => {
\trenderEntries();
});

form?.addEventListener("submit", (event) => {
\tevent.preventDefault();
\tconst text = input.value.trim();
\tif (!text) {
\t\treturn;
\t}
\tdiaryEntries.push({
\t\ttext,
\t\tcreatedAt: "Just now",
\t\tspecies: speciesFilter?.value === "Cat" ? "Cat" : "Corgi",
\t});
\tinput.value = "";
\trenderEntries();
});

renderEntries();
"""


def propose_pet_diary_entry_submit(
    repo_root: Path,
    *,
    dispatch_ref: str,
    spec_ref: str,
    patch_artifact_ref: str,
    objective: str,
) -> None:
    app_path = repo_path(repo_root, "src/app.js", label="patch proposal path")
    if not app_path.exists():
        raise SystemExit("src/app.js is missing; cannot propose Pet Life Diary patch")
    source = app_path.read_text(encoding="utf-8")
    if "diaryEntries.push" in source:
        raise SystemExit("src/app.js already appends diary entries; this dispatch must mutate the seeded bug")
    if PET_DIARY_BUGFIX_OLD_SNIPPET not in source:
        raise SystemExit("src/app.js does not contain the expected seeded diary-entry bug")

    payload = {
        "schema_version": PATCH_SPEC_SCHEMA_VERSION,
        "dispatch_ref": dispatch_ref,
        "objective": objective,
        "intent": "Fix the Pet Life Diary submit handler so new diary entries are appended before rendering.",
        "proposed_by": "executor",
        "recipe": "pet_diary_entry_submit",
        "operations": [
            operation_for_text_replacement(
                repo_root,
                rel_path="src/app.js",
                old_text=PET_DIARY_BUGFIX_OLD_SNIPPET,
                new_text=PET_DIARY_BUGFIX_NEW_SNIPPET,
                expected_replacements=1,
                forbidden_text="diaryEntries.push",
                patch_artifact_ref=patch_artifact_ref,
            )
        ],
    }
    request = load_dispatch_request(repo_root, dispatch_ref)
    validate_patch_spec_payload(repo_root, payload, dispatch_ref=dispatch_ref, request=request)
    spec_path = repo_path(repo_root, spec_ref, label="patch proposal path")
    validate_patch_spec_path(repo_root, dispatch_ref, spec_path)
    write_json(spec_path, payload)
    print(spec_ref)


def propose_pet_diary_species_filter(
    repo_root: Path,
    *,
    dispatch_ref: str,
    spec_ref: str,
    patch_artifact_ref: str,
    objective: str,
) -> None:
    app_path = repo_path(repo_root, "src/app.js", label="patch proposal path")
    index_path = repo_path(repo_root, "index.html", label="patch proposal path")
    if not app_path.exists() or not index_path.exists():
        raise SystemExit("Pet Life Diary app files are missing; cannot propose species filter patch")
    app_source = app_path.read_text(encoding="utf-8")
    index_source = index_path.read_text(encoding="utf-8")
    if "species-filter" in index_source or "visibleEntries" in app_source:
        raise SystemExit("Pet Life Diary already has a species filter; this dispatch must mutate the seeded app")
    if PET_DIARY_FILTER_INDEX_OLD not in index_source:
        raise SystemExit("index.html does not contain the expected seeded diary form block")
    if PET_DIARY_FILTER_APP_OLD not in app_source:
        raise SystemExit("src/app.js does not contain the expected seeded filter baseline")

    patch_base = patch_artifact_ref.removesuffix(".patch")
    payload = {
        "schema_version": PATCH_SPEC_SCHEMA_VERSION,
        "dispatch_ref": dispatch_ref,
        "objective": objective,
        "intent": "Add a species filter to the existing Pet Life Diary entries.",
        "proposed_by": "executor",
        "recipe": "pet_diary_species_filter",
        "operations": [
            operation_for_text_replacement(
                repo_root,
                rel_path="index.html",
                old_text=PET_DIARY_FILTER_INDEX_OLD,
                new_text=PET_DIARY_FILTER_INDEX_NEW,
                expected_replacements=1,
                forbidden_text="species-filter",
                patch_artifact_ref=f"{patch_base}-index-html.patch",
            ),
            operation_for_text_replacement(
                repo_root,
                rel_path="src/app.js",
                old_text=PET_DIARY_FILTER_APP_OLD,
                new_text=PET_DIARY_FILTER_APP_NEW,
                expected_replacements=1,
                forbidden_text="visibleEntries",
                patch_artifact_ref=f"{patch_base}-src-app-js.patch",
            ),
        ],
    }
    request = load_dispatch_request(repo_root, dispatch_ref)
    validate_patch_spec_payload(repo_root, payload, dispatch_ref=dispatch_ref, request=request)
    spec_path = repo_path(repo_root, spec_ref, label="patch proposal path")
    validate_patch_spec_path(repo_root, dispatch_ref, spec_path)
    write_json(spec_path, payload)
    print(spec_ref)


def propose_pet_diary_species_filter_partial(
    repo_root: Path,
    *,
    dispatch_ref: str,
    spec_ref: str,
    patch_artifact_ref: str,
    objective: str,
) -> None:
    app_path = repo_path(repo_root, "src/app.js", label="patch proposal path")
    index_path = repo_path(repo_root, "index.html", label="patch proposal path")
    if not app_path.exists() or not index_path.exists():
        raise SystemExit("Pet Life Diary app files are missing; cannot propose partial species filter patch")
    app_source = app_path.read_text(encoding="utf-8")
    index_source = index_path.read_text(encoding="utf-8")
    if "species-filter" in index_source or "speciesFilter" in app_source:
        raise SystemExit("Pet Life Diary already has a species filter; this partial dispatch must start from the seeded app")
    if PET_DIARY_FILTER_INDEX_OLD not in index_source:
        raise SystemExit("index.html does not contain the expected seeded diary form block")
    if PET_DIARY_FILTER_APP_OLD not in app_source:
        raise SystemExit("src/app.js does not contain the expected seeded filter baseline")

    patch_base = patch_artifact_ref.removesuffix(".patch")
    payload = {
        "schema_version": PATCH_SPEC_SCHEMA_VERSION,
        "dispatch_ref": dispatch_ref,
        "objective": objective,
        "intent": "Add the visible species filter controls, but leave filtering behavior incomplete for retry validation.",
        "proposed_by": "executor",
        "recipe": "pet_diary_species_filter_partial",
        "operations": [
            operation_for_text_replacement(
                repo_root,
                rel_path="index.html",
                old_text=PET_DIARY_FILTER_INDEX_OLD,
                new_text=PET_DIARY_FILTER_INDEX_NEW,
                expected_replacements=1,
                forbidden_text="species-filter",
                patch_artifact_ref=f"{patch_base}-index-html.patch",
            ),
            operation_for_text_replacement(
                repo_root,
                rel_path="src/app.js",
                old_text=PET_DIARY_FILTER_APP_OLD,
                new_text=PET_DIARY_FILTER_PARTIAL_APP_NEW,
                expected_replacements=1,
                forbidden_text="speciesFilter",
                patch_artifact_ref=f"{patch_base}-src-app-js.patch",
            ),
        ],
    }
    request = load_dispatch_request(repo_root, dispatch_ref)
    validate_patch_spec_payload(repo_root, payload, dispatch_ref=dispatch_ref, request=request)
    spec_path = repo_path(repo_root, spec_ref, label="patch proposal path")
    validate_patch_spec_path(repo_root, dispatch_ref, spec_path)
    write_json(spec_path, payload)
    print(spec_ref)


def propose_pet_diary_species_filter_complete(
    repo_root: Path,
    *,
    dispatch_ref: str,
    spec_ref: str,
    patch_artifact_ref: str,
    objective: str,
) -> None:
    app_path = repo_path(repo_root, "src/app.js", label="patch proposal path")
    if not app_path.exists():
        raise SystemExit("src/app.js is missing; cannot propose complete species filter patch")
    app_source = app_path.read_text(encoding="utf-8")
    if "function visibleEntries()" in app_source:
        raise SystemExit("Pet Life Diary already has complete species filter behavior")
    if PET_DIARY_FILTER_PARTIAL_APP_NEW not in app_source:
        raise SystemExit("src/app.js does not contain the expected partial species filter baseline")

    payload = {
        "schema_version": PATCH_SPEC_SCHEMA_VERSION,
        "dispatch_ref": dispatch_ref,
        "objective": objective,
        "intent": "Complete the species filter behavior by filtering visible entries before rendering.",
        "proposed_by": "executor",
        "recipe": "pet_diary_species_filter_complete",
        "operations": [
            operation_for_text_replacement(
                repo_root,
                rel_path="src/app.js",
                old_text=PET_DIARY_FILTER_PARTIAL_APP_NEW,
                new_text=PET_DIARY_FILTER_APP_NEW,
                expected_replacements=1,
                forbidden_text="function visibleEntries()",
                patch_artifact_ref=patch_artifact_ref,
            )
        ],
    }
    request = load_dispatch_request(repo_root, dispatch_ref)
    validate_patch_spec_payload(repo_root, payload, dispatch_ref=dispatch_ref, request=request)
    spec_path = repo_path(repo_root, spec_ref, label="patch proposal path")
    validate_patch_spec_path(repo_root, dispatch_ref, spec_path)
    write_json(spec_path, payload)
    print(spec_ref)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose a bounded Corgi patch specification.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--dispatch-ref", required=True)
    parser.add_argument("--objective", required=True)
    parser.add_argument(
        "--recipe",
        required=True,
        choices=[
            "pet_diary_entry_submit",
            "pet_diary_species_filter",
            "pet_diary_species_filter_partial",
            "pet_diary_species_filter_complete",
        ],
    )
    parser.add_argument("--spec", required=True)
    parser.add_argument("--patch-artifact", required=True)
    args = parser.parse_args(argv)

    try:
        repo_root = Path(args.repo_root).resolve()
        if args.recipe == "pet_diary_entry_submit":
            propose_pet_diary_entry_submit(
                repo_root,
                dispatch_ref=args.dispatch_ref,
                spec_ref=args.spec,
                patch_artifact_ref=args.patch_artifact,
                objective=args.objective,
            )
            return 0
        if args.recipe == "pet_diary_species_filter":
            propose_pet_diary_species_filter(
                repo_root,
                dispatch_ref=args.dispatch_ref,
                spec_ref=args.spec,
                patch_artifact_ref=args.patch_artifact,
                objective=args.objective,
            )
            return 0
        if args.recipe == "pet_diary_species_filter_partial":
            propose_pet_diary_species_filter_partial(
                repo_root,
                dispatch_ref=args.dispatch_ref,
                spec_ref=args.spec,
                patch_artifact_ref=args.patch_artifact,
                objective=args.objective,
            )
            return 0
        if args.recipe == "pet_diary_species_filter_complete":
            propose_pet_diary_species_filter_complete(
                repo_root,
                dispatch_ref=args.dispatch_ref,
                spec_ref=args.spec,
                patch_artifact_ref=args.patch_artifact,
                objective=args.objective,
            )
            return 0
        raise SystemExit(f"unsupported patch proposal recipe: {args.recipe}")
    except PatchSpecError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
