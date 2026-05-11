#!/usr/bin/env python3
"""Create the baseline Pet Life Diary app used by the goal-program benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def write_text(path: Path, content: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(content, encoding="utf-8")


def create_app(repo_root: Path) -> None:
	write_text(
		repo_root / "README.md",
		"""# Pet Life Diary

A small static demo for tracking everyday pet diary notes.

Open `index.html` in a browser to try the demo.
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
				<h1>Daily notes for tiny companions.</h1>
			</section>
			<form id="diary-form" class="entry-form">
				<label for="diary-entry-input">New diary entry</label>
				<input id="diary-entry-input" name="entry" placeholder="Mochi learned a new trick" />
				<button type="submit">Add entry</button>
			</form>
			<ul id="diary-entry-list" class="entry-list" aria-live="polite"></ul>
		</main>
		<script type="module" src="src/app.js"></script>
	</body>
</html>
""",
	)
	write_text(
		repo_root / "src" / "app.js",
		"""const diaryEntries = [
	{
		text: "Mochi practiced a spin trick.",
		createdAt: "Yesterday",
		species: "Corgi",
	},
	{
		text: "Nori inspected every grocery bag.",
		createdAt: "Today",
		species: "Cat",
	},
];

const form = document.querySelector("#diary-form");
const input = document.querySelector("#diary-entry-input");
const list = document.querySelector("#diary-entry-list");

function renderEntries() {
	if (!list) {
		return;
	}
	list.innerHTML = "";
	for (const entry of diaryEntries) {
		const item = document.createElement("li");
		item.className = "entry-card";
		item.textContent = entry.text + " - " + entry.createdAt;
		list.append(item);
	}
}

form?.addEventListener("submit", (event) => {
	event.preventDefault();
	const text = input.value.trim();
	if (!text) {
		return;
	}
	diaryEntries.push({
		text,
		createdAt: "Just now",
		species: "Corgi",
	});
	input.value = "";
	renderEntries();
});

renderEntries();
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
}

.shell {
	width: min(760px, calc(100% - 32px));
	margin: 0 auto;
	padding: 48px 0;
}

.entry-form {
	display: grid;
	gap: 10px;
	margin: 24px 0;
}

.filter-panel {
	display: grid;
	gap: 8px;
	margin: 16px 0;
}

.entry-card {
	margin: 10px 0;
	padding: 14px 16px;
	border-radius: 18px;
	background: rgba(255, 255, 255, 0.78);
}
""",
	)
	write_text(
		repo_root / "data" / "sample-pets.json",
		json.dumps(
			[
				{"name": "Mochi", "species": "Corgi"},
				{"name": "Nori", "species": "Cat"},
			],
			indent=2,
		)
		+ "\n",
	)


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Create the goal-program Pet Life Diary baseline app.")
	parser.add_argument("--repo-root", required=True)
	parser.add_argument("--dispatch-ref", required=True)
	parser.add_argument("--objective", required=True)
	args = parser.parse_args(argv)
	create_app(Path(args.repo_root).resolve())
	print(args.dispatch_ref)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
