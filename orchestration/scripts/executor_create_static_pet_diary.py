#!/usr/bin/env python3
"""Create a tiny static Pet Life Diary app for scratch-workspace E2E tests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return {}


def write_text(path: Path, text: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(text, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def app_files(repo_root: Path, *, dispatch_ref: str, objective: str, accepted_intake_ref: str | None) -> None:
	accepted_intake = read_json(repo_root / accepted_intake_ref) if accepted_intake_ref else {}
	goal = str(accepted_intake.get("goal") or accepted_intake.get("task") or objective).strip()
	write_text(
		repo_root / "README.md",
		f"""# Pet Life Diary

Pet Life Diary is a tiny static app for tracking everyday pet memories.

## What this app includes

- A simple dashboard for pet profiles and recent diary entries.
- Sample data in `data/sample-pets.json`.
- No build step or network dependency.

## Run locally

Open `index.html` in a browser.

## Corgi dispatch

- Dispatch: `{dispatch_ref}`
- Accepted goal: {goal}
""",
	)
	write_text(
		repo_root / "index.html",
		"""<!doctype html>
<html lang="en">
	<head>
		<meta charset="utf-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
		<title>Pet Life Diary</title>
		<link rel="stylesheet" href="src/styles.css" />
	</head>
	<body>
		<main class="shell">
			<section class="hero">
				<p class="eyebrow">Pet Life Diary</p>
				<h1>Remember the small moments.</h1>
				<p>Track meals, moods, walks, vet notes, and tiny victories for every pet at home.</p>
			</section>
			<section id="pet-list" class="pet-grid" aria-live="polite"></section>
		</main>
		<script type="module" src="src/app.js"></script>
	</body>
</html>
""",
	)
	write_text(
		repo_root / "src" / "app.js",
		"""const pets = [
	{
		name: "Mochi",
		species: "Corgi",
		mood: "Playful",
		lastEntry: "Practiced a new spin trick and demanded a celebratory snack.",
	},
	{
		name: "Nori",
		species: "Cat",
		mood: "Curious",
		lastEntry: "Inspected every grocery bag and approved the salmon treats.",
	},
	{
		name: "Biscuit",
		species: "Rabbit",
		mood: "Relaxed",
		lastEntry: "Enjoyed parsley and a long nap beside the sunny window.",
	},
];

const list = document.querySelector("#pet-list");

function petCard(pet) {
	const card = document.createElement("article");
	card.className = "pet-card";
	card.innerHTML = `
		<div class="avatar" aria-hidden="true">${pet.name.slice(0, 1)}</div>
		<div>
			<h2>${pet.name}</h2>
			<p class="species">${pet.species} - ${pet.mood}</p>
			<p>${pet.lastEntry}</p>
		</div>
	`;
	return card;
}

pets.forEach((pet) => list?.append(petCard(pet)));
""",
	)
	write_text(
		repo_root / "src" / "styles.css",
		""":root {
	color: #24302b;
	background: #fff8ef;
	font-family: Avenir Next, ui-sans-serif, system-ui, sans-serif;
}

body {
	margin: 0;
	min-height: 100vh;
	background:
		radial-gradient(circle at top left, rgba(255, 193, 112, 0.38), transparent 32rem),
		linear-gradient(135deg, #fff8ef 0%, #eef7ef 100%);
}

.shell {
	width: min(980px, calc(100% - 32px));
	margin: 0 auto;
	padding: 56px 0;
}

.hero {
	max-width: 680px;
	margin-bottom: 32px;
}

.eyebrow {
	color: #d4743d;
	font-weight: 800;
	letter-spacing: 0.12em;
	text-transform: uppercase;
}

h1 {
	margin: 0 0 16px;
	font-size: clamp(2.4rem, 8vw, 5rem);
	line-height: 0.95;
}

.pet-grid {
	display: grid;
	gap: 18px;
	grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.pet-card {
	display: flex;
	gap: 16px;
	padding: 20px;
	border: 1px solid rgba(36, 48, 43, 0.12);
	border-radius: 24px;
	background: rgba(255, 255, 255, 0.72);
	box-shadow: 0 18px 48px rgba(36, 48, 43, 0.08);
}

.avatar {
	display: grid;
	place-items: center;
	flex: 0 0 52px;
	width: 52px;
	height: 52px;
	border-radius: 18px;
	background: #24302b;
	color: #fff8ef;
	font-size: 1.4rem;
	font-weight: 800;
}

h2 {
	margin: 0;
}

.species {
	margin: 4px 0 10px;
	color: #66736d;
	font-weight: 700;
}
""",
	)
	write_json(
		repo_root / "data" / "sample-pets.json",
		[
			{
				"name": "Mochi",
				"species": "Corgi",
				"favoriteActivity": "Spin tricks",
				"lastEntry": "Practiced a new spin trick and demanded a celebratory snack.",
			},
			{
				"name": "Nori",
				"species": "Cat",
				"favoriteActivity": "Bag inspection",
				"lastEntry": "Inspected every grocery bag and approved the salmon treats.",
			},
			{
				"name": "Biscuit",
				"species": "Rabbit",
				"favoriteActivity": "Sun naps",
				"lastEntry": "Enjoyed parsley and a long nap beside the sunny window.",
			},
		],
	)


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Create the scratch Pet Life Diary static app.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", required=True)
	parser.add_argument("--accepted-intake")
	args = parser.parse_args(argv)

	repo_root = Path(args.repo_root).resolve()
	app_files(
		repo_root,
		dispatch_ref=args.dispatch_ref,
		objective=args.objective,
		accepted_intake_ref=args.accepted_intake,
	)
	print("README.md")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
