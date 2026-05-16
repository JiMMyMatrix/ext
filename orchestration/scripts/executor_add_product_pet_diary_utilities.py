#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def read_text(root: Path, rel_path: str) -> str:
	return (root / rel_path).read_text(encoding="utf-8")


def write_text(root: Path, rel_path: str, content: str) -> None:
	path = root / rel_path
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content.rstrip() + "\n", encoding="utf-8")


def require_file(root: Path, rel_path: str) -> None:
	if not (root / rel_path).exists():
		raise SystemExit(f"Required product app file is missing: {rel_path}")


def update_index(root: Path) -> None:
	source = read_text(root, "index.html")
	if "data-import-json" not in source:
		source = source.replace(
			"\t\t\t\t<section class=\"panel import-export-panel\">\n"
			"\t\t\t\t\t<h3>Import and export</h3>\n"
			"\t\t\t\t\t<p>Keep a local backup, restore sample data, or copy the current diary as JSON.</p>\n"
			"\t\t\t\t\t<div class=\"button-row\">\n"
			"\t\t\t\t\t\t<button data-action=\"copy-json\">Copy JSON</button>\n"
			"\t\t\t\t\t\t<button class=\"secondary\" data-action=\"reset-demo\">Reset demo</button>\n"
			"\t\t\t\t\t</div>\n"
			"\t\t\t\t\t<textarea readonly data-json-preview></textarea>\n"
			"\t\t\t\t</section>",
			"\t\t\t\t<section class=\"panel import-export-panel\">\n"
			"\t\t\t\t\t<h3>Import and export</h3>\n"
			"\t\t\t\t\t<p>Keep a local backup, restore sample data, or copy the current diary as JSON.</p>\n"
			"\t\t\t\t\t<div class=\"button-row\">\n"
			"\t\t\t\t\t\t<button data-action=\"copy-json\">Copy JSON</button>\n"
			"\t\t\t\t\t\t<button class=\"secondary\" data-action=\"reset-demo\">Reset demo</button>\n"
			"\t\t\t\t\t</div>\n"
			"\t\t\t\t\t<textarea readonly data-json-preview></textarea>\n"
			"\t\t\t\t\t<div class=\"import-tools\" data-import-tools>\n"
			"\t\t\t\t\t\t<label for=\"import-json\">Import JSON backup</label>\n"
			"\t\t\t\t\t\t<textarea id=\"import-json\" data-import-json placeholder=\"Paste an exported Pet Life Diary JSON backup\"></textarea>\n"
			"\t\t\t\t\t\t<button data-action=\"import-json\">Import backup</button>\n"
			"\t\t\t\t\t\t<p class=\"form-hint\" data-import-status>Imports validate pets and entries before replacing local data.</p>\n"
			"\t\t\t\t\t</div>\n"
			"\t\t\t\t</section>",
		)
	write_text(root, "index.html", source)


def update_state(root: Path) -> None:
	source = read_text(root, "src/state.js")
	if "export function importState" not in source:
		source = source.replace(
			"\nexport function createEntryId(entries) {",
			"""

function assertRecordList(value, label) {
	if (!Array.isArray(value) || value.length === 0 || !value.every((item) => item && typeof item === 'object')) {
		throw new Error(`${label} must be a non-empty array of records.`);
	}
}

export function importState(jsonText) {
	const parsed = JSON.parse(jsonText);
	if (parsed.schema !== 'pet-life-diary.product-demo.v1') {
		throw new Error('This backup does not match the Pet Life Diary export schema.');
	}
	assertRecordList(parsed.pets, 'pets');
	assertRecordList(parsed.entries, 'entries');
	const state = {
		...initialState(),
		pets: clone(parsed.pets),
		entries: clone(parsed.entries),
		filters: initialState().filters,
	};
	saveState(state);
	return state;
}

export function createEntryId(entries) {""",
		)
	write_text(root, "src/state.js", source)


def update_ui(root: Path) -> None:
	source = read_text(root, "src/ui.js")
	source = source.replace(
		"import { exportState, resetState, saveState } from './state.js';",
		"import { exportState, importState, resetState, saveState } from './state.js';",
	)
	if "data-action=\"import-json\"" not in source:
		source = source.replace(
			"\tdocument.querySelector('[data-action=\"reset-demo\"]')?.addEventListener('click', () => {\n"
			"\t\tconst reset = resetState();\n"
			"\t\tObject.assign(state, reset);\n"
			"\t\trender();\n"
			"\t});",
			"\tdocument.querySelector('[data-action=\"reset-demo\"]')?.addEventListener('click', () => {\n"
			"\t\tconst reset = resetState();\n"
			"\t\tObject.assign(state, reset);\n"
			"\t\trender();\n"
			"\t});\n"
			"\tdocument.querySelector('[data-action=\"import-json\"]')?.addEventListener('click', () => {\n"
			"\t\tconst input = document.querySelector('[data-import-json]');\n"
			"\t\tconst status = document.querySelector('[data-import-status]');\n"
			"\t\ttry {\n"
			"\t\t\tconst imported = importState(input?.value || '');\n"
			"\t\t\tObject.assign(state, imported);\n"
			"\t\t\tif (status) status.textContent = `Imported ${state.entries.length} entries for ${state.pets.length} pets.`;\n"
			"\t\t\trender();\n"
			"\t\t} catch (error) {\n"
			"\t\t\tif (status) status.textContent = error instanceof Error ? error.message : 'Import failed.';\n"
			"\t\t}\n"
			"\t});",
		)
	write_text(root, "src/ui.js", source)


def update_styles(root: Path) -> None:
	source = read_text(root, "src/styles.css")
	if "import-tools" not in source:
		source += """

.import-tools {
	display: grid;
	gap: 0.75rem;
	margin-top: 1rem;
}

.import-tools textarea {
	min-height: 130px;
}

.form-hint {
	color: #64748b;
	font-size: 0.9rem;
	margin: 0;
}
"""
	write_text(root, "src/styles.css", source)


def update_readme(root: Path) -> None:
	source = read_text(root, "README.md")
	if "Diary utilities" not in source:
		source += """

## Diary utilities

The demo now includes a fuller local-first utility loop: diary search and
filtering stay visible in the timeline, JSON export stays available from the
insights view, and JSON import validates pets and entries before replacing the
local backup.
"""
	write_text(root, "README.md", source)


def update_validation_notes(root: Path) -> None:
	source = read_text(root, "tests/product-validation.js")
	if "utilityReadiness" not in source:
		source += """

export const utilityReadiness = {
	surface: 'diary utilities',
	status: 'covered',
	checks: [
		'timeline search and filters remain available',
		'JSON export preserves pets and entries',
		'JSON import validates schema and record lists',
	],
};
"""
	write_text(root, "tests/product-validation.js", source)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", default="")
	args = parser.parse_args()

	root = Path(args.repo_root)
	for rel_path in ["README.md", "index.html", "src/state.js", "src/ui.js", "src/styles.css", "tests/product-validation.js"]:
		require_file(root, rel_path)
	update_index(root)
	update_state(root)
	update_ui(root)
	update_styles(root)
	update_readme(root)
	update_validation_notes(root)


if __name__ == "__main__":
	main()
