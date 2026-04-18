import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';
import * as vm from 'vm';
import * as vscode from 'vscode';
import {
	applyModelAction,
	createInitialModel,
	getArtifactById,
	isSnapshotStale,
} from '../phase1Model';
import {
	createExecutionTransport,
	resolveExecutionTransportTarget,
	TransportUnavailableError,
} from '../executionTransport';
import {
	DEFAULT_SEMANTIC_SIDECAR_MODEL,
	resolveSemanticRouting,
	SemanticSidecar,
	type SemanticDecision,
} from '../semanticSidecar';
import {
	EXECUTION_WINDOW_CONTAINER_ID,
	EXECUTION_WINDOW_VIEW_ID,
	getExecutionWindowHtml,
} from '../executionWindowPanel';

const PACKAGE_JSON_PATH = path.resolve(__dirname, '../../package.json');
const LAUNCH_JSON_PATH = path.resolve(__dirname, '../../.vscode/launch.json');
const EXTENSION_TS_PATH = path.resolve(__dirname, '../../src/extension.ts');
const EXECUTION_WINDOW_PANEL_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionWindowPanel.ts'
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

suite('Corgi Webview UX', () => {
	test('ships sidebar webview contributions without chat participants or open command', () => {
		const manifest = loadPackageJson();
		const contributes = manifest.contributes as Record<string, unknown>;
		const activationEvents = manifest.activationEvents as string[];
		const viewsContainers = contributes.viewsContainers as Record<string, unknown>;
		const views = contributes.views as Record<string, unknown>;

		assert.ok(Array.isArray(activationEvents));
		assert.ok(viewsContainers.activitybar);
		assert.ok(views[EXECUTION_WINDOW_CONTAINER_ID]);
		assert.strictEqual(contributes.chatParticipants, undefined);
		assert.strictEqual(contributes.commands, undefined);
		assert.ok(!activationEvents.some((event) => event.startsWith('onChatParticipant:')));
	});

	test('opens the Corgi sidebar view without throwing', async () => {
		await assert.doesNotReject(async () => {
			await vscode.commands.executeCommand(
				`workbench.view.extension.${EXECUTION_WINDOW_CONTAINER_ID}`
			);
			await vscode.commands.executeCommand(`${EXECUTION_WINDOW_VIEW_ID}.focus`);
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
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(extensionSource.includes('context.extensionMode !== vscode.ExtensionMode.Development'));
		assert.ok(webviewSource.includes('return context.extensionMode === vscode.ExtensionMode.Development;'));
		assert.ok(!extensionSource.includes('CORGI_RESET_DEV_SESSION'));
		assert.ok(!extensionSource.includes('CORGI_RESET_WEBVIEW_STATE'));
		assert.ok(!webviewSource.includes('CORGI_RESET_WEBVIEW_STATE'));
	});

	test('first-turn requests only send sessionRef after transport state is authoritative', () => {
		const webviewSource = fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8');

		assert.ok(webviewSource.includes('private hasAuthoritativeTransportState = false;'));
		assert.ok(webviewSource.includes('this.hasAuthoritativeTransportState = true;'));
		assert.match(
			webviewSource,
			/session_ref:\s*action\.session_ref\s*\?\?\s*\(\s*this\.hasAuthoritativeTransportState\s*\?\s*this\.model\.snapshot\.sessionRef\s*:\s*undefined\s*\)/
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

		assert.ok(html.includes('feed-divider'));
		assert.ok(html.includes('Current turn'));
		assert.ok(html.includes('initialFeedCount'));
		assert.ok(html.includes('composerContext'));
		assert.ok(html.includes("renderRevealPill('Current work', railTask, 'is-primary')"));
		assert.ok(html.includes('View source'));
		assert.ok(html.includes('foregroundRequest'));
		assert.ok(html.includes('Model clarifying'));
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
		assert.ok(html.includes('Execution started'));
		assert.ok(html.includes('Permission needed'));
		assert.ok(html.includes('set_permission_scope'));
		assert.ok(html.includes('data-permission-scope'));
		assert.ok(html.includes('promptHistory: []'));
		assert.ok(html.includes("event.key === 'ArrowUp'"));
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
		assert.ok(html.includes("transportState === 'disconnected'"));
		assert.ok(
			html.includes(
				'Open the repo/workspace folder that contains orchestration/scripts/orchestrate.py, then reopen Corgi.'
			)
		);
		assert.ok(html.includes('const shouldResetPersistedState = false;'));
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

	test('webview removes the current work panel and keeps context in the header', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');

		assert.ok(!html.includes('<section class="session-rail" id="sessionRail"></section>'));
		assert.ok(!html.includes('data-action="toggle_rail"'));
		assert.ok(html.includes("renderRevealPill('Current work', railTask, 'is-primary')"));
		assert.ok(html.includes('pill-reveal-value'));
		assert.ok(html.includes('<span class="status-dot '));
		assert.ok(!html.includes('Lane: '));
		assert.ok(!html.includes('Branch: '));
	});

	test('submit prompt moves the model into clarification state', () => {
		const model = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
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
			now: '2026-04-10T10:00:05.000Z',
		});

		assert.strictEqual(model.snapshot.currentStage, 'permission_needed');
		assert.strictEqual(model.activeClarification, undefined);
		assert.ok(model.snapshot.pendingPermissionRequest);
		assert.strictEqual(model.snapshot.pendingPermissionRequest?.recommendedScope, 'observe');
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
		assert.strictEqual(acceptedModel.snapshot.permissionScope, 'unset');
		assert.strictEqual(acceptedModel.activeClarification, undefined);
	});

	test('plan permission turns the draft into accepted intake artifacts', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
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
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(runningModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(runningModel.snapshot.currentStage, 'intake_accepted');
		assert.strictEqual(runningModel.snapshot.permissionScope, 'plan');
		assert.ok(runningModel.acceptedIntakeSummary);
		assert.ok(runningModel.snapshot.recentArtifacts.length >= 2);
		assert.ok(getArtifactById(runningModel, 'artifact-orchestration-readme'));
		assert.ok(!runningModel.feed.some((item) => item.type === 'artifact_reference'));
	});

	test('execute permission accepts the draft and marks the session as running', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
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
		assert.strictEqual(runningModel.snapshot.runState, 'running');
		assert.strictEqual(runningModel.snapshot.currentActor, 'governor');
		assert.strictEqual(runningModel.snapshot.currentStage, 'running');
		assert.ok(runningModel.acceptedIntakeSummary?.body.includes('Execute permission'));
	});

	test('declining a permission request leaves scope unchanged and blocks the request', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
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
