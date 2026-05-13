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
	if 'data-view-target="routines"' not in source:
		source = source.replace(
			'\t\t\t<button class="tab" data-view-target="pets">Pets</button>\n'
			'\t\t\t<button class="tab" data-view-target="insights">Insights</button>',
			'\t\t\t<button class="tab" data-view-target="pets">Pets</button>\n'
			'\t\t\t<button class="tab" data-view-target="routines">Routines</button>\n'
			'\t\t\t<button class="tab" data-view-target="insights">Insights</button>',
		)
	if 'id="view-routines"' not in source:
		routine_section = """
			<section id="view-routines" class="view" data-view="routines">
				<div class="section-heading">
					<h2>Care routines</h2>
					<p>Plan repeatable care moments so the diary becomes a practical habit, not just a log.</p>
				</div>
				<div class="routine-board" data-routine-board></div>
			</section>

"""
		source = source.replace('\t\t\t<section id="view-insights"', routine_section + '\t\t\t<section id="view-insights"')
	write_text(root, "index.html", source)


def update_state(root: Path) -> None:
	source = read_text(root, "src/state.js")
	if "routines:" not in source:
		source = source.replace(
			"\t\tentries: clone(sampleEntries),\n",
			"\t\tentries: clone(sampleEntries),\n"
			"\t\troutines: clone(samplePets).slice(0, 6).map((pet, index) => ({\n"
			"\t\t\tid: `routine-${index + 1}`,\n"
			"\t\t\tpetId: pet.id,\n"
			"\t\t\tpetName: pet.name,\n"
			"\t\t\ttitle: `${pet.name} care rhythm`,\n"
			"\t\t\tcadence: index % 2 === 0 ? 'daily' : 'weekly',\n"
			"\t\t\tchecklist: ['food', 'mood', 'memory note'],\n"
			"\t\t\tstatus: 'planned',\n"
			"\t\t})),\n",
		)
	write_text(root, "src/state.js", source)


def update_ui(root: Path) -> None:
	source = read_text(root, "src/ui.js")
	if "renderRoutineBoard" not in source:
		routine_renderer = """
export function renderRoutineBoard(state) {
	const board = document.querySelector('[data-routine-board]');
	if (!board) {
		return;
	}
	const routines = state.routines || [];
	board.innerHTML = routines.map((routine) => `
		<article class="routine-card">
			<p class="eyebrow">${routine.cadence}</p>
			<h3>${routine.title}</h3>
			<p>${routine.petName}</p>
			<ul>
				${routine.checklist.map((item) => `<li>${item}</li>`).join('')}
			</ul>
			<span>${routine.status}</span>
		</article>
	`).join('');
}

"""
		source = source.replace("export function bindActions", routine_renderer + "export function bindActions")
	if "\trenderRoutineBoard(state);" not in source:
		source = source.replace(
			"\trenderPets(state);\n\trenderInsights(state);",
			"\trenderPets(state);\n\trenderRoutineBoard(state);\n\trenderInsights(state);",
		)
	write_text(root, "src/ui.js", source)


def update_styles(root: Path) -> None:
	source = read_text(root, "src/styles.css")
	if "routine-board" not in source:
		source += """

.routine-board {
	display: grid;
	gap: 1rem;
	grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.routine-card {
	background: rgba(255, 255, 255, 0.82);
	border: 1px solid rgba(51, 65, 85, 0.14);
	border-radius: 22px;
	padding: 1rem;
	box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08);
}

.routine-card ul {
	margin: 0.75rem 0;
	padding-left: 1.1rem;
}
"""
	write_text(root, "src/styles.css", source)


def update_readme(root: Path) -> None:
	source = read_text(root, "README.md")
	if "Care routines" not in source:
		source += """

## Care routines

The product demo now includes a routine-planning surface. It keeps repeatable care
habits close to the diary timeline so a caregiver can see both what happened and
what should happen next.
"""
	write_text(root, "README.md", source)


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", default="")
	args = parser.parse_args()

	root = Path(args.repo_root)
	for rel_path in ["README.md", "index.html", "src/state.js", "src/ui.js", "src/styles.css"]:
		require_file(root, rel_path)
	update_index(root)
	update_state(root)
	update_ui(root)
	update_styles(root)
	update_readme(root)


if __name__ == "__main__":
	main()
