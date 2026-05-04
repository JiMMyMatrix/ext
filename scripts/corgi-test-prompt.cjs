#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const catalogPath = path.join(__dirname, 'corgi-test-prompts.json');
const catalog = JSON.parse(fs.readFileSync(catalogPath, 'utf8'));

function prompts() {
	return Array.isArray(catalog.prompts) ? catalog.prompts : [];
}

function validateCatalog() {
	const seen = new Set();
	const errors = [];

	for (const prompt of prompts()) {
		if (!prompt.id || typeof prompt.id !== 'string') {
			errors.push('Prompt entry is missing a string id.');
			continue;
		}
		if (seen.has(prompt.id)) {
			errors.push(`Duplicate prompt id: ${prompt.id}`);
		}
		seen.add(prompt.id);
		for (const field of ['label', 'prompt', 'category', 'purpose', 'requiresScenario']) {
			if (!prompt[field] || typeof prompt[field] !== 'string') {
				errors.push(`${prompt.id} is missing string field ${field}.`);
			}
		}
		for (const field of ['expectedFlow', 'assertions', 'tags']) {
			if (!Array.isArray(prompt[field]) || prompt[field].length === 0) {
				errors.push(`${prompt.id} is missing non-empty array field ${field}.`);
			}
		}
	}

	if (!catalog.defaultPromptId || !seen.has(catalog.defaultPromptId)) {
		errors.push('defaultPromptId must reference a known prompt id.');
	}

	return errors;
}

function promptById(id) {
	return prompts().find((prompt) => prompt.id === id);
}

function printAvailable() {
	process.stdout.write(`${prompts().map((prompt) => prompt.id).join(' ')}\n`);
}

const [command, id] = process.argv.slice(2);
const errors = validateCatalog();
if (errors.length) {
	for (const error of errors) {
		console.error(error);
	}
	process.exit(2);
}

switch (command) {
	case 'default':
		process.stdout.write(`${catalog.defaultPromptId}\n`);
		break;
	case 'get': {
		const prompt = promptById(id ?? catalog.defaultPromptId);
		if (!prompt) {
			console.error(`Unknown Corgi test-window prompt preset: ${id}`);
			console.error('Available presets:');
			printAvailable();
			process.exit(2);
		}
		process.stdout.write(`${prompt.prompt}\n`);
		break;
	}
	case 'list':
		printAvailable();
		break;
	case 'describe': {
		const prompt = promptById(id ?? catalog.defaultPromptId);
		if (!prompt) {
			console.error(`Unknown Corgi test-window prompt preset: ${id}`);
			process.exit(2);
		}
		process.stdout.write(`${JSON.stringify(prompt, null, 2)}\n`);
		break;
	}
	case 'validate':
		process.stdout.write(
			`Validated ${prompts().length} Corgi test-window prompt presets.\n`
		);
		break;
	default:
		console.error(
			'Usage: node scripts/corgi-test-prompt.cjs <default|get|list|describe|validate> [prompt-id]'
		);
		process.exit(2);
}
