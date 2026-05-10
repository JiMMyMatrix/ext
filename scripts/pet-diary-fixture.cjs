#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

function writeFixtureFile(root, relPath, content) {
	const filePath = path.join(root, relPath);
	fs.mkdirSync(path.dirname(filePath), { recursive: true });
	fs.writeFileSync(filePath, content, 'utf8');
}

function seedBuggyPetDiaryApp(scratchRoot) {
	writeFixtureFile(
		scratchRoot,
		'README.md',
		`# Pet Life Diary

This seeded scratch app has one intentional bug: submitted diary entries are not added to the visible list.

Open index.html in a browser to test it.
`
	);
	writeFixtureFile(
		scratchRoot,
		'index.html',
		`<!doctype html>
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
`
	);
	writeFixtureFile(
		scratchRoot,
		'src/app.js',
		`const diaryEntries = [
	{
		text: "Mochi practiced a spin trick.",
		createdAt: "Yesterday",
	},
	{
		text: "Nori inspected every grocery bag.",
		createdAt: "Today",
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
	input.value = "";
	renderEntries();
});

renderEntries();
`
	);
	writeFixtureFile(
		scratchRoot,
		'src/styles.css',
		`:root {
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

.entry-card {
	margin: 10px 0;
	padding: 14px 16px;
	border-radius: 18px;
	background: rgba(255, 255, 255, 0.78);
}
`
	);
	writeFixtureFile(
		scratchRoot,
		'data/sample-pets.json',
		`${JSON.stringify(
			[
				{ name: 'Mochi', species: 'Corgi' },
				{ name: 'Nori', species: 'Cat' },
			],
			null,
			2
		)}\n`
	);
	spawnSync('git', ['add', 'README.md', 'index.html', 'src/app.js', 'src/styles.css', 'data/sample-pets.json'], {
		cwd: scratchRoot,
		stdio: 'ignore',
	});
	spawnSync(
		'git',
		[
			'-c',
			'user.name=Corgi Process Test',
			'-c',
			'user.email=corgi-process-test@example.invalid',
			'commit',
			'-m',
			'Seed buggy pet diary app',
		],
		{
			cwd: scratchRoot,
			stdio: 'ignore',
		}
	);
}

function main(argv) {
	const [command, scratchRoot] = argv;
	if (command !== 'seed-bugfix' || !scratchRoot) {
		process.stderr.write('Usage: node scripts/pet-diary-fixture.cjs seed-bugfix <scratch-root>\n');
		return 2;
	}
	seedBuggyPetDiaryApp(path.resolve(scratchRoot));
	return 0;
}

if (require.main === module) {
	process.exit(main(process.argv.slice(2)));
}

module.exports = {
	seedBuggyPetDiaryApp,
	writeFixtureFile,
};
