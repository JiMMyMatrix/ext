#!/usr/bin/env node

const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { pathToFileURL } = require('url');

const repoRoot = path.resolve(__dirname, '..');
const defaultTestRoot = path.join(os.homedir(), '.corgi', 'test-window', 'extension-ext');

function parseArgs(argv) {
	const args = {
		generate: false,
		workspace: undefined,
	};
	for (let index = 0; index < argv.length; index += 1) {
		const value = argv[index];
		switch (value) {
			case '--generate':
				args.generate = true;
				break;
			case '--workspace':
				args.workspace = argv[index + 1];
				index += 1;
				break;
			case '--help':
				printUsage();
				process.exit(0);
				break;
			default:
				throw new Error(`Unknown argument: ${value}`);
		}
	}
	return args;
}

function printUsage() {
	process.stdout.write(
		[
			'Usage: node scripts/corgi-demo-behavior-test.cjs [--workspace path]',
			'Usage: node scripts/corgi-demo-behavior-test.cjs --generate',
			'',
			'Validates a Corgi-produced Pet Life Diary demo without opening VS Code.',
			'Use --generate for a fresh helper-backed demo workspace, or --workspace to validate a specific Corgi scratch output.',
		].join('\n') + '\n'
	);
}

function readJson(filePath) {
	if (!fs.existsSync(filePath)) {
		return undefined;
	}
	return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function defaultWorkspace() {
	const currentRun = readJson(path.join(defaultTestRoot, 'current-run.json'));
	if (currentRun?.workspaceMode === 'scratch' && currentRun.workspaceRoot) {
		return currentRun.workspaceRoot;
	}
	return path.join(defaultTestRoot, 'scratch-workspaces', 'pet-life-diary-app');
}

function commandPython() {
	if (process.env.ORCHESTRATION_APPROVED_PYTHON) return process.env.ORCHESTRATION_APPROVED_PYTHON;
	if (process.env.CORGI_PYTHON) return process.env.CORGI_PYTHON;
	if (fs.existsSync('/opt/homebrew/bin/python3')) return '/opt/homebrew/bin/python3';
	return 'python3';
}

function generateDemoWorkspace() {
	const workspaceRoot = path.join(repoRoot, '.agent', 'demo-behavior', 'pet-life-diary-app');
	fs.rmSync(workspaceRoot, { recursive: true, force: true });
	fs.mkdirSync(workspaceRoot, { recursive: true });
	const result = spawnSync(
		commandPython(),
		[
			path.join(repoRoot, 'orchestration/scripts/executor_create_product_pet_diary.py'),
			'--repo-root',
			workspaceRoot,
			'--dispatch-ref',
			'demo-behavior',
			'--objective',
			'Generate Pet Life Diary demo for repeatable behavior validation.',
		],
		{
			cwd: repoRoot,
			encoding: 'utf8',
			maxBuffer: 1024 * 1024 * 10,
		}
	);
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || 'Failed to generate Pet Life Diary demo workspace');
	}
	fs.writeFileSync(path.join(workspaceRoot, 'package.json'), '{"type":"module"}\n', 'utf8');
	return workspaceRoot;
}

function assertCondition(condition, message) {
	if (!condition) {
		throw new Error(message);
	}
}

function fileType(filePath) {
	if (filePath.endsWith('.html')) return 'text/html; charset=utf-8';
	if (filePath.endsWith('.css')) return 'text/css; charset=utf-8';
	if (filePath.endsWith('.js')) return 'text/javascript; charset=utf-8';
	if (filePath.endsWith('.json')) return 'application/json; charset=utf-8';
	return 'application/octet-stream';
}

function safeResolve(root, urlPath) {
	const decoded = decodeURIComponent(urlPath.split('?')[0] || '/');
	const relPath = decoded === '/' ? 'index.html' : decoded.replace(/^\/+/, '');
	const filePath = path.resolve(root, relPath);
	if (!filePath.startsWith(`${path.resolve(root)}${path.sep}`) && filePath !== path.resolve(root)) {
		return undefined;
	}
	return filePath;
}

function startStaticServer(workspaceRoot) {
	const server = http.createServer((request, response) => {
		const filePath = safeResolve(workspaceRoot, request.url || '/');
		if (!filePath || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
			response.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
			response.end('not found');
			return;
		}
		response.writeHead(200, { 'content-type': fileType(filePath) });
		if (request.method === 'HEAD') {
			response.end();
			return;
		}
		fs.createReadStream(filePath).pipe(response);
	});
	return new Promise((resolve, reject) => {
		server.once('error', reject);
		server.listen(0, '127.0.0.1', () => {
			const address = server.address();
			resolve({ server, baseUrl: `http://127.0.0.1:${address.port}` });
		});
	});
}

async function assertServesAssets(workspaceRoot) {
	const requiredFiles = [
		'index.html',
		'src/app.js',
		'src/ui.js',
		'src/state.js',
		'src/styles.css',
		'data/sample-pets.json',
	];
	for (const relPath of requiredFiles) {
		assertCondition(fs.existsSync(path.join(workspaceRoot, relPath)), `Missing demo file: ${relPath}`);
	}
	const { server, baseUrl } = await startStaticServer(workspaceRoot);
	try {
		for (const relPath of ['/', '/src/app.js', '/src/styles.css', '/data/sample-pets.json']) {
			const response = await fetch(`${baseUrl}${relPath}`, { method: 'HEAD' });
			assertCondition(response.status === 200, `${relPath} returned HTTP ${response.status}`);
		}
		return baseUrl;
	} finally {
		await new Promise((resolve) => server.close(resolve));
	}
}

class NodeShim {
	constructor() {
		this.parentNode = null;
	}
}

class TextNodeShim extends NodeShim {
	constructor(value) {
		super();
		this.nodeType = 3;
		this.value = String(value);
	}

	get textContent() {
		return this.value;
	}

	set textContent(value) {
		this.value = String(value);
	}
}

class ClassListShim {
	constructor(element) {
		this.element = element;
	}

	toggle(className, force) {
		const classes = new Set(this.element.className.split(/\s+/).filter(Boolean));
		const shouldAdd = force === undefined ? !classes.has(className) : Boolean(force);
		if (shouldAdd) {
			classes.add(className);
		} else {
			classes.delete(className);
		}
		this.element.className = [...classes].join(' ');
		return shouldAdd;
	}
}

class ElementShim extends NodeShim {
	constructor(tagName) {
		super();
		this.nodeType = 1;
		this.tagName = tagName.toUpperCase();
		this.children = [];
		this.attributes = new Map();
		this.dataset = {};
		this.eventListeners = new Map();
		this.className = '';
		this.value = '';
		this.id = '';
		this.name = '';
		this.required = false;
		this.rows = '';
		this.readOnly = false;
		this.placeholder = '';
		this.classList = new ClassListShim(this);
	}

	append(...nodes) {
		for (const node of nodes) {
			this.appendChild(node);
		}
	}

	appendChild(node) {
		const child = node instanceof NodeShim ? node : new TextNodeShim(node);
		child.parentNode = this;
		this.children.push(child);
		return child;
	}

	replaceChildren(...nodes) {
		for (const child of this.children) {
			child.parentNode = null;
		}
		this.children = [];
		this.append(...nodes);
	}

	remove() {
		if (!this.parentNode) {
			return;
		}
		this.parentNode.children = this.parentNode.children.filter((child) => child !== this);
		this.parentNode = null;
	}

	focus() {
		this.ownerDocument.activeElement = this;
	}

	reset() {
		for (const element of descendants(this)) {
			if (['INPUT', 'TEXTAREA'].includes(element.tagName)) {
				element.value = '';
			}
			if (element.tagName === 'SELECT') {
				const firstOption = element.children.find((child) => child instanceof ElementShim);
				element.value = firstOption?.value || '';
			}
		}
	}

	click() {
		this.dispatchEvent({ type: 'click', preventDefault() {} });
	}

	addEventListener(type, listener) {
		const listeners = this.eventListeners.get(type) || [];
		listeners.push(listener);
		this.eventListeners.set(type, listeners);
	}

	dispatchEvent(event) {
		event.target = event.target || this;
		for (const listener of this.eventListeners.get(event.type) || []) {
			listener.call(this, event);
		}
		return true;
	}

	setAttribute(name, value) {
		const stringValue = String(value);
		this.attributes.set(name, stringValue);
		if (name === 'class') this.className = stringValue;
		if (name === 'id') this.id = stringValue;
		if (name === 'name') this.name = stringValue;
		if (name === 'placeholder') this.placeholder = stringValue;
		if (name.startsWith('data-')) {
			this.dataset[dataKey(name.slice(5))] = stringValue;
		}
	}

	getAttribute(name) {
		if (name === 'class') return this.className || null;
		if (name === 'id') return this.id || null;
		if (name === 'name') return this.name || null;
		if (name === 'placeholder') return this.placeholder || null;
		if (name.startsWith('data-')) {
			const key = dataKey(name.slice(5));
			return Object.prototype.hasOwnProperty.call(this.dataset, key) ? this.dataset[key] : null;
		}
		return this.attributes.get(name) || null;
	}

	get childElementCount() {
		return this.children.filter((child) => child instanceof ElementShim).length;
	}

	get textContent() {
		return this.children.map((child) => child.textContent).join('');
	}

	set textContent(value) {
		this.replaceChildren(new TextNodeShim(value));
	}

	set innerHTML(_value) {
		this.replaceChildren();
	}

	get innerHTML() {
		return this.textContent;
	}

	querySelector(selector) {
		return this.querySelectorAll(selector)[0] || null;
	}

	querySelectorAll(selector) {
		return selectAll(this, selector);
	}
}

class DocumentShim extends ElementShim {
	constructor() {
		super('#document');
		this.ownerDocument = this;
		this.activeElement = null;
		this.body = new ElementShim('body');
		this.body.ownerDocument = this;
		this.appendChild(this.body);
	}

	createElement(tagName) {
		const element = new ElementShim(tagName);
		element.ownerDocument = this;
		return element;
	}

	createTextNode(value) {
		return new TextNodeShim(value);
	}
}

class LocalStorageShim {
	constructor() {
		this.values = new Map();
	}

	getItem(key) {
		return this.values.has(key) ? this.values.get(key) : null;
	}

	setItem(key, value) {
		this.values.set(key, String(value));
	}

	removeItem(key) {
		this.values.delete(key);
	}

	clear() {
		this.values.clear();
	}
}

class FormDataShim {
	constructor(form) {
		this.values = new Map();
		for (const element of descendants(form)) {
			if (element.name) {
				this.values.set(element.name, element.value || '');
			}
		}
	}

	get(key) {
		return this.values.get(key) ?? null;
	}
}

function dataKey(value) {
	return value.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function descendants(root) {
	const nodes = [];
	for (const child of root.children || []) {
		if (child instanceof ElementShim) {
			nodes.push(child);
			nodes.push(...descendants(child));
		}
	}
	return nodes;
}

function selectAll(root, selector) {
	const parts = selector.split(',').map((part) => part.trim()).filter(Boolean);
	if (parts.length > 1) {
		return [...new Set(parts.flatMap((part) => selectAll(root, part)))];
	}
	const descendantParts = selector.split(/\s+/).filter(Boolean);
	let candidates = [root];
	for (const part of descendantParts) {
		candidates = candidates.flatMap((candidate) =>
			descendants(candidate).filter((element) => matchesSimpleSelector(element, part))
		);
	}
	return candidates;
}

function matchesSimpleSelector(element, selector) {
	if (selector.startsWith('#')) {
		return element.id === selector.slice(1);
	}
	const attrMatch = selector.match(/^(?:(?<tag>[a-zA-Z0-9-]+))?\[(?<name>[^\]=]+)(?:="(?<value>[^"]*)")?\]$/);
	if (attrMatch) {
		const tag = attrMatch.groups.tag;
		const attrName = attrMatch.groups.name;
		const expected = attrMatch.groups.value;
		if (tag && element.tagName.toLowerCase() !== tag.toLowerCase()) {
			return false;
		}
		const actual = element.getAttribute(attrName);
		return expected === undefined ? actual !== null : actual === expected;
	}
	return element.tagName.toLowerCase() === selector.toLowerCase();
}

function element(document, tagName, options = {}) {
	const node = document.createElement(tagName);
	if (options.id) node.setAttribute('id', options.id);
	if (options.className) node.className = options.className;
	if (options.text) node.textContent = options.text;
	if (options.name) node.setAttribute('name', options.name);
	if (options.placeholder) node.setAttribute('placeholder', options.placeholder);
	if (options.required) node.required = true;
	if (options.rows) node.rows = String(options.rows);
	for (const [key, value] of Object.entries(options.dataset || {})) {
		node.dataset[key] = value;
	}
	return node;
}

function buildPetDiaryDom(document) {
	const shell = element(document, 'div', { dataset: { appShell: '' } });
	document.body.appendChild(shell);
	const openEditor = element(document, 'button', { text: 'Add diary entry', dataset: { action: 'open-editor' } });
	const exportData = element(document, 'button', { text: 'Export data', dataset: { action: 'export-data' } });
	shell.append(openEditor, exportData);
	for (const target of ['dashboard', 'timeline', 'pets', 'routines', 'insights']) {
		shell.append(element(document, 'button', { text: target, dataset: { viewTarget: target } }));
	}
	const main = element(document, 'main');
	shell.append(main);
	for (const view of ['dashboard', 'timeline', 'pets', 'routines', 'insights']) {
		main.append(element(document, 'section', { dataset: { view }, className: view === 'dashboard' ? 'view is-active' : 'view' }));
	}
	const dashboard = document.querySelector('[data-view="dashboard"]');
	dashboard.append(
		element(document, 'div', { dataset: { metricGrid: '' } }),
		element(document, 'ul', { dataset: { reminderList: '' } }),
		element(document, 'div', { dataset: { highlightList: '' } })
	);
	const timeline = document.querySelector('[data-view="timeline"]');
	const species = element(document, 'select', { id: 'species-filter', dataset: { filterSpecies: '' } });
	const tag = element(document, 'select', { id: 'tag-filter', dataset: { filterTag: '' } });
	const search = element(document, 'input', { placeholder: 'Search diary entries', dataset: { search: '' } });
	const form = element(document, 'form', { dataset: { entryForm: '' } });
	form.append(
		element(document, 'select', { name: 'petId', dataset: { petSelect: '' } }),
		element(document, 'input', { name: 'title', required: true }),
		element(document, 'select', { name: 'mood', dataset: { moodSelect: '' } }),
		element(document, 'input', { name: 'tags', placeholder: 'walk, meal' }),
		element(document, 'textarea', { name: 'body', rows: 5, required: true }),
		element(document, 'button', { text: 'Save diary entry' })
	);
	timeline.append(species, tag, search, form, element(document, 'section', { dataset: { entryList: '' } }));
	document.querySelector('[data-view="pets"]').append(element(document, 'div', { dataset: { petGrid: '' } }));
	document.querySelector('[data-view="routines"]').append(element(document, 'div', { dataset: { routineBoard: '' } }));
	const insights = document.querySelector('[data-view="insights"]');
	insights.append(
		element(document, 'div', { dataset: { insightGrid: '' } }),
		element(document, 'button', { text: 'Copy JSON', dataset: { action: 'copy-json' } }),
		element(document, 'button', { text: 'Reset demo', dataset: { action: 'reset-demo' } }),
		element(document, 'textarea', { dataset: { jsonPreview: '' } }),
		element(document, 'textarea', { id: 'import-json', placeholder: 'Paste an exported Pet Life Diary JSON backup', dataset: { importJson: '' } }),
		element(document, 'button', { text: 'Import backup', dataset: { action: 'import-json' } }),
		element(document, 'p', { text: 'Imports validate pets and entries before replacing local data.', dataset: { importStatus: '' } })
	);
}

async function assertDomBehavior(workspaceRoot) {
	const document = new DocumentShim();
	buildPetDiaryDom(document);
	const alerts = [];
	const errors = [];
	global.Node = NodeShim;
	global.document = document;
	global.window = {
		document,
		localStorage: new LocalStorageShim(),
		alert(message) {
			alerts.push(String(message));
		},
	};
	global.navigator = { clipboard: { writeText: async () => true } };
	global.FormData = FormDataShim;
	global.Blob = class BlobShim {
		constructor(parts, options) {
			this.parts = parts;
			this.options = options;
		}
	};
	global.URL = {
		createObjectURL() {
			return 'blob:corgi-demo-test';
		},
		revokeObjectURL() {},
	};
	const originalConsoleError = console.error;
	console.error = (...args) => {
		errors.push(args.map(String).join(' '));
		originalConsoleError(...args);
	};
	try {
		const appUrl = `${pathToFileURL(path.join(workspaceRoot, 'src/app.js')).href}?corgiDemoTest=${Date.now()}`;
		await import(appUrl);
		const entryList = document.querySelector('[data-entry-list]');
		const initialEntryCount = entryList.children.length;
		assertCondition(initialEntryCount > 0, 'Timeline did not render initial entries');
		const initialTimelineText = entryList.textContent;
		assertCondition(
			!initialTimelineText.includes('Codex repeatable demo check'),
			'Demo workspace already contains the repeatable test entry before submission'
		);
		const titleInput = document.querySelector('[data-entry-form] input[name="title"]');
		const tagsInput = document.querySelector('[data-entry-form] input[name="tags"]');
		const bodyInput = document.querySelector('[data-entry-form] textarea[name="body"]');
		const form = document.querySelector('[data-entry-form]');
		titleInput.value = 'Codex repeatable demo check';
		tagsInput.value = 'demo, sanity';
		bodyInput.value = 'The command-only demo behavior test added this visible diary entry.';
		form.dispatchEvent({
			type: 'submit',
			preventDefault() {
				this.defaultPrevented = true;
			},
		});
		const timelineText = entryList.textContent;
		const highlightText = document.querySelector('[data-highlight-list]').textContent;
		const storagePayload = window.localStorage.getItem('pet-life-diary.product-demo.v1');
		assertCondition(alerts.length === 0, `Unexpected alert: ${alerts.join('; ')}`);
		assertCondition(errors.length === 0, `Console errors: ${errors.join('; ')}`);
		assertCondition(entryList.children.length > 0, 'Timeline became empty after submitting an entry');
		assertCondition(
			timelineText.includes('Codex repeatable demo check'),
			'Submitted entry title was not visible in the timeline'
		);
		assertCondition(
			highlightText.includes('Codex repeatable demo check'),
			'Submitted entry title was not visible in dashboard highlights'
		);
		assertCondition(
			storagePayload && storagePayload.includes('Codex repeatable demo check'),
			'Submitted entry was not persisted to localStorage'
		);
		return {
			initialEntryCount,
			finalEntryCount: entryList.children.length,
			renderedTitle: 'Codex repeatable demo check',
		};
	} finally {
		console.error = originalConsoleError;
	}
}

async function main() {
	const args = parseArgs(process.argv.slice(2));
	const workspaceRoot = path.resolve(
		args.generate ? generateDemoWorkspace() : args.workspace || defaultWorkspace()
	);
	assertCondition(
		isAllowedDemoWorkspace(workspaceRoot),
		`Refusing to run demo behavior test against the Corgi development repo: ${workspaceRoot}`
	);
	assertCondition(fs.existsSync(workspaceRoot), `Demo workspace does not exist: ${workspaceRoot}`);
	const baseUrl = await assertServesAssets(workspaceRoot);
	const behavior = await assertDomBehavior(workspaceRoot);
	const report = {
		ok: true,
		workspaceRoot,
		baseUrl,
		behavior,
	};
	process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}

function isAllowedDemoWorkspace(workspaceRoot) {
	if (workspaceRoot === repoRoot) {
		return false;
	}
	if (workspaceRoot.startsWith(`${defaultTestRoot}${path.sep}`)) {
		return workspaceRoot.includes(`${path.sep}scratch-workspaces${path.sep}`);
	}
	if (workspaceRoot.startsWith(`${path.join(repoRoot, '.agent', 'command-test')}${path.sep}`)) {
		return workspaceRoot.endsWith(`${path.sep}scratch-workspace`);
	}
	if (workspaceRoot.startsWith(`${path.join(repoRoot, '.agent', 'test-window')}${path.sep}`)) {
		return workspaceRoot.includes(`${path.sep}scratch-workspaces${path.sep}`);
	}
	if (workspaceRoot.startsWith(`${path.join(repoRoot, '.agent', 'demo-behavior')}${path.sep}`)) {
		return true;
	}
	return false;
}

main().catch((error) => {
	process.stderr.write(`${error.stack || error.message}\n`);
	process.exit(1);
});
