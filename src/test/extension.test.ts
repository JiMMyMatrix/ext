import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vm from 'vm';
import * as vscode from 'vscode';
import {
	applyModelAction,
	createInitialModel,
	type ExecutionWindowModel,
	getArtifactById,
	isSnapshotStale,
	type SemanticActionName,
	type SemanticRouteType,
} from '../phase1Model';
import {
	createExecutionTransport,
	resolveGovernorRoute,
	resolveExecutionTransportTarget,
	TransportUnavailableError,
} from '../executionTransport';
import {
	AppServerSemanticRunner,
	createSemanticRunner,
	CodexSemanticRunner,
	DEFAULT_SEMANTIC_SIDECAR_MODEL,
	resolveSemanticRouting,
	SemanticSidecar,
	type SemanticDecision,
	type SemanticRunner,
} from '../semanticSidecar';
import {
	EXECUTION_WINDOW_CONTAINER_ID,
	EXECUTION_WINDOW_VIEW_ID,
	getExecutionWindowHtml,
	OPEN_EXECUTION_WINDOW_COMMAND_ID,
} from '../executionWindowPanel';
import {
	buildRuntimeErgonomicsKernel,
	runtimeVisibilityForFeedItem,
	summaryForActivity,
} from '../runtimeErgonomicsKernel';

const PACKAGE_JSON_PATH = path.resolve(__dirname, '../../package.json');
const LAUNCH_JSON_PATH = path.resolve(__dirname, '../../.vscode/launch.json');
const EXTENSION_TS_PATH = path.resolve(__dirname, '../../src/extension.ts');
const DEVELOPMENT_SESSION_TS_PATH = path.resolve(
	__dirname,
	'../../src/developmentSession.ts'
);
const EXECUTION_WINDOW_PANEL_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionWindowPanel.ts'
);
const EXECUTION_TRANSPORT_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionTransport.ts'
);
const TEST_WINDOW_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/launch-corgi-test-window.sh'
);
const TEST_WINDOW_CLOSE_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/close-corgi-test-window.sh'
);
const TEST_WINDOW_AUTO_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/run-corgi-test-window-auto.sh'
);
const TEST_WINDOW_PROMPT_CATALOG_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-test-prompts.json'
);
const TEST_WINDOW_PROMPT_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-test-prompt.cjs'
);
const TEST_WINDOW_STATUS_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-test-window-status.cjs'
);
const PROCESS_TEST_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-process-test.cjs'
);
const PROCESS_REPLAN_HELPER_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-review-replan-process-test.py'
);
const CODEX_APP_SERVER_CLIENT_TS_PATH = path.resolve(
	__dirname,
	'../../src/codexAppServerClient.ts'
);
const GOVERNOR_RUNTIME_TS_PATH = path.resolve(
	__dirname,
	'../../src/governorRuntime.ts'
);
const RUNTIME_ERGONOMICS_KERNEL_TS_PATH = path.resolve(
	__dirname,
	'../../src/runtimeErgonomicsKernel.ts'
);
const GOVERNOR_RUNTIME_CONFIG_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/config.toml'
);
const MCP_SERVER_ENTRYPOINT_PATH = path.resolve(__dirname, '../../mcp_server.py');
const DEV_MCP_SERVER_ENTRYPOINT_PATH = path.resolve(__dirname, '../../dev_mcp_server.py');
const ADVISORY_MCP_LAUNCHER_PATH = path.resolve(
	__dirname,
	'../../orchestration/scripts/serve_advisory_mcp.py'
);
const DEVELOPMENT_CONSULTING_MCP_LAUNCHER_PATH = path.resolve(
	__dirname,
	'../../orchestration/scripts/serve_development_consulting_mcp.py'
);
const ADVISORY_MCP_SETUP_PATH = path.resolve(
	__dirname,
	'../../orchestration/scripts/setup_advisory_mcp_env.py'
);
const ADVISORY_MCP_REQUIREMENTS_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/advisory/requirements.txt'
);
const ADVISORY_MCP_SERVER_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/advisory/mcp_server.py'
);
const ADVISORY_CAPABILITIES_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/advisory/capabilities.json'
);
const ADVISORY_DOC_PATH = path.resolve(__dirname, '../../orchestration/advisory.md');
const UX_CONTRACT_PATH = path.resolve(__dirname, '../../orchestration/contracts/ux.md');
const SEMANTIC_ROUTING_FIXTURE_PATH = path.resolve(
	__dirname,
	'../../src/test/fixtures/semantic-routing.json'
);

function loadPackageJson(): Record<string, unknown> {
	return JSON.parse(fs.readFileSync(PACKAGE_JSON_PATH, 'utf8')) as Record<string, unknown>;
}

function semanticContextFlags() {
	return {
		used_controller_summary: true,
		used_accepted_intake_summary: false,
		used_dialogue_summary: false,
		had_active_clarification: false,
		had_pending_permission_request: false,
		had_pending_interrupt: false,
	};
}

function semanticDecision(
	overrides: Partial<SemanticDecision>
): SemanticDecision {
	return {
		route_type: 'governed_work_intent',
		action_name: 'none',
		normalized_text: 'analyze the repo',
		paraphrase: 'Ask Corgi to analyze the repo.',
		confidence: 'high',
		reason: 'clear_work_intent',
		...overrides,
	};
}

function semanticRunnerInput(
	rawText: string
): Parameters<AppServerSemanticRunner['classify']>[0] {
	return {
		rawText,
		summary: {
			current_turn: rawText,
			controller_state: {
				permission_scope: 'unset',
				run_state: 'idle',
			},
			active_clarification: null,
			pending_permission_request: null,
			pending_interrupt: null,
			accepted_intake_summary: null,
			recent_dialogue_summary: [],
			semantic_clarification_state: null,
		},
	};
}

function semanticFallbackRunner(decision: SemanticDecision): SemanticRunner {
	return {
		classify: async () => decision,
	};
}

type SemanticRoutingFixture = {
	name: string;
	input: string;
	session_state: 'idle' | 'active_clarification' | 'pending_permission' | 'running';
	expected_route_type: SemanticRouteType;
	expected_action_name: SemanticActionName;
	expected_outcome:
		| 'submit_prompt'
		| 'answer_clarification'
		| 'interrupt_run'
		| 'block';
	notes: string;
};

type SnapshotTextRow = {
	className: string;
	text: string;
};

type WebviewSnapshotPayload = {
	goalStrip: string;
	actions: SnapshotTextRow[];
	messages: SnapshotTextRow[];
	transcript: SnapshotTextRow[];
	activity: SnapshotTextRow[];
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
	private readonly listeners = new Map<string, Array<(event: { preventDefault(): void; target: FakeWebviewElement; key?: string }) => void>>();

	addEventListener(
		type: string,
		listener: (event: { preventDefault(): void; target: FakeWebviewElement; key?: string }) => void
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
		return parseElementsBySelector(this.innerHTML, ['article', 'div', 'li'], selectorClasses(selector));
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
				!requiredClasses.some((requiredClass) => className.split(/\s+/).includes(requiredClass))
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
	private readonly listeners = new Map<string, Array<(event: { target: { closest(selector: string): null } }) => void>>();

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

function renderWebviewSnapshot(model: ExecutionWindowModel): WebviewSnapshotPayload {
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

function semanticFixtureModel(state: SemanticRoutingFixture['session_state']): ExecutionWindowModel {
	const model = createInitialModel('2026-04-10T10:00:00.000Z');
	if (state === 'active_clarification') {
		return {
			...model,
			activeClarification: {
				id: 'clarification-test',
				contextRef: 'clarification-test',
				title: 'Clarification required',
				body: 'What kind of analysis do you want?',
				requestedAt: '2026-04-10T10:00:00.000Z',
				options: [
					{
						id: 'architecture',
						label: 'Architecture',
						answer: 'Focus on architecture.',
					},
				],
				allowFreeText: true,
			},
		};
	}
	if (state === 'pending_permission') {
		return {
			...model,
			snapshot: {
				...model.snapshot,
				currentActor: 'orchestration',
				currentStage: 'permission_needed',
				pendingPermissionRequest: {
					id: 'permission-test',
					contextRef: 'permission-test',
					title: 'Permission needed',
					body: 'Choose Plan to continue this request.',
					requestedAt: '2026-04-10T10:00:00.000Z',
					recommendedScope: 'plan',
					allowedScopes: ['observe', 'plan', 'execute'],
				},
			},
		};
	}
	if (state === 'running') {
		return {
			...model,
			snapshot: {
				...model.snapshot,
				currentActor: 'governor',
				currentStage: 'running',
				runState: 'running',
			},
		};
	}
	return model;
}

suite('Corgi Webview UX', () => {
	test('ships sidebar webview contributions and a focused open command without chat participants', () => {
		const manifest = loadPackageJson();
		const contributes = manifest.contributes as Record<string, unknown>;
		const activationEvents = manifest.activationEvents as string[];
		const viewsContainers = contributes.viewsContainers as Record<string, unknown>;
		const views = contributes.views as Record<string, unknown>;
		const commands = contributes.commands as Array<Record<string, unknown>>;

		assert.ok(Array.isArray(activationEvents));
		assert.ok(viewsContainers.activitybar);
		assert.ok(views[EXECUTION_WINDOW_CONTAINER_ID]);
		assert.strictEqual(contributes.chatParticipants, undefined);
		assert.ok(commands.some((command) => command.command === OPEN_EXECUTION_WINDOW_COMMAND_ID));
		assert.ok(activationEvents.includes('onStartupFinished'));
		assert.ok(activationEvents.includes(`onCommand:${OPEN_EXECUTION_WINDOW_COMMAND_ID}`));
		assert.ok(!activationEvents.some((event) => event.startsWith('onChatParticipant:')));
	});

	test('opens the Corgi sidebar view without throwing', async () => {
		await assert.doesNotReject(async () => {
			await vscode.commands.executeCommand(OPEN_EXECUTION_WINDOW_COMMAND_ID);
		});
	});

	test('webview inline script is valid JavaScript', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
		const scriptMatch = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/);

		assert.ok(scriptMatch, 'Expected the generated webview HTML to contain an inline script.');
		assert.doesNotThrow(() => new vm.Script(scriptMatch?.[1] ?? ''));
	});

	test('debug launch opens the current repo as the workspace', () => {
		const launchJson = fs.readFileSync(LAUNCH_JSON_PATH, 'utf8');

		assert.match(
			launchJson,
			/"args"\s*:\s*\[\s*"--extensionDevelopmentPath=\$\{workspaceFolder\}"\s*,\s*"\$\{workspaceFolder\}"/s
		);
	});

	test('development resets no longer depend on launch env flags', () => {
		const extensionSource = fs.readFileSync(EXTENSION_TS_PATH, 'utf8');
		const developmentSessionSource = fs.readFileSync(
			DEVELOPMENT_SESSION_TS_PATH,
			'utf8'
		);
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');
		const launchScriptSource = fs.readFileSync(TEST_WINDOW_SCRIPT_PATH, 'utf8');
		const closeScriptSource = fs.readFileSync(TEST_WINDOW_CLOSE_SCRIPT_PATH, 'utf8');
		const autoScriptSource = fs.readFileSync(TEST_WINDOW_AUTO_SCRIPT_PATH, 'utf8');
		const promptCatalogSource = fs.readFileSync(TEST_WINDOW_PROMPT_CATALOG_PATH, 'utf8');
		const promptScriptSource = fs.readFileSync(TEST_WINDOW_PROMPT_SCRIPT_PATH, 'utf8');
		const statusScriptSource = fs.readFileSync(TEST_WINDOW_STATUS_SCRIPT_PATH, 'utf8');
		const processTestSource = fs.readFileSync(PROCESS_TEST_SCRIPT_PATH, 'utf8');
		const promptCatalog = JSON.parse(promptCatalogSource) as {
			defaultPromptId: string;
			prompts: Array<{
				id: string;
				prompt: string;
				category: string;
				requiresScenario: string;
				expectedFlow: string[];
				assertions: string[];
				tags: string[];
			}>;
		};
		const packageJson = loadPackageJson();
		const scripts = packageJson.scripts as Record<string, string>;

		assert.ok(
			developmentSessionSource.includes(
				'context.extensionMode === vscode.ExtensionMode.Development'
			)
		);
		assert.ok(developmentSessionSource.includes('CORGI_TEST_WINDOW_SCENARIO'));
		assert.ok(developmentSessionSource.includes('ui_session.json'));
		assert.ok(developmentSessionSource.includes('resolveExecutionTransportTarget'));
		assert.ok(extensionSource.includes('scheduleDevelopmentExecutionWindowOpen'));
		assert.ok(extensionSource.includes('void provider.openView().catch'));
		assert.ok(extensionSource.includes('resetDevelopmentSessionState(context);'));
		assert.ok(webviewSource.includes('didResetDevelopmentSessionState'));
		assert.ok(webviewSource.includes('resetDevelopmentSessionStateOnce'));
		assert.ok(webviewSource.includes('resetDevelopmentSessionState(this.context);'));
		assert.ok(webviewSource.includes('testWindowAutoPrompt'));
		assert.ok(webviewSource.includes('testWindowAutoStepMode'));
		assert.ok(webviewSource.includes('auto-submit test prompt'));
		assert.ok(webviewSource.includes('runTestWindowAutoStep'));
		assert.ok(webviewSource.includes('return context.extensionMode === vscode.ExtensionMode.Development;'));
		assert.ok(launchScriptSource.includes('seed_executor_test_session.py'));
		assert.ok(launchScriptSource.includes('seed_reviewer_test_session.py'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_SCENARIO'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_AUTO_PROMPT'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_AUTO_STEPS'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_PROMPT_PRESET'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_WORKSPACE_MODE'));
		assert.ok(launchScriptSource.includes('WORKSPACE_MODE="${CORGI_TEST_WINDOW_WORKSPACE_MODE:-scratch}"'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_SCRATCH_ID'));
		assert.ok(launchScriptSource.includes('Unsafe Corgi scratch workspace id'));
		assert.ok(launchScriptSource.includes('ORCHESTRATION_TARGET_WORKSPACE_MODE'));
		assert.ok(launchScriptSource.includes('ORCHESTRATION_TEST_PROMPT_PRESET'));
		assert.ok(launchScriptSource.includes('scratch-workspaces'));
		assert.ok(launchScriptSource.includes('current-run.json'));
		assert.ok(launchScriptSource.includes('ORCHESTRATION_SOURCE_ROOT'));
		assert.ok(launchScriptSource.includes('corgi-test-prompt.cjs'));
		assert.ok(launchScriptSource.includes('"$CLOSE_SCRIPT"'));
		assert.ok(launchScriptSource.includes('CORGI_SEMANTIC_MODE="${CORGI_SEMANTIC_MODE:-sidecar-first}"'));
		assert.ok(launchScriptSource.includes('CORGI_SEMANTIC_SIDECAR_RUNTIME="${CORGI_SEMANTIC_SIDECAR_RUNTIME:-app-server}"'));
		assert.ok(!launchScriptSource.includes('pkill -f "$USER_DATA_DIR"'));
		assert.ok(!launchScriptSource.includes('pkill -9 -f "$USER_DATA_DIR"'));
		assert.ok(closeScriptSource.includes('assert_test_profile_path'));
		assert.ok(closeScriptSource.includes('Refusing to close non-test VS Code profile'));
		assert.ok(closeScriptSource.includes('$ROOT_DIR/.agent/test-window/'));
		assert.ok(closeScriptSource.includes('pkill -TERM -f "$profile_dir"'));
		assert.ok(!closeScriptSource.includes('pkill -f "$APP_NAME"'));
		assert.ok(!closeScriptSource.includes('pkill -f "Visual Studio Code"'));
		assert.ok(autoScriptSource.includes('trap cleanup EXIT'));
		assert.ok(autoScriptSource.includes('close-corgi-test-window.sh'));
		assert.ok(autoScriptSource.includes('corgi-test-window-status.cjs'));
		assert.ok(autoScriptSource.includes('CORGI_TEST_WINDOW_SNAPSHOT_GRACE_SECONDS'));
		assert.ok(autoScriptSource.includes('PROMPT_PRESET="${CORGI_TEST_WINDOW_PROMPT_PRESET:-pet-life-diary-static}"'));
		assert.ok(autoScriptSource.includes('AUTO_STEPS="${CORGI_TEST_WINDOW_AUTO_STEPS:-execute}"'));
		assert.ok(autoScriptSource.includes('WORKSPACE_MODE="${CORGI_TEST_WINDOW_WORKSPACE_MODE:-scratch}"'));
		assert.ok(autoScriptSource.includes('governor_decision_recorded'));
		assert.ok(autoScriptSource.includes('executor_completed'));
		assert.ok(autoScriptSource.includes('exited before reaching the expected checkpoint'));
		assert.ok(!autoScriptSource.includes('run_state'));
		assert.ok(promptScriptSource.includes('validateCatalog'));
		assert.ok(statusScriptSource.includes('corgi_webview_snapshot.json'));
		assert.ok(statusScriptSource.includes('current-run.json'));
		assert.ok(statusScriptSource.includes('workspaceMode'));
		assert.ok(statusScriptSource.includes('workspaceRoot'));
		assert.ok(statusScriptSource.includes('agentRoot'));
		assert.ok(statusScriptSource.includes('relevantLogErrors'));
		assert.ok(statusScriptSource.includes('isKnownBenignVsCodeLogLine'));
		assert.ok(statusScriptSource.includes('GPU process exited unexpectedly: exit_code=15'));
		assert.ok(statusScriptSource.includes('Render frame was disposed before WebFrameMain could be accessed'));
		assert.ok(statusScriptSource.includes('Visual%20Studio%20Code'));
		assert.ok(statusScriptSource.includes('processAlive'));
		assert.ok(statusScriptSource.includes('feedHasError'));
		assert.ok(statusScriptSource.includes('knownBlockingError'));
		assert.ok(!statusScriptSource.includes('visibleError'));
		assert.ok(processTestSource.includes('ORCHESTRATION_AGENT_ROOT'));
		assert.ok(processTestSource.includes('ORCHESTRATION_SOURCE_ROOT'));
		assert.ok(processTestSource.includes('ORCHESTRATION_TARGET_WORKSPACE_MODE'));
		assert.ok(processTestSource.includes('ORCHESTRATION_TEST_PROMPT_PRESET'));
		assert.ok(processTestSource.includes('createScratchTestEnv'));
		assert.ok(processTestSource.includes('scratch-static-app'));
		assert.ok(processTestSource.includes('pet-life-diary-static'));
		assert.ok(processTestSource.includes('ORCHESTRATION_APPROVED_PYTHON'));
		assert.ok(processTestSource.includes('--auto-consume-executor'));
		assert.ok(processTestSource.includes('--module'));
		assert.ok(processTestSource.includes('assertExecutorArtifacts'));
		assert.ok(processTestSource.includes('assertReviewerArtifacts'));
		assert.ok(processTestSource.includes('runReviewReplanModule'));
		assert.ok(processTestSource.includes('corgi-review-replan-process-test.py'));
		assert.ok(fs.existsSync(PROCESS_REPLAN_HELPER_PATH));
		assert.strictEqual(promptCatalog.defaultPromptId, 'analyze-repo');
		assert.ok(promptCatalog.prompts.length >= 8);
		for (const prompt of promptCatalog.prompts) {
			assert.ok(prompt.id);
			assert.ok(prompt.prompt);
			assert.ok(prompt.category);
			assert.ok(prompt.requiresScenario);
			assert.ok(prompt.expectedFlow.length > 0);
			assert.ok(prompt.assertions.length > 0);
			assert.ok(prompt.tags.length > 0);
		}
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'analyze-repo'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'architecture'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'develop-internet'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'pet-life-diary-static'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'progress'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'mixed-stop-work'));
		assert.strictEqual(
			scripts['test:process'],
			'node scripts/corgi-process-test.cjs --through-executor'
		);
		assert.strictEqual(
			scripts['test:process:all'],
			'node scripts/corgi-process-test.cjs --all'
		);
		assert.strictEqual(
			scripts['test:process:executor'],
			'node scripts/corgi-process-test.cjs --module executor'
		);
		assert.strictEqual(
			scripts['test:process:modules'],
			'node scripts/corgi-process-test.cjs --module all'
		);
		assert.strictEqual(
			scripts['test:process:review-replan'],
			'node scripts/corgi-process-test.cjs --module review-replan'
		);
		assert.strictEqual(
			scripts['test:process:reviewer'],
			'node scripts/corgi-process-test.cjs --module reviewer'
		);
		assert.strictEqual(
			scripts['test:process:scratch'],
			'node scripts/corgi-process-test.cjs --module scratch-static-app'
		);
		assert.strictEqual(scripts['test:prompts'], 'node scripts/corgi-test-prompt.cjs validate');
		assert.strictEqual(scripts['test:prompts:list'], 'node scripts/corgi-test-prompt.cjs list');
		assert.strictEqual(
			scripts['test:window'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:architecture'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=architecture bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:architecture:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=architecture CORGI_TEST_WINDOW_AUTO_STEPS=plan bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:architecture:e2e'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=architecture CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:feature'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=develop-internet bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:greeting'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=greeting bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:mixed'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=mixed-stop-work bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:progress'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=progress bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:question-work'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=question-work bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:executor'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=execute-permission bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:plan-ready'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=plan-ready bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:reviewer'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=reviewer-completed bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:reviewer-ready'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=reviewer-ready bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:scratch'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:scratch:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/run-corgi-test-window-auto.sh'
		);
		assert.strictEqual(
			scripts['test:window:close'],
			'bash scripts/close-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/run-corgi-test-window-auto.sh'
		);
		assert.strictEqual(
			scripts['test:window:status'],
			'node scripts/corgi-test-window-status.cjs'
		);
		assert.ok(!extensionSource.includes('CORGI_RESET_DEV_SESSION'));
		assert.ok(!developmentSessionSource.includes('CORGI_RESET_DEV_SESSION'));
		assert.ok(!extensionSource.includes('CORGI_RESET_WEBVIEW_STATE'));
		assert.ok(!developmentSessionSource.includes('CORGI_RESET_WEBVIEW_STATE'));
		assert.ok(!webviewSource.includes('CORGI_RESET_WEBVIEW_STATE'));
	});

	test('declares app-server Governor runtime as default while keeping exec selectable', () => {
		const manifest = loadPackageJson();
		const contributes = manifest.contributes as Record<string, unknown>;
		const configuration = contributes.configuration as Record<string, unknown>;
		const properties = configuration.properties as Record<string, unknown>;
		const runtimeSetting = properties['corgi.governorRuntime'] as Record<string, unknown>;
		const semanticRuntimeSetting = properties[
			'corgi.semanticSidecarRuntime'
		] as Record<string, unknown>;

		assert.strictEqual(runtimeSetting.default, 'app-server');
		assert.deepStrictEqual(runtimeSetting.enum, ['exec', 'app-server']);
		assert.strictEqual(semanticRuntimeSetting.default, 'app-server');
		assert.deepStrictEqual(semanticRuntimeSetting.enum, ['exec', 'app-server']);
	});

	test('transport gates app-server runtime behind selector and completes or falls back internally', () => {
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');

		assert.ok(transportSource.includes('CORGI_GOVERNOR_RUNTIME'));
		assert.ok(transportSource.includes('--semantic-mode'));
		assert.ok(transportSource.includes('prewarm()'));
		assert.ok(transportSource.includes('onRuntimeEvent'));
		assert.ok(transportSource.includes('model?: ExecutionWindowModel'));
		assert.ok(transportSource.includes('this.handleGovernorRuntimeResponse(result.request, result.model, elapsedMs)'));
		assert.ok(transportSource.includes('model: preparedModel'));
		assert.ok(transportSource.includes('orchestration_command_started'));
		assert.ok(transportSource.includes('orchestration_command_completed'));
		assert.ok(transportSource.includes('totalElapsedMs'));
		assert.ok(transportSource.includes('governorPromptLengthForRequest'));
		assert.ok(transportSource.includes("get<string>('governorRuntime')"));
		assert.ok(transportSource.includes("configured === 'exec' ? 'exec' : 'app-server'"));
		assert.ok(transportSource.includes("'--governor-runtime', 'external'"));
		assert.ok(transportSource.includes("'complete-governor-turn'"));
		assert.ok(transportSource.includes('const completed = await this.runRaw'));
		assert.ok(transportSource.includes('isGovernorRuntimeResponse(completed)'));
		assert.ok(transportSource.includes("'fail-governor-turn'"));
		assert.ok(transportSource.includes('isAppServerShutdownReason'));
		assert.ok(transportSource.includes('isGovernorRuntimeResponse'));
	});

	test('semantic sidecar runtime defaults to app-server while keeping exec selectable', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');
		const semanticSource = fs.readFileSync(
			path.resolve(__dirname, '../../src/semanticSidecar.ts'),
			'utf8'
		);

		assert.ok(webviewSource.includes('CORGI_SEMANTIC_SIDECAR_RUNTIME'));
		assert.ok(webviewSource.includes("get<string>('semanticSidecarRuntime')"));
		assert.ok(webviewSource.includes('runtime: semanticSidecarRuntime()'));
		assert.ok(webviewSource.includes('this.semanticSidecar.shutdown()'));
		assert.ok(semanticSource.includes("runtimeKind: 'semantic_intake'"));
		assert.ok(semanticSource.includes('ephemeralThread: true'));
		assert.ok(semanticSource.includes('previewEnabled: false'));
		assert.ok(semanticSource.includes("reasoning: 'low'"));
		assert.ok(semanticSource.includes('new CodexAppServerClient()'));
		assert.ok(semanticSource.includes('new CodexSemanticRunner()'));
		assert.ok(semanticSource.includes('corgi-semantic-appserver-'));
		assert.ok(semanticSource.includes('runtime=app-server'));
		assert.ok(semanticSource.includes('elapsedMs='));
	});

	test('Governor runtime route resolution is explicit and action-bound', () => {
		for (const command of [
				'submit-prompt',
				'answer-clarification',
				'set-permission-scope',
				'execute-plan',
				'revise-plan',
			]) {
				assert.strictEqual(resolveGovernorRoute(command, 'app-server'), 'external');
			}
			for (const command of [
				'decline-permission',
				'interrupt',
				'reconnect',
				'state',
		]) {
			assert.strictEqual(resolveGovernorRoute(command, 'app-server'), 'exec');
		}
		assert.strictEqual(resolveGovernorRoute('submit-prompt', 'exec'), 'exec');
	});

	test('development app-server runtime uses ephemeral threads for clean test launches', () => {
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');
		const clientSource = fs.readFileSync(CODEX_APP_SERVER_CLIENT_TS_PATH, 'utf8');
		const runtimeSource = fs.readFileSync(GOVERNOR_RUNTIME_TS_PATH, 'utf8');

		assert.ok(
			transportSource.includes(
				'developmentMode: extensionMode === vscode.ExtensionMode.Development'
			)
		);
		assert.ok(transportSource.includes('CORGI_APP_SERVER_EPHEMERAL'));
		assert.ok(runtimeSource.includes('ephemeralThreads'));
		assert.ok(runtimeSource.includes('this.options.ephemeralThreads'));
		assert.ok(runtimeSource.includes('isUnavailableAppServerThreadError'));
		assert.ok(clientSource.includes('ephemeral: request.ephemeralThread'));
	});

	test('app-server client keeps protocol details internal and handles fallback-relevant failures', () => {
		const clientSource = fs.readFileSync(CODEX_APP_SERVER_CLIENT_TS_PATH, 'utf8');
		const runtimeSource = fs.readFileSync(GOVERNOR_RUNTIME_TS_PATH, 'utf8');

		assert.ok(clientSource.includes("'codex'"));
		assert.ok(clientSource.includes("'app-server'"));
		assert.ok(clientSource.includes('analytics.enabled=false'));
		assert.ok(clientSource.includes('pendingRequests'));
		assert.ok(clientSource.includes('item/agentMessage/delta'));
		assert.ok(clientSource.includes('item/completed'));
		assert.ok(clientSource.includes('turn/completed'));
		assert.ok(clientSource.includes('turn/interrupt'));
		assert.ok(clientSource.includes('turn_request_sent'));
		assert.ok(clientSource.includes('draft_preview'));
		assert.ok(clientSource.includes('compactPreviewText'));
		assert.ok(clientSource.includes('text.length <= 5000'));
		assert.ok(clientSource.includes('app-server emitted malformed JSON'));
		assert.ok(runtimeSource.includes("account.kind === 'apiKey'"));
		assert.ok(runtimeSource.includes('expects ChatGPT auth'));
		assert.ok(runtimeSource.includes("previewEnabled: request.runtimeKind !== 'semantic_intake'"));
		assert.ok(runtimeSource.includes('CORGI_SEMANTIC_INTAKE_TIMEOUT_MS'));
		assert.ok(runtimeSource.includes('DEFAULT_SEMANTIC_INTAKE_TIMEOUT_MS = 60_000'));
		assert.ok(!runtimeSource.includes("? 25_000"));
	});

	test('semantic-intake runtime progress is presented as interpretation, not user-visible drafting', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');
		const clientSource = fs.readFileSync(CODEX_APP_SERVER_CLIENT_TS_PATH, 'utf8');

		assert.ok(clientSource.includes("runtimeKind?: 'dialogue' | 'plan' | 'semantic_intake'"));
		assert.ok(clientSource.includes('firstDeltaMessage'));
		assert.ok(clientSource.includes('Governor is drafting the plan'));
		assert.ok(clientSource.includes('Governor plan draft preview'));
		assert.ok(transportSource.includes('runtimeKind: event.runtimeKind'));
		assert.ok(webviewSource.includes("event.runtimeKind === 'semantic_intake'"));
		assert.ok(webviewSource.includes("event.runtimeKind === 'plan'"));
		assert.ok(webviewSource.includes('if (event.model)'));
		assert.ok(webviewSource.includes('this.model = event.model'));
		assert.ok(webviewSource.includes('Understanding request'));
		assert.ok(webviewSource.includes('Governor is drafting the plan'));
		assert.ok(webviewSource.includes('Still drafting the plan'));
		assert.ok(webviewSource.includes('runtimeTimings'));
		assert.ok(webviewSource.includes('lastRuntimeTimings'));
		assert.ok(webviewSource.includes('uiLagMs'));
		assert.ok(webviewSource.includes('Preparing Governor handoff'));
		assert.ok(webviewSource.includes('Governor request sent'));
		assert.match(
			webviewSource,
			/snapshot\.currentActor === 'governor'[\s\S]*?snapshot\.currentStage === 'semantic_intake'[\s\S]*?snapshot\.runState === 'running'/
		);
	});

	test('prompt submits omit sessionRef while state-bound actions still gate it on authoritative transport state', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('CORGI_SEMANTIC_MODE'));
		assert.ok(webviewSource.includes("semantic_mode: 'governor-first'"));
		assert.ok(webviewSource.includes('private hasAuthoritativeTransportState = false;'));
		assert.ok(webviewSource.includes('this.hasAuthoritativeTransportState = true;'));
		assert.ok(
			webviewSource.includes(
				'includeSessionRef = this.hasAuthoritativeTransportState'
			)
		);
		assert.match(
			webviewSource,
			/await this\.routeFreeText\(\s*message\.text \?\? '',\s*message\.requestId,\s*this\.hasAuthoritativeTransportState\s*\)/
		);
		assert.match(
			webviewSource,
			/session_ref:\s*action\.session_ref\s*\?\?\s*\(\s*action\.type !== 'submit_prompt' && includeSessionRef\s*\?\s*this\.model\.snapshot\.sessionRef\s*:\s*undefined\s*\)/
		);
	});

	test('permission clicks keep the foreground request key while sending a fresh command request id', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('function foregroundRequestKeyForAction(action) {'));
		assert.ok(webviewSource.includes('pendingPermissionRequest?.foregroundRequestId'));
		assert.match(
			webviewSource,
			/const requestId = nextForegroundRequestKey\(\);\s*const requestKey = foregroundRequestKeyForAction\(action\);\s*ensureForegroundRequest\('', '', requestKey\);/
		);
	});

	test('governor replies do not render debug details in the transcript', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(
			webviewSource.includes(
				"if (item.type === 'actor_event' && item.source_actor === 'governor') {"
			)
		);
		assert.ok(webviewSource.includes("return '';"));
	});

	test('transient progress stack hides after a governor reply and only keeps three visible rows', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('function latestGovernorReplyForRequest(requestKey) {'));
		assert.ok(webviewSource.includes('if (latestGovernorReplyForRequest(requestKey)) {'));
		assert.ok(webviewSource.includes("return '';"));
		assert.ok(webviewSource.includes('const visibleBullets = bullets.slice(-3);'));
		assert.ok(webviewSource.includes('function trimForegroundBullets()'));
		assert.ok(webviewSource.includes('function foregroundRequestCanReceiveTrace(requestKey)'));
		assert.ok(webviewSource.includes('function applyRuntimeProgress(event)'));
		assert.ok(webviewSource.includes('function reconcileLocalUiWithModel()'));
		assert.ok(webviewSource.includes('function foregroundRequestHasAuthoritativeSurface(requestKey)'));
		assert.ok(webviewSource.includes('function clearForegroundRequest()'));
		assert.ok(webviewSource.includes('reconcileLocalUiWithModel();'));
		assert.ok(webviewSource.includes('function setDraftPreviewTarget(value)'));
		assert.ok(webviewSource.includes('function scheduleDraftPreviewTyping()'));
		assert.ok(webviewSource.includes('function scheduleGovernorWaitHeartbeat(event)'));
		assert.ok(webviewSource.includes('Still waiting for the Governor'));
		assert.ok(webviewSource.includes('Governor is taking a deeper pass'));
		assert.ok(webviewSource.includes('nextDraftPreviewSlice(current, target)'));
		assert.ok(webviewSource.includes("scheduleWebviewSnapshot('draft_preview_type')"));
		assert.ok(webviewSource.includes("scheduleWebviewSnapshot('governor_wait_heartbeat')"));
		assert.ok(webviewSource.includes('draft-preview'));
		assert.ok(webviewSource.includes('Governor draft'));
		assert.ok(
			!/function ensureForegroundRequest[\s\S]*?\(state \|\| ''\)[\s\S]*?\n\t\tfunction latestForegroundUserTextFromModel/.test(
				webviewSource
			)
		);
		assert.ok(webviewSource.includes('snapshot.pendingPermissionRequest'));
		assert.ok(webviewSource.includes('model.activeClarification'));
		assert.ok(webviewSource.includes('activity-trace'));
		assert.ok(webviewSource.includes('Still working behind the scenes'));
		assert.ok(webviewSource.includes('background: transparent;'));
	});

	test('governor runtime config uses gpt-5.5 with xhigh reasoning', () => {
		const configSource = fs.readFileSync(GOVERNOR_RUNTIME_CONFIG_PATH, 'utf8');
		const sessionSource = fs.readFileSync(
			path.resolve(__dirname, '../../orchestration/harness/session.py'),
			'utf8'
		);

		assert.ok(configSource.includes('model = "gpt-5.5"'));
		assert.ok(configSource.includes('model_reasoning_effort = "xhigh"'));
		assert.ok(sessionSource.includes('model = "gpt-5.5"'));
		assert.ok(sessionSource.includes('reasoning = "xhigh"'));
	});

	test('registers advisory MCP server through repo entrypoint with Python env handling', () => {
		const configSource = fs.readFileSync(GOVERNOR_RUNTIME_CONFIG_PATH, 'utf8');
		const entrypointSource = fs.readFileSync(MCP_SERVER_ENTRYPOINT_PATH, 'utf8');
		const devEntrypointSource = fs.readFileSync(DEV_MCP_SERVER_ENTRYPOINT_PATH, 'utf8');
		const launcherSource = fs.readFileSync(ADVISORY_MCP_LAUNCHER_PATH, 'utf8');
		const devLauncherSource = fs.readFileSync(DEVELOPMENT_CONSULTING_MCP_LAUNCHER_PATH, 'utf8');
		const setupSource = fs.readFileSync(ADVISORY_MCP_SETUP_PATH, 'utf8');
		const requirementsSource = fs.readFileSync(ADVISORY_MCP_REQUIREMENTS_PATH, 'utf8');

		assert.ok(configSource.includes('[mcp_servers.orchestration_advisory]'));
		assert.ok(configSource.includes('command = "python3"'));
		assert.ok(configSource.includes('args = ["mcp_server.py"]'));
		assert.ok(!configSource.includes('args = ["orchestration/runtime/advisory/mcp_server.py"]'));
		assert.ok(!configSource.includes('dev_mcp_server.py'));
		assert.ok(entrypointSource.includes('serve_advisory_mcp.py'));
		assert.ok(entrypointSource.includes('os.environ["CORGI_ADVISORY_CONTEXT"] = "corgi-governor-runtime"'));
		assert.ok(devEntrypointSource.includes('serve_development_consulting_mcp.py'));
		assert.ok(devLauncherSource.includes('CORGI_ADVISORY_LAUNCH_PROFILE'));
		assert.ok(devLauncherSource.includes('corgi-development-consulting'));
		assert.ok(devLauncherSource.includes('CORGI_ADVISORY_CALLER_ROLE'));
		assert.ok(devLauncherSource.includes('.agent" / "development" / "advisory'));
		assert.ok(launcherSource.includes('ORCHESTRATION_APPROVED_PYTHON'));
		assert.ok(launcherSource.includes('CORGI_ADVISORY_MCP_PYTHON'));
		assert.ok(launcherSource.includes('CORGI_PYTHON'));
		assert.ok(launcherSource.includes('/opt/homebrew/bin/python3'));
		assert.ok(launcherSource.includes('ORCHESTRATION_REPO_ROOT'));
		assert.ok(launcherSource.includes('ORCHESTRATION_SOURCE_ROOT'));
		assert.ok(launcherSource.includes('CORGI_ADVISORY_CONTEXT'));
		assert.ok(launcherSource.includes('corgi-governor-runtime'));
		assert.ok(launcherSource.includes('CORGI_ADVISORY_STATE_DIR'));
		assert.ok(launcherSource.includes('PYTHONPATH'));
		assert.ok(launcherSource.includes('requirements.txt'));
		assert.ok(launcherSource.includes('"runtime" / "advisory" / "mcp_server.py"'));
		assert.ok(setupSource.includes('/opt/homebrew/bin/python3'));
		assert.ok(setupSource.includes('.venv'));
		assert.ok(setupSource.includes('requirements.txt'));
		assert.ok(requirementsSource.includes('anthropic'));
		assert.ok(requirementsSource.includes('mcp'));
	});

	test('separates runtime Governor advisory from development consulting', () => {
		const serverSource = fs.readFileSync(ADVISORY_MCP_SERVER_PATH, 'utf8');
		const advisoryDoc = fs.readFileSync(ADVISORY_DOC_PATH, 'utf8');

		assert.ok(serverSource.includes('CORGI_RUNTIME_CONTEXT'));
		assert.ok(serverSource.includes('corgi-governor-runtime'));
		assert.ok(serverSource.includes('corgi-development-consulting'));
		assert.ok(serverSource.includes('Corgi_Governor_Advisor'));
		assert.ok(serverSource.includes('Corgi_Development_Consulting'));
		assert.ok(serverSource.includes('_authorize_tool_call'));
		assert.ok(serverSource.includes('ADVISORY_CALLER_ROLE != "governor"'));
		assert.ok(serverSource.includes('_runtime_prompt_boundary_error'));
		assert.ok(serverSource.includes('_resolve_context_path'));
		assert.ok(advisoryDoc.includes('Runtime advisor file access is target-workspace scoped'));
		assert.ok(advisoryDoc.includes('for building Corgi itself'));
	});

	test('documents runtime ergonomics as presentation-only and advisor capabilities as descriptive', () => {
		const uxContract = fs.readFileSync(UX_CONTRACT_PATH, 'utf8');
		const advisoryDoc = fs.readFileSync(ADVISORY_DOC_PATH, 'utf8');
		const kernelSource = fs.readFileSync(RUNTIME_ERGONOMICS_KERNEL_TS_PATH, 'utf8');
		const capabilities = JSON.parse(
			fs.readFileSync(ADVISORY_CAPABILITIES_PATH, 'utf8')
		) as { capabilities: Array<{ provider: string; roleAccess: string[] }> };

		assert.ok(uxContract.includes('## Runtime Ergonomics Kernel'));
		assert.ok(uxContract.includes('presentation-only'));
		assert.ok(uxContract.includes('must not create workflow truth'));
		assert.ok(uxContract.includes('`activity` is for short operational rows'));
		assert.ok(uxContract.includes('`internal` is for request ids, session refs, context refs'));
		assert.ok(advisoryDoc.includes('## Runtime Capability Registry'));
		assert.ok(advisoryDoc.includes('orchestration/runtime/advisory/capabilities.json'));
		assert.ok(advisoryDoc.includes('| MiniMax | `consult_minimax` | Governor only | none |'));
		assert.ok(advisoryDoc.includes('| Claude Headless | `consult_claude_headless` | Governor only | read-only target workspace |'));
		assert.ok(advisoryDoc.includes('descriptive only'));
		assert.ok(kernelSource.includes('RuntimeActivityVisibility'));
		assert.ok(kernelSource.includes('activityFeedItemIds'));
		assert.ok(kernelSource.includes('governor_decision_recorded'));
		assert.deepStrictEqual(
			capabilities.capabilities.map((capability) => capability.provider),
			['consult_minimax', 'consult_claude_headless', 'consult_architect']
		);
		assert.ok(
			capabilities.capabilities.every((capability) =>
				capability.roleAccess.includes('governor')
			)
		);
	});

	test('permission continuation collapses progress into a specific wait state', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('function setForegroundSingleBullet(label, state, hint) {'));
		assert.ok(webviewSource.includes('Waiting for a reply from the Governor...'));
		assert.ok(webviewSource.includes("scope === 'execute'"));
		assert.ok(webviewSource.includes('Starting execution...'));
		assert.ok(!webviewSource.includes('Applying your permission choice...'));
		assert.ok(
			!webviewSource.includes(
				"appendForegroundBullet('Continuing request', 'active', 'Applying your permission choice...')"
			)
		);
	});

	test('permission action surface stays hidden until authoritative state changes', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('ui.pendingPermissionContextRef ='));
		assert.ok(webviewSource.includes('pendingPermissionHiddenAt'));
		assert.ok(webviewSource.includes('function retainOptimisticHidesUntilAuthoritativeChange()'));
		assert.ok(!webviewSource.includes('const maxHideMs'));
		assert.ok(webviewSource.includes('const composerActions = document.getElementById'));
		assert.ok(webviewSource.includes("actions: collectTextRows(composerActions, 'button')"));
		assert.ok(
			webviewSource.includes(
				'buttons.push(\'<button type="button" class="secondary" data-action="refresh_state">Refresh state</button>\');'
			)
		);
		assert.ok(!webviewSource.includes('Permission choice sent. Waiting for a reply from the Governor...'));
		assert.ok(webviewSource.includes('data-action="refresh_state"'));
		assert.ok(webviewSource.includes('authoritativePermissionContextRef() !== ui.pendingPermissionContextRef'));
		assert.ok(webviewSource.includes('authoritativePlanContextRef() !== ui.pendingPlanContextRef'));
		assert.ok(webviewSource.includes('function clearOptimisticActionHides()'));
		assert.ok(webviewSource.includes('if (latestRequestError(requestKey))'));
		assert.ok(webviewSource.includes('clearOptimisticActionHides();'));
		assert.ok(!webviewSource.includes('pendingPermissionRequest?.contextRef !=='));
	});

	test('plan-ready checkpoint exposes execute and revision actions', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('function isPlanReady(snapshot) {'));
		assert.ok(webviewSource.includes('Plan ready'));
		assert.ok(webviewSource.includes('data-action="execute_plan"'));
		assert.ok(webviewSource.includes('data-action="revise_plan"'));
		assert.ok(webviewSource.includes('pendingPermissionContextRef'));
		assert.ok(webviewSource.includes('planRevisionMode'));
		assert.ok(webviewSource.includes("type: 'execute_plan'"));
		assert.ok(webviewSource.includes("type: 'revise_plan'"));
		assert.ok(webviewSource.includes("runtimeActionLabel('execute_plan', 'Execute plan')"));
		assert.ok(webviewSource.includes("runtimeActionLabel('revise_plan', 'Revise')"));
		assert.ok(webviewSource.includes('Send to Governor'));
	});

	test('presentation mapping keeps non-governor copy controller-owned', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('function displayCopy(item) {'));
		assert.ok(webviewSource.includes("case 'permission.needed':"));
		assert.ok(webviewSource.includes("case 'error.semantic_route_required':"));
		assert.ok(webviewSource.includes("case 'error.stale_context':"));
		assert.ok(
			webviewSource.includes(
				"if (item.type === 'actor_event' && item.source_actor === 'governor') {"
			)
		);
		assert.ok(webviewSource.includes('const copy = displayCopy(item);'));
		assert.ok(webviewSource.includes('renderStructuredAssistantBody(body)'));
		assert.ok(webviewSource.includes("item.title === 'Executor completed'"));
		assert.ok(webviewSource.includes('function renderCompactResultMessage(item, copy, renderedBody)'));
		assert.ok(webviewSource.includes('message assistant result-summary'));
		assert.ok(webviewSource.includes('Reviewer checked the result'));
		assert.ok(webviewSource.includes('escapeHtml(body)'));

		const permissionModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'what happened?',
			semantic_route_type: 'governor_dialogue',
			request_id: 'req-dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});
		const permissionItem = permissionModel.feed.find(
			(item) => item.type === 'permission_request'
		);
		assert.strictEqual(permissionItem?.presentation_key, 'permission.needed');
		assert.strictEqual(permissionItem?.presentation_args?.scope, 'observe');

		const clarificationModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'analyze the repo',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const failedClarificationModel = applyModelAction(clarificationModel, {
			type: 'answer_clarification',
			text: 'architecture',
			context_ref: 'stale-context',
			request_id: 'req-stale',
			now: '2026-04-10T10:00:10.000Z',
		});
		const errorItem = failedClarificationModel.feed[failedClarificationModel.feed.length - 1];
		assert.strictEqual(errorItem.type, 'error');
		assert.strictEqual(errorItem.presentation_key, 'error.stale_context');
		assert.strictEqual(errorItem.presentation_args?.kind, 'clarification');
	});

	test('webview snapshot renders the goal strip and compact post-execution summaries', () => {
		const reviewArtifact = {
			id: 'review-report',
			label: 'Reviewer report',
			path: '.agent/reviews/review.md',
			status: 'ready',
			summary: 'Reviewer report artifact',
			authoritative: true,
		};
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			activeForegroundRequestId: 'corgi-request:test:execute',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'reviewer',
				currentStage: 'reviewer_completed',
				permissionScope: 'execute',
				runState: 'idle',
				recentArtifacts: [reviewArtifact],
			},
			feed: [
				{
					id: 'user-message',
					type: 'user_message',
					title: 'Prompt submitted',
					body: 'analyze the repo',
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: false,
				},
				{
					id: 'governor-plan',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: analyze the repository architecture.\n\nReadiness: plan-ready.',
					timestamp: '2026-04-10T10:00:05.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
				{
					id: 'execute-plan-action',
					type: 'user_message',
					title: 'Permission selected',
					body: 'Execute plan',
					timestamp: '2026-04-10T10:00:10.000Z',
					authoritative: false,
					turn_type: 'permission_action',
					in_response_to_request_id: 'corgi-request:test:execute',
				},
				{
					id: 'executor-completed',
					type: 'system_status',
					title: 'Executor completed',
					body: 'Executor wrote details at .agent/executor/result.md.',
					timestamp: '2026-04-10T10:00:20.000Z',
					authoritative: true,
					source_artifact_ref: reviewArtifact.path,
					in_response_to_request_id: 'corgi-request:test:execute',
				},
				{
					id: 'reviewer-completed',
					type: 'system_status',
					title: 'Reviewer completed',
					body: 'Reviewer completed the read-only check at .agent/reviews/review.md.',
					timestamp: '2026-04-10T10:00:30.000Z',
					authoritative: true,
					source_artifact_ref: reviewArtifact.path,
					in_response_to_request_id: 'corgi-request:test:execute',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const messageText = snapshot.messages.map((message) => message.text).join('\n');
		const activityText = snapshot.activity.map((message) => message.text).join('\n');
		const transcriptText = snapshot.transcript.map((message) => message.text).join('\n');

		assert.match(snapshot.goalStrip, /Goal: Analyze the repository architecture\./);
		assert.match(snapshot.goalStrip, /Step: Reviewer checked the result/);
		assert.match(snapshot.goalStrip, /Done/);
		assert.strictEqual(snapshot.composer.context, 'Scope: Execute');
		assert.match(activityText, /Executor finished the task/);
		assert.match(messageText, /Reviewer checked the result/);
		assert.match(transcriptText, /Objective: analyze the repository architecture/);
		assert.match(messageText, /View source/);
		assert.ok(!messageText.includes('Execute plan'));
		assert.ok(!messageText.includes('reviewer_completed'));
		assert.ok(!snapshot.composer.context.includes('Reviewer'));
		assert.deepStrictEqual(snapshot.progress, []);
	});

	test('runtime ergonomics kernel separates transcript, activity, detail, and internal surfaces', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeForegroundRequestId: 'req-kernel',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'reviewer',
				currentStage: 'reviewer_completed',
				currentWorkRef: 'lane/main/work-123',
				currentAttemptNumber: 2,
			},
			feed: [
				{
					id: 'governor',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: analyze the repo.',
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
				{
					id: 'executor',
					type: 'system_status',
					title: 'Executor completed',
					body: 'Executor wrote .agent/dispatches/lane/main/dispatch-1/result.json.',
					timestamp: '2026-04-10T10:00:10.000Z',
					authoritative: true,
					source_artifact_ref: '.agent/dispatches/lane/main/dispatch-1/result.json',
				},
				{
					id: 'artifact',
					type: 'artifact_reference',
					title: 'Result artifact',
					timestamp: '2026-04-10T10:00:11.000Z',
					authoritative: true,
					artifact: {
						id: 'artifact',
						label: 'result.json',
						path: '.agent/dispatches/lane/main/dispatch-1/result.json',
						authoritative: true,
					},
				},
				{
					id: 'permission-action',
					type: 'user_message',
					title: 'Permission selected',
					body: 'Execute plan',
					timestamp: '2026-04-10T10:00:12.000Z',
					authoritative: false,
					turn_type: 'permission_action',
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);
		const activityText = kernel.activities.map((activity) => activity.summary).join('\n');

		assert.deepStrictEqual(kernel.transcriptFeedItemIds, ['governor']);
		assert.deepStrictEqual(kernel.activityFeedItemIds, ['executor']);
		assert.deepStrictEqual(kernel.detailFeedItemIds, ['artifact']);
		assert.deepStrictEqual(kernel.internalFeedItemIds, ['permission-action']);
		assert.match(activityText, /Executor finished the task/);
		assert.ok(!activityText.includes('dispatch-1'));
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[0]), 'transcript');
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[1]), 'activity');
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[2]), 'detail');
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[3]), 'internal');
	});

	test('runtime ergonomics kernel hides stale blocking surfaces from transcript indexes', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeClarification: undefined,
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				pendingPermissionRequest: undefined,
			},
			feed: [
				{
					id: 'stale-permission',
					type: 'permission_request',
					title: 'Permission needed',
					body: 'Choose plan if you want Corgi to continue.',
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: true,
				},
				{
					id: 'stale-clarification',
					type: 'clarification_request',
					title: 'Clarification required',
					body: 'What should Corgi focus on?',
					timestamp: '2026-04-10T10:00:01.000Z',
					authoritative: true,
				},
				{
					id: 'ready',
					type: 'system_status',
					title: 'Ready when you are',
					body: 'Ask Corgi to work on this repo.',
					timestamp: '2026-04-10T10:00:02.000Z',
					authoritative: true,
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);

		assert.deepStrictEqual(kernel.transcriptFeedItemIds, []);
		assert.deepStrictEqual(kernel.internalFeedItemIds, [
			'stale-permission',
			'stale-clarification',
			'ready',
		]);
	});

	test('runtime ergonomics kernel matches active blocking surfaces by context ref', () => {
		const body = 'Choose plan if you want Corgi to continue this request.';
		const clarificationBody = 'What should Corgi focus on?';
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeClarification: {
				id: 'clarification-new',
				contextRef: 'clarification-new',
				title: 'Clarification required',
				body: clarificationBody,
				allowFreeText: true,
				requestedAt: '2026-04-10T10:00:04.000Z',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				pendingPermissionRequest: {
					id: 'permission-new',
					contextRef: 'permission-new',
					title: 'Permission needed',
					body,
					requestedAt: '2026-04-10T10:00:03.000Z',
					recommendedScope: 'plan',
					allowedScopes: ['plan', 'execute'],
				},
			},
			feed: [
				{
					id: 'permission-old',
					type: 'permission_request',
					title: 'Permission needed',
					body,
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'permission-old', scope: 'plan' },
				},
				{
					id: 'permission-new',
					type: 'permission_request',
					title: 'Permission needed',
					body,
					timestamp: '2026-04-10T10:00:03.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'permission-new', scope: 'plan' },
				},
				{
					id: 'clarification-old',
					type: 'clarification_request',
					title: 'Clarification required',
					body: clarificationBody,
					timestamp: '2026-04-10T10:00:01.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'clarification-old' },
				},
				{
					id: 'clarification-new',
					type: 'clarification_request',
					title: 'Clarification required',
					body: clarificationBody,
					timestamp: '2026-04-10T10:00:04.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'clarification-new' },
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);

		assert.deepStrictEqual(kernel.transcriptFeedItemIds, [
			'permission-new',
			'clarification-new',
		]);
		assert.deepStrictEqual(kernel.internalFeedItemIds, [
			'permission-old',
			'clarification-old',
		]);
	});

	test('runtime ergonomics kernel collapses repeated activity and names safe parallel work', () => {
		const base = createInitialModel('2026-04-10T10:00:00.000Z');
		const model: ExecutionWindowModel = {
			...base,
			activeForegroundRequestId: 'req-parallel',
			snapshot: {
				...base.snapshot,
				task: 'Build the static pet diary app.',
				currentActor: 'executor',
				currentStage: 'plan_executing',
				runState: 'running',
				currentWorkRef: 'work-pet-diary',
				currentAttemptNumber: 1,
				activeParallelDispatchCount: 2,
			},
			feed: [
				{
					id: 'executor-starting-1',
					type: 'system_status',
					title: 'Executor starting',
					body: 'Executor is starting.',
					timestamp: '2026-04-10T10:00:10.000Z',
					authoritative: true,
					in_response_to_request_id: 'req-parallel',
				},
				{
					id: 'executor-starting-2',
					type: 'system_status',
					title: 'Executor starting',
					body: 'Executor is still starting.',
					timestamp: '2026-04-10T10:00:11.000Z',
					authoritative: true,
					in_response_to_request_id: 'req-parallel',
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);
		const executorRunningEvents = kernel.activities.filter(
			(activity) => activity.summaryKey === 'executor_running'
		);

		assert.strictEqual(executorRunningEvents.length, 1);
		assert.deepStrictEqual(kernel.activityFeedItemIds, ['executor-starting-2']);
		assert.ok(kernel.internalFeedItemIds.includes('executor-starting-1'));
		assert.strictEqual(
			summaryForActivity('parallel_running', { count: 2 }),
			'2 executor tasks running'
		);
		assert.match(
			kernel.activities.map((activity) => activity.summary).join('\n'),
			/2 executor tasks running/
		);
	});

	test('webview snapshot keeps plan-ready actions compact and action-bound', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			planReadyRequest: {
				id: 'plan-ready',
				contextRef: 'plan-context-1',
				title: 'Plan ready',
				body: 'The plan is ready.',
				requestedAt: '2026-04-10T10:00:20.000Z',
				foregroundRequestId: 'req-plan',
				acceptedIntakeSummary: {
					title: 'Analyze repo',
					body: 'Analyze the repository architecture.',
				},
				allowedActions: ['execute_plan', 'revise_plan'],
				planVersion: 1,
				planContextRef: 'plan-context-1',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'governor',
				currentStage: 'plan_ready',
				permissionScope: 'plan',
				runState: 'idle',
			},
			feed: [
				{
					id: 'governor-plan',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: analyze the repository architecture.\n\nExecution readiness: plan-ready only.',
					timestamp: '2026-04-10T10:00:20.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const kernel = buildRuntimeErgonomicsKernel(model);
		const actionText = snapshot.actions.map((action) => action.text);
		const executeAction = snapshot.actions.find((action) => action.text === 'Execute plan');
		const reviseAction = snapshot.actions.find((action) => action.text === 'Revise');

		assert.match(snapshot.goalStrip, /Step: Plan ready/);
		assert.deepStrictEqual(actionText, ['Execute plan', 'Revise']);
		assert.strictEqual(kernel.primaryAction?.label, 'Execute plan');
		assert.deepStrictEqual(
			kernel.secondaryActions.map((action) => action.label),
			['Revise']
		);
		assert.ok(executeAction);
		assert.ok(!executeAction.className.includes('secondary'));
		assert.ok(reviseAction?.className.includes('secondary'));
		assert.strictEqual(snapshot.composer.context, 'Scope: Plan');
		assert.ok(!snapshot.composer.context.includes('Plan ready'));
	});

	test('webview snapshot keeps retry plan-ready state on the same goal and attempt', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			planReadyRequest: {
				id: 'plan-ready-retry',
				contextRef: 'plan-context-2',
				title: 'Plan ready',
				body: 'The revised plan is ready.',
				requestedAt: '2026-04-10T10:01:00.000Z',
				foregroundRequestId: 'req-retry',
				acceptedIntakeSummary: {
					title: 'Analyze repo',
					body: 'Analyze the repository architecture.',
				},
				allowedActions: ['execute_plan', 'revise_plan'],
				planVersion: 2,
				planContextRef: 'plan-context-2',
				workRef: 'lane/main/work-123',
				planRef: '.agent/work/lane/main/work-123/plans/plan-v2.md',
				revisionReason: 'review_requested_changes',
				latestReviewRef: '.agent/reviews/lane/main/dispatch-1/review.json',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'governor',
				currentStage: 'plan_ready',
				permissionScope: 'plan',
				runState: 'idle',
				currentWorkRef: 'lane/main/work-123',
				currentPlanVersion: 2,
				currentAttemptNumber: 1,
				latestReviewRef: '.agent/reviews/lane/main/dispatch-1/review.json',
				latestReviewVerdict: 'request_changes',
			},
			feed: [
				{
					id: 'governor-revised-plan',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: revise the same repository analysis plan.\n\nExecution readiness: retry plan-ready.',
					timestamp: '2026-04-10T10:01:00.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const actionText = snapshot.actions.map((action) => action.text);
		const visibleText = [
			snapshot.goalStrip,
			snapshot.composer.context,
			...snapshot.messages.map((message) => message.text),
			...actionText,
		].join('\n');

		assert.match(snapshot.goalStrip, /Goal: Analyze the repository architecture\./);
		assert.match(snapshot.goalStrip, /Step: Plan ready · Attempt 2/);
		assert.deepStrictEqual(actionText, ['Execute plan', 'Revise']);
		assert.strictEqual(snapshot.composer.context, 'Scope: Plan');
		assert.ok(!visibleText.includes('lane/main/work-123'));
		assert.ok(!visibleText.includes('plan-context-2'));
		assert.ok(!visibleText.includes('review_requested_changes'));
		assert.ok(!visibleText.includes('dispatch-1/review.json'));
	});

	test('webview snapshot shows compact parallel goal status without exposing refs', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Build app',
				body: 'Build the static pet diary app.',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Build the static pet diary app.',
				currentActor: 'executor',
				currentStage: 'plan_executing',
				permissionScope: 'execute',
				runState: 'running',
				activeParallelDispatchCount: 2,
				currentParallelSetRef: 'lane/work/parallel-set-1',
			},
			feed: [],
		};

		const snapshot = renderWebviewSnapshot(model);

		assert.match(snapshot.goalStrip, /Step: 2 executor tasks running/);
		assert.ok(!snapshot.goalStrip.includes('parallel-set-1'));
	});

	test('webview snapshot condenses dispatch queued into the goal strip instead of transcript noise', () => {
		const requestArtifact = {
			id: 'dispatch-request',
			label: 'Dispatch request',
			path: '.agent/dispatches/lane/main/dispatch-123/request.json',
			status: 'ready',
			summary: 'Dispatch request artifact',
			authoritative: true,
		};
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			activeForegroundRequestId: 'corgi-request:test:execute',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'orchestration',
				currentStage: 'dispatch_queued',
				permissionScope: 'execute',
				runState: 'queued',
				recentArtifacts: [requestArtifact],
			},
			feed: [
				{
					id: 'execute-plan-action',
					type: 'user_message',
					title: 'Permission selected',
					body: 'Execute plan',
					timestamp: '2026-04-10T10:00:25.000Z',
					authoritative: false,
					turn_type: 'permission_action',
					in_response_to_request_id: 'corgi-request:test:execute',
				},
				{
					id: 'dispatch-queued',
					type: 'system_status',
					title: 'Dispatch queued',
					body: 'Dispatch truth was created.',
					timestamp: '2026-04-10T10:00:30.000Z',
					authoritative: true,
					source_artifact_ref: requestArtifact.path,
					in_response_to_request_id: 'corgi-request:test:execute',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const messageText = snapshot.messages.map((message) => message.text).join('\n');

		assert.match(snapshot.goalStrip, /Step: Executor is ready/);
		assert.match(snapshot.goalStrip, /Executor ready/);
		assert.ok(!messageText.includes('Dispatch queued'));
		assert.ok(!messageText.includes('Dispatch truth was created'));
		assert.ok(!messageText.includes('Execute plan'));
		assert.deepStrictEqual(snapshot.actions.map((action) => action.text), ['View source']);
		assert.deepStrictEqual(snapshot.progress, []);
		assert.strictEqual(snapshot.composer.context, 'Scope: Execute');
	});

	test('webview snapshot shows plan execution as active goal state', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			activeForegroundRequestId: 'corgi-request:test:execute',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'orchestration',
				currentStage: 'plan_executing',
				permissionScope: 'execute',
				runState: 'running',
				recentArtifacts: [],
			},
			feed: [
				{
					id: 'executor-starting',
					type: 'system_status',
					title: 'Executor starting',
					body: 'Executor is starting from the accepted plan.',
					timestamp: '2026-04-10T10:00:30.000Z',
					authoritative: true,
					in_response_to_request_id: 'corgi-request:test:execute',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const messageText = snapshot.messages.map((message) => message.text).join('\n');

		assert.match(snapshot.goalStrip, /Step: Executor running/);
		assert.match(snapshot.goalStrip, /Running/);
		assert.ok(!messageText.includes('Executor starting'));
		assert.strictEqual(snapshot.composer.context, 'Scope: Execute');
	});

	test('transport selection resolves the real orchestration workspace when available', () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Development,
			vscode.Uri.file(path.resolve(__dirname, '../..')),
			vscode.Uri.file('/tmp/not-used-because-workspace-wins')
		);

		assert.strictEqual(target.kind, 'orchestration');
		if (target.kind === 'orchestration') {
			assert.ok(target.scriptPath.endsWith('orchestration/scripts/orchestrate.py'));
			assert.strictEqual(target.source, 'workspace');
		}
	});

	test('transport prefers configured or Homebrew Python before system python', () => {
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');
		const testRunnerSource = fs.readFileSync(
			path.resolve(__dirname, '../../scripts/run-orchestration-tests.cjs'),
			'utf8'
		);

		for (const source of [transportSource, testRunnerSource]) {
			assert.ok(source.includes('CORGI_PYTHON'));
			assert.ok(source.includes('/opt/homebrew/bin/python3'));
			assert.ok(source.includes('/usr/local/bin/python3'));
		}
		assert.ok(transportSource.includes('this.pythonExecutable'));
		assert.ok(transportSource.includes('ORCHESTRATION_APPROVED_PYTHON'));
		assert.ok(transportSource.includes('--auto-consume-executor'));
		assert.match(
			transportSource,
			/action\?\.type === 'execute_plan'[\s\S]{0,120}args\.push\('--auto-consume-executor'\)/
		);
	});

	test('transport selection falls back to the development extension repo when no workspace is open', async () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Development,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		assert.strictEqual(target.kind, 'orchestration');
		if (target.kind === 'orchestration') {
			assert.strictEqual(target.source, 'extension_dev');
		}

		const transport = createExecutionTransport(
			vscode.ExtensionMode.Development,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		await assert.doesNotReject(() => transport.load());
	});

	test('development transport can run source orchestration against a scratch workspace', async () => {
		const scratchWorkspace = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-scratch-workspace-'));
		try {
			const target = resolveExecutionTransportTarget(
				vscode.ExtensionMode.Development,
				vscode.Uri.file(scratchWorkspace),
				vscode.Uri.file(path.resolve(__dirname, '../..'))
			);
			assert.strictEqual(target.kind, 'orchestration');
			if (target.kind === 'orchestration') {
				assert.strictEqual(target.source, 'extension_dev');
				assert.strictEqual(target.cwd, scratchWorkspace);
				assert.strictEqual(target.sourceRoot, path.resolve(__dirname, '../..'));
				assert.ok(target.scriptPath.endsWith('orchestration/scripts/orchestrate.py'));
			}
		} finally {
			fs.rmSync(scratchWorkspace, { recursive: true, force: true });
		}
	});

	test('transport selection fails closed in production when no workspace is open', async () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Production,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		assert.strictEqual(target.kind, 'unavailable');
		if (target.kind === 'unavailable') {
			assert.strictEqual(target.title, 'Real orchestration workspace required');
		}

		const transport = createExecutionTransport(
			vscode.ExtensionMode.Production,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		await assert.rejects(
			() => transport.load(),
			(error: unknown) =>
				error instanceof TransportUnavailableError &&
				error.title === 'Real orchestration workspace required'
		);
	});

	test('transport selection fails closed in production when workspace lacks orchestration support', () => {
		const scratchWorkspace = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-prod-workspace-'));
		try {
			const target = resolveExecutionTransportTarget(
				vscode.ExtensionMode.Production,
				vscode.Uri.file(scratchWorkspace),
				vscode.Uri.file(path.resolve(__dirname, '../..'))
			);
			assert.strictEqual(target.kind, 'unavailable');
			if (target.kind === 'unavailable') {
				assert.strictEqual(target.title, 'Orchestration CLI not found');
			}
		} finally {
			fs.rmSync(scratchWorkspace, { recursive: true, force: true });
		}
	});

	test('transport selection fails closed when neither workspace nor development repo contains orchestrate', async () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Development,
			undefined,
			vscode.Uri.file('/tmp/corgi-missing-root')
		);
		assert.strictEqual(target.kind, 'unavailable');
		if (target.kind === 'unavailable') {
			assert.strictEqual(target.title, 'Real orchestration workspace required');
		}
	});

	test('semantic sidecar defaults to gpt-5.4-mini', () => {
		assert.strictEqual(DEFAULT_SEMANTIC_SIDECAR_MODEL, 'gpt-5.4-mini');
	});

	test('semantic routing maps stop intent only when a run is active', () => {
		const runningModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'What is happening?',
			semantic_route_type: 'governor_dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});
		const activeRunModel = {
			...runningModel,
			snapshot: {
				...runningModel.snapshot,
				runState: 'running' as const,
			},
		};
		const resolution = resolveSemanticRouting(
			activeRunModel,
			'stop',
			semanticDecision({
				route_type: 'explicit_action',
				action_name: 'interrupt_run',
				normalized_text: 'stop',
				paraphrase: 'Stop the current run.',
			}),
			undefined,
			'semantic-summary:test',
			{
				...semanticContextFlags(),
				had_pending_interrupt: false,
			}
		);

		assert.strictEqual(resolution.kind, 'dispatch');
		if (resolution.kind === 'dispatch') {
			assert.strictEqual(resolution.action.type, 'interrupt_run');
			assert.strictEqual(resolution.action.text, 'stop');
			assert.strictEqual(resolution.action.semantic_route_type, 'explicit_action');
		}
	});

	test('semantic routing blocks clarification replies when no clarification is active', () => {
		const resolution = resolveSemanticRouting(
			createInitialModel('2026-04-10T10:00:00.000Z'),
			'architecture',
			semanticDecision({
				route_type: 'clarification_reply',
				normalized_text: 'architecture',
				paraphrase: 'Answer the current clarification with architecture.',
			}),
			undefined,
			'semantic-summary:test',
			semanticContextFlags()
		);

		assert.strictEqual(resolution.kind, 'block');
		if (resolution.kind === 'block') {
			assert.strictEqual(resolution.blockKind, 'no_active_clarification');
		}
	});

	test('semantic routing exhausts the clarification budget conservatively', () => {
		const resolution = resolveSemanticRouting(
			createInitialModel('2026-04-10T10:00:00.000Z'),
			'do whatever is best',
			semanticDecision({
				route_type: 'block',
				action_name: 'none',
				normalized_text: 'do whatever is best',
				paraphrase: '',
				confidence: 'low',
				reason: 'mixed_or_ambiguous',
			}),
			{
				attempts: 2,
				exhausted: false,
				lastQuestion: 'Please restate this more directly.',
			},
			'semantic-summary:test',
			semanticContextFlags()
		);

		assert.strictEqual(resolution.kind, 'block');
		if (resolution.kind === 'block') {
			assert.strictEqual(resolution.nextLoopState.exhausted, true);
			assert.strictEqual(resolution.blockKind, 'needs_disambiguation');
		}
	});

	test('semantic routing fixtures resolve deterministically without live model calls', () => {
		const fixtures = JSON.parse(
			fs.readFileSync(SEMANTIC_ROUTING_FIXTURE_PATH, 'utf8')
		) as SemanticRoutingFixture[];

		assert.ok(fixtures.length >= 14);
		for (const fixture of fixtures) {
			const decision = semanticDecision({
				route_type: fixture.expected_route_type,
				action_name: fixture.expected_action_name,
				normalized_text: fixture.input,
				paraphrase: fixture.notes,
				confidence: fixture.expected_route_type === 'block' ? 'low' : 'high',
				reason:
					fixture.expected_route_type === 'block'
						? 'mixed_or_ambiguous'
						: 'fixture_expected_route',
			});
			const resolution = resolveSemanticRouting(
				semanticFixtureModel(fixture.session_state),
				fixture.input,
				decision,
				undefined,
				`semantic-summary:${fixture.name}`,
				semanticContextFlags()
			);

			if (fixture.expected_outcome === 'block') {
				assert.strictEqual(
					resolution.kind,
					'block',
					`${fixture.name} should block`
				);
				continue;
			}

			assert.strictEqual(
				resolution.kind,
				'dispatch',
				`${fixture.name} should dispatch`
			);
			if (resolution.kind === 'dispatch') {
				assert.strictEqual(
					resolution.action.type,
					fixture.expected_outcome,
					fixture.name
				);
				assert.strictEqual(
					resolution.action.semantic_route_type,
					fixture.expected_route_type,
					fixture.name
				);
			}
		}
	});

	test('semantic routing fixtures are not runtime lookup data', () => {
		const runtimeSources = [
			fs.readFileSync(path.resolve(__dirname, '../../src/phase1Model.ts'), 'utf8'),
			fs.readFileSync(path.resolve(__dirname, '../../src/semanticSidecar.ts'), 'utf8'),
			fs.readFileSync(path.resolve(__dirname, '../../src/executionWindowPanel.ts'), 'utf8'),
		].join('\n');

		assert.ok(!runtimeSources.includes('semantic-routing.json'));
	});

	test('app-server semantic runner sends read-only ephemeral semantic intake turns', async () => {
		let capturedRequest: Record<string, unknown> | undefined;
		const previousModel = process.env.CORGI_SEMANTIC_SIDECAR_MODEL;
		process.env.CORGI_SEMANTIC_SIDECAR_MODEL = 'gpt-test-semantic';
		try {
			const runner = new AppServerSemanticRunner({
				client: {
					startTurn: async (request) => {
						capturedRequest = request as unknown as Record<string, unknown>;
						return {
							threadId: 'thread-semantic',
							message: JSON.stringify(
								semanticDecision({
									route_type: 'governed_work_intent',
									normalized_text: 'analyze the repo',
								})
							),
						};
					},
					health: () => 'ready',
					shutdown: () => undefined,
				},
				fallbackRunner: semanticFallbackRunner(
					semanticDecision({ reason: 'should_not_fallback' })
				),
				cwd: '/tmp/corgi-semantic-test',
			});

			const decision = await runner.classify(semanticRunnerInput('analyze the repo'));

			assert.strictEqual(decision.route_type, 'governed_work_intent');
			assert.ok(capturedRequest);
			assert.strictEqual(capturedRequest?.runtimeKind, 'semantic_intake');
			assert.strictEqual(capturedRequest?.previewEnabled, false);
			assert.strictEqual(capturedRequest?.ephemeralThread, true);
			assert.strictEqual(capturedRequest?.model, 'gpt-test-semantic');
			assert.strictEqual(capturedRequest?.reasoning, 'low');
			assert.strictEqual(capturedRequest?.cwd, '/tmp/corgi-semantic-test');
		} finally {
			if (previousModel === undefined) {
				delete process.env.CORGI_SEMANTIC_SIDECAR_MODEL;
			} else {
				process.env.CORGI_SEMANTIC_SIDECAR_MODEL = previousModel;
			}
		}
	});

	test('app-server semantic runner extracts embedded JSON and fails closed on malformed output', async () => {
		const runner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => ({
					threadId: 'thread-semantic',
					message: `Here is the classification:\n${JSON.stringify(
						semanticDecision({
							route_type: 'governor_dialogue',
							normalized_text: 'what happened?',
						})
					)}`,
				}),
				health: () => 'ready',
				shutdown: () => undefined,
			},
		});

		const decision = await runner.classify(semanticRunnerInput('what happened?'));
		assert.strictEqual(decision.route_type, 'governor_dialogue');

		const malformedRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => ({
					threadId: 'thread-semantic',
					message: 'not json',
				}),
				health: () => 'ready',
				shutdown: () => undefined,
			},
			fallbackRunner: semanticFallbackRunner(
				semanticDecision({ reason: 'should_not_fallback' })
			),
		});
		const malformedDecision = await malformedRunner.classify(
			semanticRunnerInput('do something')
		);
		assert.strictEqual(malformedDecision.route_type, 'block');
		assert.strictEqual(malformedDecision.confidence, 'low');
		assert.strictEqual(malformedDecision.reason, 'semantic_sidecar_error');
	});

	test('app-server semantic runner falls back only for startup failures, not semantic timeouts', async () => {
		let fallbackCalls = 0;
		const fallbackRunner: SemanticRunner = {
			classify: async () => {
				fallbackCalls += 1;
				return semanticDecision({
					route_type: 'governed_work_intent',
					normalized_text: 'analyze the repo',
					reason: 'exec_fallback',
				});
			},
		};

		const startupFailureRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => {
					throw new Error('app-server initialize failed');
				},
				health: () => 'exited',
				shutdown: () => undefined,
			},
			fallbackRunner,
		});
		const fallbackDecision = await startupFailureRunner.classify(
			semanticRunnerInput('analyze the repo')
		);
		assert.strictEqual(fallbackDecision.reason, 'exec_fallback');
		assert.strictEqual(fallbackCalls, 1);

		const timeoutRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => {
					throw new Error('app-server Governor turn timed out');
				},
				health: () => 'ready',
				shutdown: () => undefined,
			},
			fallbackRunner,
		});
		const timeoutDecision = await timeoutRunner.classify(
			semanticRunnerInput('analyze the repo')
		);
		assert.strictEqual(timeoutDecision.route_type, 'block');
		assert.strictEqual(timeoutDecision.reason, 'semantic_sidecar_unavailable');
		assert.strictEqual(fallbackCalls, 1);

		const busyRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => {
					throw new Error('app-server turn already in progress');
				},
				health: () => 'ready',
				shutdown: () => undefined,
			},
			fallbackRunner,
		});
		const busyDecision = await busyRunner.classify(
			semanticRunnerInput('analyze the repo')
		);
		assert.strictEqual(busyDecision.route_type, 'block');
		assert.strictEqual(busyDecision.reason, 'semantic_sidecar_unavailable');
		assert.strictEqual(fallbackCalls, 1);
	});

	test('semantic runner factory defaults to app-server and explicit exec preserves legacy runner', () => {
		assert.ok(createSemanticRunner({ runtime: 'app-server' }) instanceof AppServerSemanticRunner);
		assert.ok(createSemanticRunner({ runtime: 'exec' }) instanceof CodexSemanticRunner);
	});

	test('semantic sidecar uses the model runner for obvious governed work requests', async () => {
		let calls = 0;
		const sidecar = new SemanticSidecar({
			classify: async () => {
				calls += 1;
				return semanticDecision({
					route_type: 'governed_work_intent',
					normalized_text: 'develop the internet connect feature',
					paraphrase: 'Ask Corgi to develop the feature.',
				});
			},
		});

		const resolution = await sidecar.route(
			'develop the internet connect feature',
			createInitialModel('2026-04-10T10:00:00.000Z')
		);

		assert.strictEqual(calls, 1);
		assert.strictEqual(resolution.kind, 'dispatch');
		if (resolution.kind === 'dispatch') {
			assert.strictEqual(resolution.action.type, 'submit_prompt');
			assert.strictEqual(
				resolution.action.semantic_route_type,
				'governed_work_intent'
			);
		}
	});

	test('semantic sidecar treats runner failures as internal unavailability', async () => {
		const sidecar = new SemanticSidecar({
			classify: async () => {
				throw new Error('network exploded');
			},
		});

		const resolution = await sidecar.route(
			'develop the internet connect feature',
			createInitialModel('2026-04-10T10:00:00.000Z')
		);

		assert.strictEqual(resolution.kind, 'block');
		if (resolution.kind === 'block') {
			assert.strictEqual(resolution.blockKind, 'semantic_unavailable');
			assert.strictEqual(
				resolution.semantic.semantic_block_reason,
				'semantic_sidecar_unavailable'
			);
		}
	});

	test('webview transcript treats requests as assistant replies and separates new turns', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(html.includes('feed-divider'));
		assert.ok(html.includes('Current turn'));
		assert.ok(html.includes('initialFeedCount'));
		assert.ok(html.includes('composerContext'));
		assert.ok(html.includes('composerActions'));
		assert.ok(html.includes('goal-strip'));
		assert.ok(html.includes('runtimeGoalDisplay'));
		assert.ok(html.includes('runtimeActionLabel'));
		assert.ok(html.includes('goalStrip: compactText'));
		assert.ok(html.includes('View source'));
		assert.ok(html.includes('foregroundRequest'));
		assert.ok(html.includes('Interpreting request'));
		assert.ok(html.includes('Checking workflow state'));
		assert.ok(html.includes('normalizeUiText'));
		assert.ok(html.includes('[hidden]'));
		assert.ok(html.includes('display: none !important;'));
		assert.ok(html.includes('latestRenderedAssistantItem'));
		assert.ok(html.includes('requestId'));
		assert.ok(html.includes("type: 'submit_prompt', text, requestId"));
		assert.ok(html.includes("type: 'set_permission_scope'"));
		assert.ok(html.includes('permissionScope: scope'));
		assert.ok(html.includes('progress-bullet-text'));
		assert.ok(html.includes('@keyframes progressShimmer'));
		assert.ok(!html.includes('@keyframes progressDotPulse'));
		assert.ok(html.includes("ui.foregroundRequest.bullets = ui.foregroundRequest.bullets.map"));
		assert.ok(html.includes('function latestRequestActorEvent(requestKey)'));
		assert.ok(html.includes("if (item.type === 'permission_request')"));
		assert.ok(html.includes("if (item.type === 'clarification_request')"));
		assert.ok(html.includes('Scope: '));
		assert.ok(html.includes('Waiting for clarification'));
		assert.ok(html.includes('Waiting for permission: '));
		assert.ok(html.includes('Executor is ready'));
		assert.ok(html.includes('latestDispatchQueuedStatus'));
		assert.ok(html.includes('latestPostExecutionStatus'));
		assert.ok(
			webviewSource.indexOf('const latestTerminalStatus = latestPostExecutionStatus(requestKey);') <
				webviewSource.indexOf('if (isDispatchQueued(snapshot) || latestDispatchQueuedStatus(requestKey))')
		);
		assert.ok(html.includes("snapshot.runState === 'queued'"));
		assert.ok(webviewSource.includes('Risks?\\\\s+or\\\\s+unknowns'));
		assert.ok(webviewSource.includes("replace(/(^|[.!?])\\\\s+(Unknowns[:]?)/gi"));
		assert.ok(html.includes('Permission needed'));
		assert.ok(html.includes('set_permission_scope'));
		assert.ok(html.includes('data-permission-scope'));
		assert.ok(html.includes('promptHistory: []'));
		assert.ok(html.includes("event.key === 'ArrowUp'"));
		assert.ok(html.includes('const hasActionSurface = Boolean('));
		assert.ok(html.includes("composerSubmitButton.textContent = busy ? 'Sending...' : mode.buttonLabel;"));
		assert.ok(!html.includes('request-marker'));
		assert.ok(!html.includes('renderRequestMarker'));
		assert.ok(!html.includes("return renderRequestMarker(item);"));
		assert.ok(!html.includes('Open</button>'));
		assert.ok(!html.includes('Reveal</button>'));
		assert.ok(!html.includes('Copy path</button>'));
		assert.ok(!html.includes('const latestItem = model.feed[model.feed.length - 1];'));
		assert.ok(!html.includes('<h1 class="header-title">Corgi</h1>'));
		assert.ok(!html.includes('<div class="brand-mark">C</div>'));
		assert.ok(!html.includes('<div class="message-label">Corgi</div>'));
		assert.ok(!html.includes('action-card'));
		assert.ok(!html.includes('Run controls'));
		assert.ok(html.includes("transportState === 'disconnected'"));
		assert.ok(
			html.includes(
				'Open the repo/workspace folder that contains orchestration/scripts/orchestrate.py, then reopen Corgi.'
			)
		);
		assert.ok(html.includes('const shouldResetPersistedState = false;'));
	});

	test('webview reports structured monitor snapshots without screenshots', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
		const autoHtml = getExecutionWindowHtml(
			'vscode-webview-resource://test',
			'nonce-for-test',
			false,
			'plan'
		);

		assert.ok(webviewSource.includes("type: 'webview_snapshot'"));
		assert.ok(webviewSource.includes('corgi_webview_snapshot.json'));
		assert.ok(webviewSource.includes('removeOldWebviewSnapshotFiles'));
		assert.ok(webviewSource.includes('fs.renameSync(tempSnapshotPath, snapshotPath)'));
		assert.ok(webviewSource.includes("filename.startsWith('corgi_webview_snapshot')"));
		assert.ok(!webviewSource.includes('corgi_webview_snapshot.txt'));
		assert.ok(webviewSource.includes('this.context.extensionMode === vscode.ExtensionMode.Development'));
		assert.ok(webviewSource.includes('this.workspaceRoot ?? this.context.extensionUri'));
		assert.ok(webviewSource.includes('monitorSessionStartedAt'));
		assert.ok(webviewSource.includes('shouldReplaceWebviewSnapshot'));
		assert.ok(webviewSource.includes('isLatestWebviewSnapshot'));
		assert.ok(webviewSource.includes('existing.monitorSessionStartedAt === undefined'));
		assert.ok(webviewSource.includes('candidateSession < existingSession'));
		assert.ok(webviewSource.includes('candidateRenderedAt >= existingRenderedAt'));
		assert.ok(html.includes('function collectWebviewSnapshot(reason)'));
		assert.ok(html.includes('function cloneForSnapshot(value)'));
			assert.ok(html.includes("type: 'webview_snapshot'"));
			assert.ok(html.includes('messages: collectTextRows(feed'));
			assert.ok(html.includes('transcript: collectTextRows(feed'));
			assert.ok(html.includes('activity: collectTextRows(feed'));
			assert.ok(html.includes('detailsHidden:'));
			assert.ok(html.includes("actions: collectTextRows(composerActions, 'button')"));
			assert.ok(html.includes('model: {'));
		assert.ok(html.includes('feed: cloneForSnapshot(feedItems)'));
		assert.ok(html.includes('activeClarification: cloneForSnapshot(model?.activeClarification)'));
		assert.ok(html.includes('autoStep: {'));
		assert.ok(autoHtml.includes('const testWindowAutoStepMode = "plan";'));
		assert.ok(autoHtml.includes('function scheduleTestWindowAutoStep(reason)'));
		assert.ok(autoHtml.includes('button[data-clarification-answer]'));
		assert.ok(autoHtml.includes('button[data-action="set_permission_scope"]'));
		assert.ok(!html.toLowerCase().includes('screenshot'));
		assert.ok(!html.includes('toDataURL'));
	});

	test('webview can reset persisted state for development launches', () => {
		const html = getExecutionWindowHtml(
			'vscode-webview-resource://test',
			'nonce-for-test',
			true
		);

		assert.ok(html.includes('const shouldResetPersistedState = true;'));
		assert.ok(html.includes('vscode.setState(defaultPersistedState);'));
	});

	test('webview removes the current work panel and keeps context in the goal strip', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');

		assert.ok(!html.includes('<section class="session-rail" id="sessionRail"></section>'));
		assert.ok(!html.includes('data-action="toggle_rail"'));
		assert.ok(html.includes('class="goal-strip" id="headerContent"'));
		assert.ok(html.includes('<span class="goal-label">Goal:</span>'));
		assert.ok(html.includes('<span class="goal-label">Step:</span>'));
		assert.ok(html.includes('<span class="status-dot '));
		assert.ok(!html.includes('Lane: '));
		assert.ok(!html.includes('Branch: '));
	});

	test('plan-ready header stays calm even after snapshot freshness ages', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');

		assert.ok(html.includes('model?.planReadyRequest'));
		assert.ok(html.includes("return 'Plan ready';"));
		assert.ok(html.includes("return 'is-ready';"));
		assert.ok(html.includes('statusDotClass(snapshot, stale)'));
	});

	test('active clarification keeps the composer answerable while progress is live', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');

		assert.ok(html.includes("ui.foregroundRequest.status === 'live'"));
		assert.ok(html.includes('!model?.activeClarification'));
		assert.ok(html.includes("buttonLabel: 'Answer'"));
	});

	test('submit prompt moves the model into clarification state', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentActor, 'intake_shell');
		assert.strictEqual(model.snapshot.currentStage, 'clarification_needed');
		assert.ok(model.activeClarification);
		assert.strictEqual(model.snapshot.pendingPermissionRequest, undefined);
	});

	test('broad analysis prompts offer clarification choices', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze this folder.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.ok(model.activeClarification);
		assert.strictEqual(model.activeClarification?.kind, 'analysis_focus');
		assert.strictEqual(model.activeClarification?.options?.length, 3);
		assert.strictEqual(model.activeClarification?.allowFreeText, true);
	});

	test('governor dialogue requests observe permission before replying', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const model = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'What is the current progress?',
			semantic_route_type: 'governor_dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentStage, 'permission_needed');
		assert.strictEqual(model.snapshot.currentActor, 'orchestration');
		assert.strictEqual(model.activeClarification, undefined);
		assert.ok(model.snapshot.pendingPermissionRequest);
		assert.strictEqual(model.snapshot.pendingPermissionRequest?.recommendedScope, 'observe');
	});

	test('natural progress questions also request observe permission first', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const model = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'what happen?',
			semantic_route_type: 'governor_dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentStage, 'permission_needed');
		assert.strictEqual(model.activeClarification, undefined);
		assert.ok(model.snapshot.pendingPermissionRequest);
		assert.strictEqual(model.snapshot.pendingPermissionRequest?.recommendedScope, 'observe');
	});

	test('submit prompt without semantic route metadata fails closed', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'what happened?',
			request_id: 'req-missing-route',
			now: '2026-04-10T10:00:05.000Z',
		});

		const lastItem = model.feed[model.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.presentation_key, 'error.semantic_route_required');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-missing-route');
		assert.strictEqual(model.snapshot.pendingPermissionRequest, undefined);
		assert.strictEqual(model.activeClarification, undefined);
	});

	test('observe permission resumes the same governor dialogue request', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const gatedModel = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'hello!',
			semantic_route_type: 'governor_dialogue',
			request_id: 'req-hello',
			now: '2026-04-10T10:00:05.000Z',
		});

		const resumedModel = applyModelAction(gatedModel, {
			type: 'set_permission_scope',
			permission_scope: 'observe',
			context_ref: gatedModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-observe-click',
			now: '2026-04-10T10:00:10.000Z',
		});

		assert.strictEqual(resumedModel.snapshot.permissionScope, 'observe');
		assert.strictEqual(resumedModel.snapshot.pendingPermissionRequest, undefined);
		assert.strictEqual(resumedModel.snapshot.currentActor, 'governor');
		assert.strictEqual(resumedModel.snapshot.currentStage, 'dialogue_ready');
		const lastItem = resumedModel.feed[resumedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'actor_event');
		assert.strictEqual(lastItem.title, 'Governor response');
		assert.ok(!(lastItem.body ?? '').includes('waiting for a observe permission choice'));
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-hello');
	});

	test('a new governed request keeps its own foreground flow after an observe dialogue completes', () => {
		const initialModel = createInitialModel('2026-04-10T10:00:00.000Z');
		const gatedDialogueModel = applyModelAction(initialModel, {
			type: 'submit_prompt',
			text: 'hello!',
			semantic_route_type: 'governor_dialogue',
			request_id: 'req-hello',
			now: '2026-04-10T10:00:05.000Z',
		});
		const observedDialogueModel = applyModelAction(gatedDialogueModel, {
			type: 'set_permission_scope',
			permission_scope: 'observe',
			context_ref: gatedDialogueModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-observe',
			now: '2026-04-10T10:00:10.000Z',
		});
		const governedPromptModel = applyModelAction(observedDialogueModel, {
			type: 'submit_prompt',
			text: 'analyze the repo',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:15.000Z',
		});
		const clarifiedModel = applyModelAction(governedPromptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: governedPromptModel.activeClarification?.contextRef,
			request_id: 'req-clarify',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(observedDialogueModel.activeForegroundRequestId, undefined);
		assert.strictEqual(governedPromptModel.activeForegroundRequestId, 'req-analyze');
		assert.strictEqual(clarifiedModel.activeForegroundRequestId, 'req-analyze');
		assert.strictEqual(
			clarifiedModel.snapshot.pendingPermissionRequest?.recommendedScope,
			'plan'
		);
		const lastItem = clarifiedModel.feed[clarifiedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'permission_request');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-clarify');
	});

	test('answer clarification produces a permission request', () => {
		const draftModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const acceptedModel = applyModelAction(draftModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: draftModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});

		assert.strictEqual(acceptedModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(acceptedModel.snapshot.currentStage, 'permission_needed');
		assert.strictEqual(acceptedModel.acceptedIntakeSummary, undefined);
		assert.ok(acceptedModel.snapshot.pendingPermissionRequest);
		assert.deepStrictEqual(acceptedModel.snapshot.pendingPermissionRequest.allowedScopes, [
			'plan',
			'execute',
		]);
		assert.strictEqual(acceptedModel.snapshot.permissionScope, 'unset');
		assert.strictEqual(acceptedModel.activeClarification, undefined);
	});

	test('weaker permission scope cannot accept a stronger permission request', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-weaker-submit',
			now: '2026-04-10T10:00:05.000Z',
		});
		const permissionModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			request_id: 'req-weaker-answer',
			now: '2026-04-10T10:00:10.000Z',
		});
		const rejectedModel = applyModelAction(permissionModel, {
			type: 'set_permission_scope',
			permission_scope: 'observe',
			context_ref: permissionModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-weaker-observe',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(rejectedModel.snapshot.permissionScope, 'unset');
		assert.ok(rejectedModel.snapshot.pendingPermissionRequest);
		assert.strictEqual(rejectedModel.acceptedIntakeSummary, undefined);
		const lastItem = rejectedModel.feed[rejectedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.title, 'Permission scope too low');
		assert.strictEqual(lastItem.presentation_key, 'error.permission_scope_too_low');
	});

	test('plan permission accepts intake and returns a Governor planning response', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-plan',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const runningModel = applyModelAction(approvalModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: approvalModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-permission-click',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(runningModel.snapshot.currentActor, 'governor');
		assert.strictEqual(runningModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(runningModel.snapshot.runState, 'idle');
		assert.strictEqual(runningModel.snapshot.permissionScope, 'plan');
		assert.ok(runningModel.acceptedIntakeSummary);
		assert.ok(runningModel.planReadyRequest);
		assert.strictEqual(runningModel.planReadyRequest.foregroundRequestId, 'req-plan');
		assert.deepStrictEqual(runningModel.planReadyRequest.allowedActions, [
			'execute_plan',
			'revise_plan',
		]);
		assert.ok(runningModel.snapshot.recentArtifacts.length >= 2);
		assert.ok(getArtifactById(runningModel, 'artifact-orchestration-readme'));
		assert.ok(!runningModel.feed.some((item) => item.type === 'artifact_reference'));
		const lastItem = runningModel.feed[runningModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'actor_event');
		assert.strictEqual(lastItem.source_actor, 'governor');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-plan');
		assert.match(lastItem.body ?? '', /Plan scope/);
		assert.match(lastItem.body ?? '', /Risks or unknowns/);
		assert.match(lastItem.body ?? '', /src\/executionWindowPanel\.ts/);
		assert.match(lastItem.body ?? '', /orchestration\/harness\/session\.py/);
	});

	test('execute plan action authorizes execute and queues dispatch without a second permission click', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on bugs, regressions, and architectural risks.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const continuationModel = applyModelAction(planReadyModel, {
			type: 'execute_plan',
			context_ref: planReadyModel.planReadyRequest?.contextRef,
			request_id: 'req-do-it',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(continuationModel.activeClarification, undefined);
		assert.strictEqual(continuationModel.snapshot.permissionScope, 'execute');
		assert.strictEqual(continuationModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(continuationModel.snapshot.currentStage, 'plan_executing');
		assert.strictEqual(continuationModel.snapshot.runState, 'queued');
		assert.strictEqual(continuationModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(
			!continuationModel.feed.some(
				(item) =>
					item.type === 'permission_request' &&
					item.in_response_to_request_id === 'req-do-it'
			)
		);
		assert.ok(
			!continuationModel.feed.some((item) =>
				item.in_response_to_request_id === 'req-do-it' &&
				/permission needed|choose execute/i.test(`${item.title ?? ''}\n${item.body ?? ''}`)
			)
		);
		assert.ok(continuationModel.acceptedIntakeSummary);
		assert.strictEqual(continuationModel.planReadyRequest, undefined);
		assert.ok(!continuationModel.feed.some((item) => item.type === 'clarification_request' && item.in_response_to_request_id === 'req-do-it'));
		const lastItem = continuationModel.feed[continuationModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'system_status');
		assert.strictEqual(lastItem.title, 'Executor starting');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-do-it');
	});

	test('optimistic execute plan state does not expose stop before authoritative running state', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeForegroundRequestId: 'req-do-it',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				currentActor: 'orchestration',
				currentStage: 'plan_executing',
				permissionScope: 'execute',
				runState: 'queued',
			},
		};

		const snapshot = renderWebviewSnapshot(model);

		assert.ok(!snapshot.actions.some((action) => action.text === 'Stop'));
	});

	test('execute plan action with stale context fails closed', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const failedModel = applyModelAction(planReadyModel, {
			type: 'execute_plan',
			context_ref: 'stale-plan-context',
			request_id: 'req-stale-execute',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(failedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(failedModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(failedModel.planReadyRequest);
		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.presentation_key, 'error.stale_context');
	});

	test('execute plan action without accepted intake fails with specific plan error', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const failedModel = applyModelAction(
			{
				...planReadyModel,
				acceptedIntakeSummary: undefined,
			},
			{
				type: 'execute_plan',
				context_ref: planReadyModel.planReadyRequest?.contextRef,
				request_id: 'req-missing-intake-execute',
				now: '2026-04-10T10:00:20.000Z',
			}
		);

		assert.strictEqual(failedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(failedModel.snapshot.permissionScope, 'plan');
		assert.ok(failedModel.planReadyRequest);
		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.title, 'Accepted intake missing');
		assert.strictEqual(lastItem.presentation_key, 'error.plan_not_ready');
		assert.deepStrictEqual(lastItem.presentation_args, { reason: 'missing_intake' });
	});

	test('execute plan action without request id fails closed', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const failedModel = applyModelAction(planReadyModel, {
			type: 'execute_plan',
			context_ref: planReadyModel.planReadyRequest?.contextRef,
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(failedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(failedModel.snapshot.permissionScope, 'plan');
		assert.strictEqual(failedModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(failedModel.planReadyRequest);
		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.title, 'Request id required');
		assert.strictEqual(lastItem.presentation_key, 'error.stale_context');
	});

	test('plan revision action stays in governor planning mode without starting execution', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const revisedModel = applyModelAction(planReadyModel, {
			type: 'revise_plan',
			text: 'Also explain the testing risks before execution.',
			context_ref: planReadyModel.planReadyRequest?.contextRef,
			request_id: 'req-revise-plan',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(revisedModel.snapshot.permissionScope, 'plan');
		assert.strictEqual(revisedModel.snapshot.currentActor, 'governor');
		assert.strictEqual(revisedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(revisedModel.snapshot.runState, 'idle');
		assert.strictEqual(revisedModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(revisedModel.planReadyRequest);
		assert.notStrictEqual(
			revisedModel.planReadyRequest.contextRef,
			planReadyModel.planReadyRequest?.contextRef
		);
		assert.strictEqual(
			revisedModel.planReadyRequest.planVersion,
			(planReadyModel.planReadyRequest?.planVersion ?? 1) + 1
		);
		const lastItem = revisedModel.feed[revisedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'actor_event');
		assert.strictEqual(lastItem.source_actor, 'governor');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-revise-plan');
		assert.match(lastItem.body ?? '', /revise the current plan/i);
	});

	test('execute permission accepts the draft and queues dispatch truth', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const runningModel = applyModelAction(approvalModel, {
			type: 'set_permission_scope',
			permission_scope: 'execute',
			context_ref: approvalModel.snapshot.pendingPermissionRequest?.contextRef,
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(runningModel.snapshot.permissionScope, 'execute');
		assert.strictEqual(runningModel.snapshot.runState, 'queued');
		assert.strictEqual(runningModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(runningModel.snapshot.currentStage, 'dispatch_queued');
		assert.ok(runningModel.acceptedIntakeSummary?.body.includes('Execute permission'));
	});

	test('declining a permission request leaves scope unchanged and blocks the request', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const permissionModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const declinedModel = applyModelAction(permissionModel, {
			type: 'decline_permission',
			context_ref: permissionModel.snapshot.pendingPermissionRequest?.contextRef,
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(declinedModel.snapshot.permissionScope, 'unset');
		assert.strictEqual(declinedModel.snapshot.pendingPermissionRequest, undefined);
		assert.strictEqual(declinedModel.snapshot.currentStage, 'permission_declined');
	});

	test('state-bound actions fail closed when the context token is stale', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});

		const failedModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: 'clarification-context-stale',
			request_id: 'corgi-request:test-stale',
			now: '2026-04-10T10:00:10.000Z',
		});

		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.in_response_to_request_id, 'corgi-request:test-stale');
		assert.match(lastItem.body ?? '', /clarification changed/i);
	});

	test('new prompts supersede a pending permission request instead of holding it', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const supersededModel = applyModelAction(approvalModel, {
			type: 'submit_prompt',
			text: 'Start over with a quieter transcript.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.ok(
			supersededModel.feed.some(
				(item) =>
					item.type === 'system_status' &&
					item.title === 'Pending permission request superseded'
			)
		);
	});

	test('stale snapshots are detected from freshness metadata', () => {
		const model = createInitialModel('2026-04-10T10:00:00.000Z');

		assert.strictEqual(
			isSnapshotStale(
				model.snapshot.snapshotFreshness,
				Date.parse('2026-04-10T10:00:20.000Z')
			),
			false
		);
		assert.strictEqual(
			isSnapshotStale(
				model.snapshot.snapshotFreshness,
				Date.parse('2026-04-10T10:01:00.000Z')
			),
			true
		);
	});

	test('feed items carry internal provenance metadata', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze this folder.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'corgi-request:test-provenance',
			now: '2026-04-10T10:00:05.000Z',
		});

		const clarificationItem = model.feed.find(
			(item) => item.type === 'clarification_request'
		);
		assert.ok(clarificationItem);
		assert.strictEqual(clarificationItem?.source_layer, 'intake');
		assert.strictEqual(clarificationItem?.source_actor, 'intake_shell');
		assert.strictEqual(clarificationItem?.turn_type, 'governed_work_intent');
		assert.strictEqual(
			clarificationItem?.in_response_to_request_id,
			'corgi-request:test-provenance'
		);
	});
});
