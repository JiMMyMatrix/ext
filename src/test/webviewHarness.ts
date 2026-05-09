import * as assert from 'assert';
import * as vm from 'vm';
import type { ExecutionWindowModel } from '../phase1Model';
import { getExecutionWindowHtml } from '../executionWindowPanel';
import { buildRuntimeErgonomicsKernel } from '../runtimeErgonomicsKernel';

export type SnapshotTextRow = {
	className: string;
	text: string;
};

export type WebviewSnapshotPayload = {
	goalStrip: string;
	actions: SnapshotTextRow[];
	messages: SnapshotTextRow[];
	transcript: SnapshotTextRow[];
	activity: SnapshotTextRow[];
	activityOverflow: SnapshotTextRow[];
	progress: SnapshotTextRow[];
	detailsHidden: number;
	composer: {
		context: string;
		hint: string;
		button: string;
		placeholder: string;
		disabled: boolean;
	};
	state: {
		currentActor: string;
		currentStage: string;
		permissionScope: string;
		runState: string;
		task: string;
	};
};

type PostedWebviewMessage = {
	type: string;
	payload?: WebviewSnapshotPayload;
};

function decodeHtmlEntities(value: string): string {
	return value
		.replace(/&nbsp;/g, ' ')
		.replace(/&amp;/g, '&')
		.replace(/&lt;/g, '<')
		.replace(/&gt;/g, '>')
		.replace(/&quot;/g, '"')
		.replace(/&#39;/g, "'");
}

function htmlToText(value: string): string {
	return decodeHtmlEntities(
		value
			.replace(/<style\b[\s\S]*?<\/style>/gi, '')
			.replace(/<script\b[\s\S]*?<\/script>/gi, '')
			.replace(/<[^>]+>/g, ' ')
			.replace(/\s+/g, ' ')
			.trim()
	);
}

function parseClassName(attributes: string): string {
	return decodeHtmlEntities(attributes.match(/\bclass="([^"]*)"/)?.[1] ?? '');
}

function selectorClasses(selector: string): string[] {
	return selector
		.split(',')
		.map((part) => part.trim())
		.filter((part) => part.startsWith('.'))
		.map((part) => part.slice(1));
}

class FakeWebviewNode {
	constructor(
		readonly className: string,
		readonly innerHTML: string
	) {}

	get textContent(): string {
		return htmlToText(this.innerHTML);
	}

	get innerText(): string {
		return this.textContent;
	}
}

class FakeWebviewElement {
	innerHTML = '';
	textContent = '';
	value = '';
	placeholder = '';
	disabled = false;
	hidden = false;
	scrollTop = 0;
	scrollHeight = 1200;
	clientHeight = 600;
	selectionStart = 0;
	selectionEnd = 0;
	private readonly listeners = new Map<
		string,
		Array<(event: { preventDefault(): void; target: FakeWebviewElement; key?: string }) => void>
	>();

	addEventListener(
		type: string,
		listener: (event: {
			preventDefault(): void;
			target: FakeWebviewElement;
			key?: string;
		}) => void
	): void {
		const listeners = this.listeners.get(type) ?? [];
		listeners.push(listener);
		this.listeners.set(type, listeners);
	}

	requestSubmit(): void {
		for (const listener of this.listeners.get('submit') ?? []) {
			listener({
				preventDefault() {
					// The webview handler expects this browser API.
				},
				target: this,
			});
		}
	}

	focus(): void {
		// No-op for renderer tests.
	}

	get innerText(): string {
		return htmlToText(this.innerHTML || this.textContent || this.value);
	}

	set innerText(value: string) {
		this.textContent = value;
	}

	querySelectorAll(selector: string): FakeWebviewNode[] {
		if (selector === 'button') {
			return parseElementsBySelector(this.innerHTML, ['button'], []);
		}
		return parseElementsBySelector(
			this.innerHTML,
			['article', 'div', 'li', 'details'],
			selectorClasses(selector)
		);
	}
}

function parseElementsBySelector(
	html: string,
	tags: string[],
	requiredClasses: string[]
): FakeWebviewNode[] {
	const nodes: FakeWebviewNode[] = [];
	for (const tag of tags) {
		const pattern = new RegExp('<' + tag + '\\b([^>]*)>([\\s\\S]*?)<\\/' + tag + '>', 'gi');
		for (const match of html.matchAll(pattern)) {
			const className = parseClassName(match[1] ?? '');
			if (
				requiredClasses.length > 0 &&
				!requiredClasses.some((requiredClass) =>
					className.split(/\s+/).includes(requiredClass)
				)
			) {
				continue;
			}
			nodes.push(new FakeWebviewNode(className, match[2] ?? ''));
		}
	}
	return nodes;
}

class FakeWebviewDocument {
	private readonly elements = new Map<string, FakeWebviewElement>();
	private readonly listeners = new Map<
		string,
		Array<(event: { target: { closest(selector: string): null } }) => void>
	>();

	getElementById(id: string): FakeWebviewElement {
		const existing = this.elements.get(id);
		if (existing) {
			return existing;
		}
		const created = new FakeWebviewElement();
		this.elements.set(id, created);
		return created;
	}

	addEventListener(
		type: string,
		listener: (event: { target: { closest(selector: string): null } }) => void
	): void {
		const listeners = this.listeners.get(type) ?? [];
		listeners.push(listener);
		this.listeners.set(type, listeners);
	}
}

class FakeWebviewWindow {
	private readonly listeners = new Map<string, Array<(event: { data: unknown }) => void>>();

	addEventListener(type: string, listener: (event: { data: unknown }) => void): void {
		const listeners = this.listeners.get(type) ?? [];
		listeners.push(listener);
		this.listeners.set(type, listeners);
	}

	dispatchMessage(data: unknown): void {
		for (const listener of this.listeners.get('message') ?? []) {
			listener({ data });
		}
	}
}

export function renderWebviewSnapshot(model: ExecutionWindowModel): WebviewSnapshotPayload {
	const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
	const script = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/)?.[1];
	assert.ok(script, 'Expected generated webview HTML to contain an inline script.');

	const postedMessages: PostedWebviewMessage[] = [];
	const fakeDocument = new FakeWebviewDocument();
	const fakeWindow = new FakeWebviewWindow();
	let persistedState: unknown = undefined;
	let timeoutId = 0;

	const context = {
		acquireVsCodeApi: () => ({
			getState: () => persistedState,
			setState: (value: unknown) => {
				persistedState = value;
			},
			postMessage: (message: PostedWebviewMessage) => {
				postedMessages.push(message);
			},
		}),
		document: fakeDocument,
		window: fakeWindow,
		console,
		Date,
		JSON,
		Math,
		String,
		Array,
		Boolean,
		Number,
		RegExp,
		setTimeout: (callback: () => void) => {
			callback();
			timeoutId += 1;
			return timeoutId;
		},
		clearTimeout: () => {
			// Timers run synchronously in this focused renderer harness.
		},
		setInterval: () => 0,
		clearInterval: () => {
			// No-op for renderer tests.
		},
	};

	vm.runInNewContext(script, context);
	fakeWindow.dispatchMessage({
		type: 'state',
		payload: {
			...model,
			runtimeErgonomics: buildRuntimeErgonomicsKernel(model),
		},
	});

	const snapshot = postedMessages
		.filter((message) => message.type === 'webview_snapshot')
		.at(-1)?.payload;
	assert.ok(snapshot, 'Expected webview renderer to post a monitor snapshot.');
	return snapshot;
}
