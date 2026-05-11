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

Pet Life Diary is a polished static demo for tracking everyday pet memories.
It is designed as a small product showcase that could support an App Store-style
listing or investor/demo walkthrough without requiring a build step.

## What this app includes

- A warm landing screen with product positioning and app-style feature cards.
- A phone-preview style diary surface with pet profiles, mood stats, and recent entries.
- Lightweight filtering so the demo feels interactive without adding dependencies.
- Sample data in `data/sample-pets.json`.
- No build step or network dependency.

## Run locally

Open `index.html` in a browser.

## Demo focus

This is intentionally static. The goal is to prove the Corgi Governor /
Executor / Reviewer loop can create a coherent project artifact in an isolated
scratch workspace.

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
			<section class="hero" aria-labelledby="hero-title">
				<div class="hero-copy">
					<p class="eyebrow">Pet Life Diary</p>
					<h1 id="hero-title">A calmer way to remember every pet moment.</h1>
					<p class="lede">
						Capture moods, meals, walks, vet notes, and tiny victories in a
						warm diary built for multi-pet homes.
					</p>
					<div class="store-row" aria-label="Demo highlights">
						<span class="store-pill">Static demo</span>
						<span class="store-pill">No signup</span>
						<span class="store-pill">Pet-first timeline</span>
					</div>
				</div>
				<aside class="phone-preview" aria-label="Pet Life Diary app preview">
					<div class="phone-topbar"></div>
					<p class="preview-date">Today</p>
					<h2>3 happy updates</h2>
					<div id="preview-list" class="preview-list"></div>
				</aside>
			</section>

			<section class="summary-grid" aria-label="Diary summary">
				<div class="summary-card">
					<strong id="pet-count">0</strong>
					<span>pets tracked</span>
				</div>
				<div class="summary-card">
					<strong id="entry-count">0</strong>
					<span>sample entries</span>
				</div>
				<div class="summary-card">
					<strong id="mood-count">0</strong>
					<span>moods logged</span>
				</div>
			</section>

			<section class="controls" aria-label="Filter diary entries">
				<button class="filter-button is-active" data-filter="all" type="button">All pets</button>
				<button class="filter-button" data-filter="Corgi" type="button">Corgi</button>
				<button class="filter-button" data-filter="Cat" type="button">Cat</button>
				<button class="filter-button" data-filter="Rabbit" type="button">Rabbit</button>
			</section>

			<section id="pet-list" class="pet-grid" aria-live="polite"></section>

			<section class="feature-panel" aria-labelledby="features-title">
				<p class="eyebrow">Why it feels useful</p>
				<h2 id="features-title">Built for everyday care, not spreadsheet chores.</h2>
				<div class="feature-grid">
					<article>
						<h3>Fast notes</h3>
						<p>Keep meals, medication, behavior, and favorite moments in one gentle timeline.</p>
					</article>
					<article>
						<h3>Family context</h3>
						<p>See each pet's mood and latest update without digging through scattered messages.</p>
					</article>
					<article>
						<h3>Vet-ready memory</h3>
						<p>Turn small observations into a lightweight history you can reference later.</p>
					</article>
				</div>
			</section>
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
		emoji: "M",
		accent: "#ffb86b",
		entries: [
			"Practiced a new spin trick and demanded a celebratory snack.",
			"Took a breezy evening walk and greeted every neighbor.",
		],
	},
	{
		name: "Nori",
		species: "Cat",
		mood: "Curious",
		emoji: "N",
		accent: "#9cc9ff",
		entries: [
			"Inspected every grocery bag and approved the salmon treats.",
			"Claimed the sunny chair for a three-hour nap.",
		],
	},
	{
		name: "Biscuit",
		species: "Rabbit",
		mood: "Relaxed",
		emoji: "B",
		accent: "#b9e7a5",
		entries: [
			"Enjoyed parsley and a long nap beside the sunny window.",
			"Explored the blanket fort with serious determination.",
		],
	},
];

const list = document.querySelector("#pet-list");
const previewList = document.querySelector("#preview-list");
const filterButtons = [...document.querySelectorAll("[data-filter]")];
const petCount = document.querySelector("#pet-count");
const entryCount = document.querySelector("#entry-count");
const moodCount = document.querySelector("#mood-count");

let selectedSpecies = "all";

function petCard(pet) {
	const card = document.createElement("article");
	card.className = "pet-card";
	card.style.setProperty("--accent", pet.accent);
	card.innerHTML = `
		<div class="avatar" aria-hidden="true">${pet.emoji}</div>
		<div>
			<h2>${pet.name}</h2>
			<p class="species">${pet.species} - ${pet.mood}</p>
			<p>${pet.entries[0]}</p>
			<ul class="entry-list">
				${pet.entries.map((entry) => `<li>${entry}</li>`).join("")}
			</ul>
		</div>
	`;
	return card;
}

function renderPreview() {
	if (!previewList) {
		return;
	}
	previewList.innerHTML = "";
	pets.slice(0, 3).forEach((pet) => {
		const item = document.createElement("div");
		item.className = "preview-item";
		item.innerHTML = `<span>${pet.emoji}</span><p>${pet.entries[0]}</p>`;
		previewList.append(item);
	});
}

function renderStats() {
	const totalEntries = pets.reduce((count, pet) => count + pet.entries.length, 0);
	const moods = new Set(pets.map((pet) => pet.mood));
	if (petCount) petCount.textContent = String(pets.length);
	if (entryCount) entryCount.textContent = String(totalEntries);
	if (moodCount) moodCount.textContent = String(moods.size);
}

function renderPets() {
	if (!list) {
		return;
	}
	list.innerHTML = "";
	const visiblePets =
		selectedSpecies === "all"
			? pets
			: pets.filter((pet) => pet.species === selectedSpecies);
	visiblePets.forEach((pet) => list.append(petCard(pet)));
}

filterButtons.forEach((button) => {
	button.addEventListener("click", () => {
		selectedSpecies = button.dataset.filter || "all";
		filterButtons.forEach((candidate) =>
			candidate.classList.toggle("is-active", candidate === button)
		);
		renderPets();
	});
});

renderPreview();
renderStats();
renderPets();
""",
	)
	write_text(
		repo_root / "src" / "styles.css",
		""":root {
	color: #24302b;
	background: #fff8ef;
	font-family: Avenir Next, ui-sans-serif, system-ui, sans-serif;
	--ink: #24302b;
	--paper: #fff8ef;
	--muted: #66736d;
	--blue: #5c9dd8;
	--orange: #d4743d;
}

body {
	margin: 0;
	min-height: 100vh;
	background:
		radial-gradient(circle at top left, rgba(255, 193, 112, 0.38), transparent 32rem),
		linear-gradient(135deg, #fff8ef 0%, #eef7ef 100%);
}

.shell {
	width: min(1120px, calc(100% - 32px));
	margin: 0 auto;
	padding: 56px 0;
}

.hero {
	display: grid;
	grid-template-columns: minmax(0, 1fr) minmax(280px, 380px);
	gap: 32px;
	align-items: center;
	margin-bottom: 32px;
}

.hero-copy {
	max-width: 700px;
}

.eyebrow {
	color: var(--orange);
	font-weight: 800;
	letter-spacing: 0.12em;
	text-transform: uppercase;
}

h1 {
	margin: 0 0 16px;
	font-size: clamp(2.4rem, 8vw, 5rem);
	line-height: 0.95;
}

.lede {
	max-width: 640px;
	color: var(--muted);
	font-size: 1.15rem;
	line-height: 1.7;
}

.store-row,
.controls {
	display: flex;
	flex-wrap: wrap;
	gap: 10px;
}

.store-pill,
.filter-button {
	border: 1px solid rgba(36, 48, 43, 0.14);
	border-radius: 999px;
	background: rgba(255, 255, 255, 0.7);
	color: var(--ink);
	font-weight: 800;
	padding: 10px 14px;
}

.filter-button {
	cursor: pointer;
}

.filter-button.is-active {
	background: var(--ink);
	color: var(--paper);
}

.phone-preview {
	border: 10px solid var(--ink);
	border-radius: 42px;
	background: #fffdfa;
	box-shadow: 0 24px 70px rgba(36, 48, 43, 0.18);
	padding: 24px;
	min-height: 360px;
}

.phone-topbar {
	width: 84px;
	height: 6px;
	border-radius: 999px;
	margin: 0 auto 24px;
	background: rgba(36, 48, 43, 0.25);
}

.preview-date {
	color: var(--muted);
	font-weight: 800;
	margin-bottom: 4px;
}

.preview-list {
	display: grid;
	gap: 12px;
	margin-top: 20px;
}

.preview-item {
	display: flex;
	gap: 12px;
	align-items: center;
	border-radius: 18px;
	background: #f5efe6;
	padding: 12px;
}

.preview-item span {
	display: grid;
	place-items: center;
	width: 38px;
	height: 38px;
	border-radius: 14px;
	background: var(--ink);
	color: var(--paper);
	font-weight: 900;
}

.preview-item p {
	margin: 0;
	color: var(--muted);
}

.summary-grid {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 14px;
	margin: 28px 0;
}

.summary-card {
	border: 1px solid rgba(36, 48, 43, 0.12);
	border-radius: 24px;
	background: rgba(255, 255, 255, 0.62);
	padding: 20px;
}

.summary-card strong {
	display: block;
	font-size: 2rem;
}

.summary-card span {
	color: var(--muted);
	font-weight: 700;
}

.pet-grid {
	display: grid;
	gap: 18px;
	grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
	margin-top: 20px;
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
	background: var(--accent, var(--ink));
	color: #fff8ef;
	font-size: 1.4rem;
	font-weight: 800;
}

h2 {
	margin: 0;
}

.species {
	margin: 4px 0 10px;
	color: var(--muted);
	font-weight: 700;
}

.entry-list {
	margin: 14px 0 0;
	padding-left: 18px;
	color: var(--muted);
}

.feature-panel {
	margin-top: 34px;
	padding: 28px;
	border-radius: 32px;
	background: rgba(36, 48, 43, 0.9);
	color: var(--paper);
}

.feature-panel .eyebrow,
.feature-panel p {
	color: rgba(255, 248, 239, 0.72);
}

.feature-grid {
	display: grid;
	grid-template-columns: repeat(3, minmax(0, 1fr));
	gap: 16px;
}

.feature-grid article {
	border: 1px solid rgba(255, 248, 239, 0.14);
	border-radius: 22px;
	padding: 18px;
}

@media (max-width: 760px) {
	.hero,
	.summary-grid,
	.feature-grid {
		grid-template-columns: 1fr;
	}

	.phone-preview {
		min-height: auto;
	}
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
				"mood": "Playful",
				"entries": [
					"Practiced a new spin trick and demanded a celebratory snack.",
					"Took a breezy evening walk and greeted every neighbor."
				],
			},
			{
				"name": "Nori",
				"species": "Cat",
				"favoriteActivity": "Bag inspection",
				"mood": "Curious",
				"entries": [
					"Inspected every grocery bag and approved the salmon treats.",
					"Claimed the sunny chair for a three-hour nap."
				],
			},
			{
				"name": "Biscuit",
				"species": "Rabbit",
				"favoriteActivity": "Sun naps",
				"mood": "Relaxed",
				"entries": [
					"Enjoyed parsley and a long nap beside the sunny window.",
					"Explored the blanket fort with serious determination."
				],
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
