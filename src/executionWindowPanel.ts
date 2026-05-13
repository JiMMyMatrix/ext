import { randomUUID } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { resolveOrchestrationStateRootPath } from './agentPaths';
import {
	appendError,
	appendControllerSemanticClarification,
	applyModelAction,
	createInitialModel,
	getArtifactById,
	type ExecutionWindowModel,
	type ModelAction,
} from './phase1Model';
import { resetDevelopmentSessionState } from './developmentSession';
import {
	createExecutionTransport,
	TransportUnavailableError,
	type ExecutionTransport,
	type ExecutionRuntimeEvent,
} from './executionTransport';
import {
	SemanticSidecar,
	type SemanticBlockKind,
	type SemanticLoopState,
	type SemanticSidecarRuntime,
} from './semanticSidecar';
import { buildRuntimeErgonomicsKernel } from './runtimeErgonomicsKernel';
import {
	getExecutionWindowHtml,
	type TestWindowAutoStepMode,
} from './executionWindowRenderer';

export { getExecutionWindowHtml } from './executionWindowRenderer';

export const EXECUTION_WINDOW_CONTAINER_ID = 'extExecutionWindowSidebar';
export const EXECUTION_WINDOW_VIEW_ID = 'ext.executionWindowView';
export const OPEN_EXECUTION_WINDOW_COMMAND_ID = 'ext.openExecutionWindow';

function shouldResetDevelopmentWebviewState(context: vscode.ExtensionContext): boolean {
	return context.extensionMode === vscode.ExtensionMode.Development;
}

function semanticMode(): 'sidecar-first' | 'governor-first' {
	return process.env.CORGI_SEMANTIC_MODE?.trim() === 'governor-first'
		? 'governor-first'
		: 'sidecar-first';
}

function semanticSidecarRuntime(): SemanticSidecarRuntime {
	const envMode = process.env.CORGI_SEMANTIC_SIDECAR_RUNTIME?.trim();
	if (envMode === 'app-server' || envMode === 'exec') {
		return envMode;
	}
	if (typeof vscode.workspace.getConfiguration !== 'function') {
		return 'app-server';
	}
	const configured = vscode.workspace
		.getConfiguration('corgi')
		.get<string>('semanticSidecarRuntime');
	return configured === 'exec' ? 'exec' : 'app-server';
}

function testWindowAutoPrompt(context: vscode.ExtensionContext): string | undefined {
	if (context.extensionMode !== vscode.ExtensionMode.Development) {
		return undefined;
	}

	const prompt = process.env.CORGI_TEST_WINDOW_AUTO_PROMPT?.trim();
	return prompt || undefined;
}

function testWindowAutoPromptPreset(context: vscode.ExtensionContext): string | undefined {
	if (context.extensionMode !== vscode.ExtensionMode.Development) {
		return undefined;
	}

	return process.env.ORCHESTRATION_TEST_PROMPT_PRESET?.trim() || undefined;
}

function testWindowAutoPromptAction(
	context: vscode.ExtensionContext
): 'submit_prompt' | 'start_goal' {
	if (context.extensionMode !== vscode.ExtensionMode.Development) {
		return 'submit_prompt';
	}

	const explicitAction = process.env.CORGI_TEST_WINDOW_AUTO_ACTION?.trim().toLowerCase();
	if (explicitAction === 'start_goal' || explicitAction === 'start-goal') {
		return 'start_goal';
	}
	if (explicitAction === 'submit_prompt' || explicitAction === 'submit-prompt') {
		return 'submit_prompt';
	}

	const preset = testWindowAutoPromptPreset(context);
	if (preset === 'pet-life-diary-goal-program' || preset === 'pet-life-diary-goal-review-retry') {
		return 'start_goal';
	}
	return 'submit_prompt';
}

function testWindowAutoStepMode(
	context: vscode.ExtensionContext
): TestWindowAutoStepMode {
	if (context.extensionMode !== vscode.ExtensionMode.Development) {
		return 'off';
	}

	const mode = process.env.CORGI_TEST_WINDOW_AUTO_STEPS?.trim().toLowerCase();
	if (mode === 'execute') {
		return 'execute';
	}
	if (mode === 'plan' || mode === '1' || mode === 'true') {
		return 'plan';
	}
	return 'off';
}

type WebviewMessage =
	| { type: 'ready' }
	| { type: 'refresh_state' }
	| { type: 'webview_snapshot'; payload?: unknown }
	| { type: 'submit_prompt'; text?: string; requestId?: string }
	| { type: 'start_goal'; text?: string; requestId?: string }
	| { type: 'execute_plan'; requestId?: string }
	| { type: 'revise_plan'; text?: string; requestId?: string }
	| { type: 'answer_clarification'; text?: string; requestId?: string }
	| {
			type: 'set_permission_scope';
			permissionScope?: 'observe' | 'plan' | 'execute';
			requestId?: string;
	  }
	| { type: 'decline_permission'; requestId?: string }
	| { type: 'interrupt_run'; requestId?: string }
	| { type: 'open_artifact'; artifactId?: string }
	| { type: 'reveal_artifact_path'; artifactId?: string }
	| { type: 'copy_artifact_path'; artifactId?: string };

type WebviewSnapshotFile = {
	recordedAt: string;
	monitorSessionId?: string;
	monitorSessionStartedAt?: string;
	viewId: string;
	payload: unknown;
};

export class ExecutionWindowPanel implements vscode.WebviewViewProvider {
	public static register(context: vscode.ExtensionContext): ExecutionWindowPanel {
		const provider = new ExecutionWindowPanel(context);

		context.subscriptions.push(
			vscode.window.registerWebviewViewProvider(
				EXECUTION_WINDOW_VIEW_ID,
				provider,
				{
					webviewOptions: {
						retainContextWhenHidden: true,
					},
				}
			),
			vscode.commands.registerCommand(OPEN_EXECUTION_WINDOW_COMMAND_ID, () =>
				provider.openView()
			),
			provider
		);

		return provider;
	}

	private model: ExecutionWindowModel;
	private readonly transport: ExecutionTransport;
	private readonly semanticSidecar: SemanticSidecar;
	private readonly context: vscode.ExtensionContext;
	private view: vscode.WebviewView | undefined;
	private readonly workspaceRoot: vscode.Uri | undefined;
	private readonly disposables: vscode.Disposable[] = [];
	private readonly webviewDisposables: vscode.Disposable[] = [];
	private readonly monitorSessionId = randomUUID();
	private readonly monitorSessionStartedAt = new Date().toISOString();
	private semanticLoopState: SemanticLoopState | undefined;
	private hasAuthoritativeTransportState = false;
	private didSubmitTestWindowAutoPrompt = false;
	private didResetDevelopmentSessionState = false;

	private constructor(context: vscode.ExtensionContext) {
		this.context = context;
		this.workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
		this.model = createInitialModel();
		this.transport = createExecutionTransport(
			context.extensionMode,
			this.workspaceRoot,
			context.extensionUri
		);
		if (this.transport.onRuntimeEvent) {
			this.disposables.push(
				this.transport.onRuntimeEvent((event) => this.handleRuntimeEvent(event))
			);
		}
		this.semanticSidecar = new SemanticSidecar({
			runtime: semanticSidecarRuntime(),
		});
	}

	public resolveWebviewView(webviewView: vscode.WebviewView) {
		this.disposeWebviewListeners();
		this.resetDevelopmentSessionStateOnce();
		this.view = webviewView;
		this.view.title = 'Corgi';
		this.view.webview.options = {
			enableScripts: true,
		};
		this.view.webview.html = getExecutionWindowHtml(
			this.view.webview.cspSource,
			undefined,
			shouldResetDevelopmentWebviewState(this.context),
			testWindowAutoStepMode(this.context)
		);
		this.webviewDisposables.push(
			this.view.webview.onDidReceiveMessage((message) => {
				void this.handleMessage(message as WebviewMessage);
			})
		);
		void this.initializeResolvedWebview();
		this.transport.prewarm?.();
	}

	private resetDevelopmentSessionStateOnce() {
		if (this.didResetDevelopmentSessionState) {
			return;
		}
		this.didResetDevelopmentSessionState = true;
		resetDevelopmentSessionState(this.context);
	}

	public async openView() {
		await vscode.commands.executeCommand(
			`workbench.view.extension.${EXECUTION_WINDOW_CONTAINER_ID}`
		);
		await vscode.commands.executeCommand(`${EXECUTION_WINDOW_VIEW_ID}.focus`);
	}

	public dispose() {
		this.disposeWebviewListeners();
		this.semanticSidecar.shutdown();
		this.transport.dispose?.();

		while (this.disposables.length) {
			this.disposables.pop()?.dispose();
		}
	}

	private disposeWebviewListeners() {
		while (this.webviewDisposables.length) {
			this.webviewDisposables.pop()?.dispose();
		}
	}

	private postState() {
		void this.view?.webview.postMessage({
			type: 'state',
			payload: {
				...this.model,
				runtimeErgonomics: buildRuntimeErgonomicsKernel(this.model),
			},
		});
	}

	private handleRuntimeEvent(event: ExecutionRuntimeEvent) {
		this.appendDevelopmentLog(
			[
				`runtime ${event.stage}`,
				event.runtimeKind ? `kind=${event.runtimeKind}` : undefined,
				event.requestId ? `request=${event.requestId}` : undefined,
				event.runtimeRequestId ? `runtime=${event.runtimeRequestId}` : undefined,
				event.elapsedMs !== undefined ? `elapsed=${event.elapsedMs}ms` : undefined,
				event.totalElapsedMs !== undefined ? `total=${event.totalElapsedMs}ms` : undefined,
				event.promptChars !== undefined ? `promptChars=${event.promptChars}` : undefined,
				event.modelName ? `model=${event.modelName}` : undefined,
				event.reasoning ? `reasoning=${event.reasoning}` : undefined,
			]
				.filter(Boolean)
				.join(' ')
		);
		if (event.model) {
			this.model = event.model;
			this.postState();
		}
		void this.view?.webview.postMessage({
			type: 'runtime_progress',
			payload: event,
		});
	}

	private appendDevelopmentLog(message: string) {
		if (this.context.extensionMode !== vscode.ExtensionMode.Development) {
			return;
		}

		const monitorRoot = this.monitorRootUri();
		if (!monitorRoot) {
			return;
		}

		const logDir = resolveOrchestrationStateRootPath(monitorRoot.fsPath);
		fs.mkdirSync(logDir, { recursive: true });
		fs.appendFileSync(
			path.join(logDir, 'corgi_extension_dev.log'),
			`${new Date().toISOString()} ${message}\n`,
			'utf8'
		);
	}

	private shouldWriteWebviewSnapshots(): boolean {
		return this.context.extensionMode === vscode.ExtensionMode.Development;
	}

	private monitorRootUri(): vscode.Uri | undefined {
		return this.workspaceRoot ?? this.context.extensionUri;
	}

	private writeWebviewSnapshot(payload: unknown) {
		if (!this.shouldWriteWebviewSnapshots()) {
			return;
		}

		const monitorRoot = this.monitorRootUri();
		if (!monitorRoot) {
			return;
		}

		const monitorDir = resolveOrchestrationStateRootPath(monitorRoot.fsPath);
		const snapshot: WebviewSnapshotFile = {
			recordedAt: new Date().toISOString(),
			monitorSessionId: this.monitorSessionId,
			monitorSessionStartedAt: this.monitorSessionStartedAt,
			viewId: EXECUTION_WINDOW_VIEW_ID,
			payload,
		};
		const snapshotPath = path.join(monitorDir, 'corgi_webview_snapshot.json');
		fs.mkdirSync(monitorDir, { recursive: true });
		this.removeOldWebviewSnapshotFiles(monitorDir, snapshotPath);
		if (!this.shouldReplaceWebviewSnapshot(snapshotPath, snapshot)) {
			return;
		}

		const json = JSON.stringify(snapshot, null, 2);
		const tempSnapshotPath = path.join(
			monitorDir,
			`corgi_webview_snapshot.${process.pid}.${this.monitorSessionId}.tmp`
		);

		fs.writeFileSync(tempSnapshotPath, json, 'utf8');
		fs.renameSync(tempSnapshotPath, snapshotPath);
	}

	private removeOldWebviewSnapshotFiles(
		monitorDir: string,
		latestSnapshotPath: string
	) {
		for (const filename of fs.readdirSync(monitorDir)) {
			if (!filename.startsWith('corgi_webview_snapshot')) {
				continue;
			}

			const candidatePath = path.join(monitorDir, filename);
			if (candidatePath === latestSnapshotPath) {
				continue;
			}

			fs.rmSync(candidatePath, { force: true, recursive: true });
		}
	}

	private shouldReplaceWebviewSnapshot(
		snapshotPath: string,
		candidate: WebviewSnapshotFile
	): boolean {
		if (!fs.existsSync(snapshotPath)) {
			return true;
		}

		try {
			const existing = JSON.parse(
				fs.readFileSync(snapshotPath, 'utf8')
			) as Partial<WebviewSnapshotFile>;
			return this.isLatestWebviewSnapshot(candidate, existing);
		} catch {
			return true;
		}
	}

	private isLatestWebviewSnapshot(
		candidate: WebviewSnapshotFile,
		existing: Partial<WebviewSnapshotFile>
	): boolean {
		const candidateSession = Date.parse(candidate.monitorSessionStartedAt ?? '');
		const existingSession = Date.parse(existing.monitorSessionStartedAt ?? '');
		if (existing.monitorSessionStartedAt === undefined) {
			return true;
		}
		if (!Number.isNaN(existingSession) && !Number.isNaN(candidateSession)) {
			if (candidateSession < existingSession) {
				return false;
			}
			if (candidateSession > existingSession) {
				return true;
			}
		}

		const candidateRenderedAt = this.webviewSnapshotRenderedAt(candidate);
		const existingRenderedAt = this.webviewSnapshotRenderedAt(existing);
		if (!Number.isNaN(existingRenderedAt) && !Number.isNaN(candidateRenderedAt)) {
			return candidateRenderedAt >= existingRenderedAt;
		}

		const candidateRecordedAt = Date.parse(candidate.recordedAt);
		const existingRecordedAt = Date.parse(existing.recordedAt ?? '');
		if (!Number.isNaN(existingRecordedAt) && !Number.isNaN(candidateRecordedAt)) {
			return candidateRecordedAt >= existingRecordedAt;
		}

		return true;
	}

	private webviewSnapshotRenderedAt(
		snapshot: Pick<Partial<WebviewSnapshotFile>, 'payload'>
	): number {
		const payload =
			typeof snapshot.payload === 'object' && snapshot.payload !== null
				? (snapshot.payload as Record<string, unknown>)
				: {};
		return Date.parse(String(payload.renderedAt ?? ''));
	}

	private async refreshState(): Promise<boolean> {
		try {
			this.model = await this.transport.load();
			this.hasAuthoritativeTransportState = true;
		} catch (error) {
			this.hasAuthoritativeTransportState = false;
			this.pushTransportError(
				error,
				'Orchestration state unavailable',
				'Failed to load orchestration state.'
			);
			return false;
		}

		this.postState();
		return true;
	}

	private async initializeResolvedWebview() {
		if (await this.refreshState()) {
			await this.submitTestWindowAutoPrompt();
		}
	}

	private async submitTestWindowAutoPrompt() {
		const prompt = testWindowAutoPrompt(this.context);
		if (!prompt || this.didSubmitTestWindowAutoPrompt) {
			return;
		}

		this.didSubmitTestWindowAutoPrompt = true;
		const requestId = `corgi-request:test-window:${randomUUID()}`;
		const action = testWindowAutoPromptAction(this.context);
		if (action === 'start_goal') {
			this.appendDevelopmentLog(`auto-start test goal: ${prompt}`);
			await this.applyAction(
				this.buildControllerAction({
					type: 'start_goal',
					text: prompt,
					request_id: requestId,
					auto_consume_executor: testWindowAutoStepMode(this.context) === 'execute',
				})
			);
			return;
		}
		this.appendDevelopmentLog(`auto-submit test prompt: ${prompt}`);
		await this.routeFreeText(prompt, requestId, false);
	}

	private async applyAction(
		action: ModelAction,
		options: { clearSemanticLoop?: boolean } = {}
	) {
		const previousModel = this.model;
		if (this.shouldApplyOptimisticExecutePlan(action)) {
			this.model = applyModelAction(this.model, action);
			this.postState();
		}
		try {
			this.model = await this.transport.dispatch(action);
			this.hasAuthoritativeTransportState = true;
		} catch (error) {
			this.model = previousModel;
			this.pushTransportError(
				error,
				'Orchestration action failed',
				'The orchestration action could not be applied.'
			);
			return;
		}

		if (options.clearSemanticLoop ?? true) {
			this.semanticLoopState = undefined;
		}
		this.postState();
	}

	private shouldApplyOptimisticExecutePlan(action: ModelAction): boolean {
		return Boolean(
			action.type === 'execute_plan' &&
				action.request_id &&
				this.model.planReadyRequest &&
				this.model.snapshot.currentStage === 'plan_ready' &&
				this.model.snapshot.permissionScope === 'plan' &&
				action.context_ref === this.model.planReadyRequest.contextRef
		);
	}

	private nextRequestId(): string {
		return `corgi-request:${randomUUID()}`;
	}

	private contextRefForAction(actionType: ModelAction['type']): string | undefined {
		switch (actionType) {
			case 'answer_clarification':
				return this.model.activeClarification?.contextRef;
			case 'set_permission_scope':
			case 'decline_permission':
				return this.model.snapshot.pendingPermissionRequest?.contextRef;
			case 'execute_plan':
			case 'revise_plan':
				return this.model.planReadyRequest?.contextRef;
			case 'interrupt_run':
				return this.model.snapshot.snapshotFreshness.receivedAt
					? `interrupt:${this.model.snapshot.snapshotFreshness.receivedAt}`
					: undefined;
			default:
				return undefined;
		}
	}

	private buildControllerAction(
		action: ModelAction,
		includeSessionRef = this.hasAuthoritativeTransportState
	): ModelAction {
		return {
			...action,
			request_id: action.request_id ?? this.nextRequestId(),
			context_ref: action.context_ref ?? this.contextRefForAction(action.type),
			session_ref:
				action.session_ref ??
				(action.type !== 'submit_prompt' && includeSessionRef
					? this.model.snapshot.sessionRef
					: undefined),
		};
	}

	private buildExecutePlanAction(requestId?: string): ModelAction {
		return {
			type: 'execute_plan',
			request_id: requestId,
			session_ref: this.model.snapshot.sessionRef,
			context_ref: this.model.planReadyRequest?.contextRef,
		};
	}

	private buildRevisePlanAction(text: string, requestId?: string): ModelAction {
		return {
			type: 'revise_plan',
			text,
			request_id: requestId,
			session_ref: this.model.snapshot.sessionRef,
			context_ref: this.model.planReadyRequest?.contextRef,
		};
	}

	private semanticDisambiguationCopy(
		loopState: SemanticLoopState
	): { title: string; body: string } {
		const exhausted = loopState.exhausted;
		if (this.model.activeClarification) {
			return {
				title: 'Need a clearer clarification answer',
				body: exhausted
					? 'I still need a direct answer to the current clarification. Answer it in one short phrase, or choose one of the listed options.'
					: 'Please answer the current clarification directly, or choose one of the listed options.',
			};
		}

		if (this.model.snapshot.pendingPermissionRequest) {
			return {
				title: 'Need a clearer request',
				body: exhausted
					? 'Please either choose a permission scope with the buttons, or ask a progress question.'
					: 'I’m not sure whether this is a follow-up question or a new request while a permission choice is still pending. Please either choose a permission scope or ask a progress question.',
			};
		}

		if (this.model.snapshot.runState === 'running') {
			return {
				title: 'Need a clearer request',
				body: exhausted
					? 'Please restate this as exactly one of: stop, a progress question, or a new work request.'
					: 'I’m not sure whether this is a stop request, a progress question, or a new work request. Please restate it more directly.',
			};
		}

		return {
			title: exhausted ? 'Still need a clearer request' : 'Need a clearer request',
			body: exhausted
				? 'I still couldn’t route that safely. Please restate it as exactly one of: ask for progress, or give a new work request.'
				: 'I’m not sure whether this is a new work request or a read-only question. Please restate it more directly.',
		};
	}

	private semanticBlockCopy(
		blockKind: SemanticBlockKind,
		loopState: SemanticLoopState
	): { title: string; body: string } {
		switch (blockKind) {
			case 'semantic_unavailable':
				return {
					title: 'Couldn’t classify request right now',
					body: 'Corgi couldn’t classify that request right now. Please try again, or restate it more directly.',
				};
			case 'control_unmappable':
				return {
					title: 'Need a clearer control request',
					body: 'I couldn’t map that control request safely. Please restate it as stop, a progress question, or a new work request.',
				};
			case 'nothing_running':
				return {
					title: 'Nothing is running right now',
					body: 'Ask for progress, or send a new work request instead.',
				};
			case 'interrupt_pending':
				return {
					title: 'Stop already requested',
					body: 'A stop request is already pending. Wait for orchestration to handle it before asking again.',
				};
			case 'no_active_clarification':
				return {
					title: 'No clarification is active',
					body: 'There is no active clarification to answer right now. Ask for progress or send a new work request instead.',
				};
			case 'needs_disambiguation':
				return this.semanticDisambiguationCopy(loopState);
		}
	}

	private semanticPresentationKey(blockKind: SemanticBlockKind): string {
		switch (blockKind) {
			case 'semantic_unavailable':
				return 'semantic.unavailable';
			case 'control_unmappable':
				return 'semantic.control_unmappable';
			case 'nothing_running':
				return 'semantic.nothing_running';
			case 'interrupt_pending':
				return 'semantic.interrupt_pending';
			case 'no_active_clarification':
				return 'semantic.no_active_clarification';
			case 'needs_disambiguation':
				return 'semantic.needs_clearer_request';
		}
	}

	private async routeFreeText(
		text: string,
		requestId?: string,
		includeSessionRef = this.hasAuthoritativeTransportState
	) {
		const rawText = text.trim();
		if (!rawText) {
			return;
		}

		if (semanticMode() === 'governor-first') {
			await this.applyAction(
				this.buildControllerAction({
					type: 'submit_prompt',
					text: rawText,
					request_id: requestId,
					semantic_mode: 'governor-first',
				}, includeSessionRef)
			);
			return;
		}

		let resolution;
		try {
			resolution = await this.semanticSidecar.route(
				rawText,
				this.model,
				this.semanticLoopState
			);
		} catch (error) {
			this.pushLocalError(
				'Couldn’t classify request right now',
				'Corgi couldn’t classify that request right now. Please try again, or restate it more directly.'
			);
			return;
		}

		if (resolution.kind === 'block') {
			this.semanticLoopState = resolution.nextLoopState;
			const presentation = this.semanticBlockCopy(
				resolution.blockKind,
				resolution.nextLoopState
			);
			this.model = appendControllerSemanticClarification(
				this.model,
				rawText,
				presentation.title,
				presentation.body,
				resolution.semantic,
				undefined,
				requestId,
				this.semanticPresentationKey(resolution.blockKind)
			);
			this.postState();
			return;
		}

		await this.applyAction(
			this.buildControllerAction({
				...resolution.action,
				request_id: requestId ?? resolution.action.request_id,
			}, includeSessionRef)
		);
	}

	private async handleMessage(message: WebviewMessage) {
		switch (message.type) {
			case 'ready':
				await this.refreshState();
				return;
			case 'refresh_state':
				await this.refreshState();
				return;
			case 'webview_snapshot':
				this.writeWebviewSnapshot(message.payload);
				return;
			case 'submit_prompt':
				await this.routeFreeText(
					message.text ?? '',
					message.requestId,
					this.hasAuthoritativeTransportState
				);
				return;
			case 'start_goal':
				await this.applyAction(
					this.buildControllerAction({
						type: 'start_goal',
						text: message.text ?? '',
						request_id: message.requestId,
					})
				);
				return;
			case 'execute_plan':
				await this.applyAction(
					this.buildControllerAction(
						this.buildExecutePlanAction(message.requestId),
						true
					)
				);
				return;
			case 'revise_plan':
				await this.applyAction(
					this.buildControllerAction(
						this.buildRevisePlanAction(message.text ?? '', message.requestId),
						true
					)
				);
				return;
			case 'answer_clarification':
				await this.applyAction(this.buildControllerAction({
					type: 'answer_clarification',
					text: message.text ?? '',
					request_id: message.requestId,
				}));
				return;
			case 'set_permission_scope':
				if (!message.permissionScope) {
					return;
				}
				await this.applyAction(this.buildControllerAction({
					type: 'set_permission_scope',
					permission_scope: message.permissionScope,
					request_id: message.requestId,
				}));
				return;
			case 'decline_permission':
				await this.applyAction(
					this.buildControllerAction({
						type: 'decline_permission',
						request_id: message.requestId,
					})
				);
				return;
			case 'interrupt_run':
				await this.applyAction(
					this.buildControllerAction({
						type: 'interrupt_run',
						request_id: message.requestId,
					})
				);
				return;
			case 'open_artifact':
				await this.handleArtifactAction(message.artifactId, 'open');
				return;
			case 'reveal_artifact_path':
				await this.handleArtifactAction(message.artifactId, 'reveal');
				return;
			case 'copy_artifact_path':
				await this.handleArtifactAction(message.artifactId, 'copy');
				return;
		}
	}

	private async handleArtifactAction(
		artifactId: string | undefined,
		action: 'open' | 'reveal' | 'copy'
	) {
		if (!artifactId) {
			this.pushLocalError(
				'Artifact unavailable',
				'The requested artifact action did not include an artifact identifier.'
			);
			return;
		}

		const artifact =
			getArtifactById(this.model, artifactId) ??
			this.resolveArtifactByPath(artifactId);
		if (!artifact) {
			this.pushLocalError(
				'Artifact unavailable',
				`The artifact "${artifactId}" could not be found in the current Corgi state.`
			);
			return;
		}

		const artifactUri = this.resolveArtifactUri(artifact.path);
		if (!artifactUri) {
			this.pushLocalError(
				'Workspace root unavailable',
				'Artifact path actions need an open workspace folder.'
			);
			return;
		}

		try {
			await vscode.workspace.fs.stat(artifactUri);
		} catch {
			this.pushLocalError(
				'Artifact path missing',
				`The artifact path "${artifact.path}" does not exist in the current workspace.`
			);
			return;
		}

		switch (action) {
			case 'open':
				await vscode.window.showTextDocument(artifactUri, {
					preview: false,
				});
				return;
			case 'reveal':
				await vscode.commands.executeCommand('revealFileInOS', artifactUri);
				return;
			case 'copy':
				await vscode.env.clipboard.writeText(artifactUri.fsPath);
				vscode.window.setStatusBarMessage(`Copied ${artifact.path}`, 2000);
				return;
		}
	}

	private resolveArtifactUri(relativePath: string): vscode.Uri | undefined {
		if (!this.workspaceRoot) {
			return undefined;
		}

		return vscode.Uri.joinPath(this.workspaceRoot, relativePath);
	}

	private resolveArtifactByPath(relativePath: string) {
		for (const artifact of this.model.snapshot.recentArtifacts) {
			if (artifact.path === relativePath) {
				return artifact;
			}
		}

		for (const item of this.model.feed) {
			if (
				item.type === 'artifact_reference' &&
				item.artifact.path === relativePath
			) {
				return item.artifact;
			}
		}

		return undefined;
	}

	private pushLocalError(title: string, body: string, details?: string[]) {
		this.model = appendError(this.model, title, body, details);
		this.postState();
	}

	private pushBlockingError(title: string, body: string, details?: string[]) {
		const baseModel = createInitialModel();
		this.model = {
			...baseModel,
			snapshot: {
				...baseModel.snapshot,
				currentActor: 'orchestration',
				currentStage: 'unavailable',
				transportState: 'disconnected',
				runState: 'idle',
				recentArtifacts: [],
				pendingPermissionRequest: undefined,
				pendingInterrupt: undefined,
			},
			feed: [],
			activeClarification: undefined,
			acceptedIntakeSummary: undefined,
		};
		this.model = appendError(this.model, title, body, details);
		this.postState();
	}

	private pushTransportError(
		error: unknown,
		fallbackTitle: string,
		fallbackBody: string
	) {
		if (error instanceof TransportUnavailableError) {
			this.pushBlockingError(error.title, error.message, error.details);
			return;
		}

		this.pushLocalError(
			fallbackTitle,
			fallbackBody
		);
	}

}
