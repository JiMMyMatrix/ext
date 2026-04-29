import { randomUUID } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { resolveOrchestrationStateRootPath } from './agentPaths';
import {
	appendError,
	appendControllerSemanticClarification,
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
} from './semanticSidecar';

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

type WebviewMessage =
	| { type: 'ready' }
	| { type: 'refresh_state' }
	| { type: 'webview_snapshot'; payload?: unknown }
	| { type: 'submit_prompt'; text?: string; requestId?: string }
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
		this.semanticSidecar = new SemanticSidecar();
	}

	public resolveWebviewView(webviewView: vscode.WebviewView) {
		this.disposeWebviewListeners();
		resetDevelopmentSessionState(this.context);
		this.view = webviewView;
		this.view.title = 'Corgi';
		this.view.webview.options = {
			enableScripts: true,
		};
		this.view.webview.html = getExecutionWindowHtml(
			this.view.webview.cspSource,
			getNonce(),
			shouldResetDevelopmentWebviewState(this.context)
		);
		this.webviewDisposables.push(
			this.view.webview.onDidReceiveMessage((message) => {
				void this.handleMessage(message as WebviewMessage);
			})
		);
		void this.refreshState();
		this.transport.prewarm?.();
	}

	public async openView() {
		await vscode.commands.executeCommand(
			`workbench.view.extension.${EXECUTION_WINDOW_CONTAINER_ID}`
		);
		await vscode.commands.executeCommand(`${EXECUTION_WINDOW_VIEW_ID}.focus`);
	}

	public dispose() {
		this.disposeWebviewListeners();
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
			payload: this.model,
		});
	}

	private handleRuntimeEvent(event: ExecutionRuntimeEvent) {
		this.appendDevelopmentLog(
			`runtime ${event.stage}${event.elapsedMs !== undefined ? ` ${event.elapsedMs}ms` : ''}`
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

	private async refreshState() {
		try {
			this.model = await this.transport.load();
			this.hasAuthoritativeTransportState = true;
		} catch (error) {
			this.pushTransportError(
				error,
				'Orchestration state unavailable',
				'Failed to load orchestration state.'
			);
			return;
		}

		this.postState();
	}

	private async applyAction(
		action: ModelAction,
		options: { clearSemanticLoop?: boolean } = {}
	) {
		try {
			this.model = await this.transport.dispatch(action);
			this.hasAuthoritativeTransportState = true;
		} catch (error) {
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

export function getExecutionWindowHtml(
	cspSource: string,
	nonce: string = getNonce(),
	resetPersistedState: boolean = false
): string {
		return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; img-src ${cspSource} data:; style-src ${cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';"
	/>
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<title>Corgi</title>
	<style>
		:root {
			color-scheme: light dark;
			--bg: var(--vscode-sideBar-background, var(--vscode-editor-background));
			--panel: var(--vscode-input-background, rgba(127, 127, 127, 0.1));
			--panel-raised: var(--vscode-editorWidget-background, rgba(127, 127, 127, 0.14));
			--line: var(--vscode-sideBar-border, rgba(127, 127, 127, 0.22));
			--line-soft: rgba(127, 127, 127, 0.18);
			--text: var(--vscode-foreground);
			--muted: var(--vscode-descriptionForeground);
			--faint: rgba(127, 127, 127, 0.72);
			--accent: var(--vscode-focusBorder);
			--danger: var(--vscode-errorForeground);
			--success: var(--vscode-testing-iconPassed, #4ec27b);
			--warning: var(--vscode-editorWarning-foreground, #d6b84f);
		}

		* {
			box-sizing: border-box;
		}

		html,
		body {
			height: 100%;
			margin: 0;
			background: var(--bg);
			color: var(--text);
			font-family: var(--vscode-font-family);
			font-size: var(--vscode-font-size, 13px);
		}

		button,
		textarea {
			font: inherit;
		}

		[hidden] {
			display: none !important;
		}

		button {
			border: 1px solid transparent;
			border-radius: 10px;
			background: var(--vscode-button-background);
			color: var(--vscode-button-foreground);
			cursor: pointer;
			padding: 6px 10px;
		}

		button.secondary {
			background: var(--vscode-button-secondaryBackground, transparent);
			color: var(--vscode-button-secondaryForeground, var(--text));
			border-color: var(--line);
		}

		button.ghost {
			background: transparent;
			color: var(--muted);
			border-color: transparent;
			padding: 3px 6px;
		}

		button:hover {
			filter: brightness(1.06);
		}

		button:disabled {
			opacity: 0.55;
			cursor: default;
		}

		.app {
			height: 100%;
			display: flex;
			flex-direction: column;
			overflow: hidden;
			background: var(--bg);
		}

		.header {
			flex: 0 0 auto;
			padding: 10px 12px 8px;
			border-bottom: 1px solid var(--line);
		}

		.status-dot {
			width: 7px;
			height: 7px;
			border-radius: 50%;
			background: var(--success);
		}

		.status-dot.is-stale {
			background: var(--warning);
		}

		.status-dot.is-ready {
			background: var(--success);
		}

		.header-subline {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
			color: var(--muted);
			font-size: 11px;
		}

		.session-rail {
			flex: 0 0 auto;
			padding: 10px 12px 0;
			display: grid;
			gap: 8px;
		}

		.session-card {
			border: 1px solid var(--line);
			border-radius: 13px;
			background: var(--panel);
			padding: 10px;
			display: grid;
			gap: 8px;
		}

		.session-card.is-collapsed {
			padding: 8px 10px;
			gap: 6px;
		}

		.session-card-header {
			display: flex;
			align-items: flex-start;
			justify-content: space-between;
			gap: 8px;
		}

		.session-label {
			color: var(--muted);
			font-size: 11px;
			font-weight: 600;
			text-transform: uppercase;
			letter-spacing: 0.04em;
		}

		.session-title {
			margin: 2px 0 0;
			font-size: 13px;
			font-weight: 600;
			line-height: 1.4;
		}

		.session-summary {
			color: var(--muted);
			font-size: 12px;
			line-height: 1.45;
		}

		.session-card.is-collapsed .session-summary {
			font-size: 11px;
			line-height: 1.35;
		}

		.session-grid {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: 8px 12px;
		}

		.session-field {
			display: grid;
			gap: 2px;
			min-width: 0;
		}

		.session-field-label {
			color: var(--muted);
			font-size: 11px;
		}

		.session-field-value {
			font-size: 12px;
			line-height: 1.35;
			word-break: break-word;
		}

		.milestone-card {
			border: 1px solid var(--line-soft);
			border-radius: 12px;
			background: var(--panel-raised);
			padding: 9px 10px;
			display: grid;
			gap: 4px;
		}

		.milestone-title {
			font-size: 12px;
			font-weight: 600;
			line-height: 1.4;
		}

		.milestone-body {
			color: var(--muted);
			font-size: 12px;
			line-height: 1.45;
		}

		.pill-row {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
		}

		.pill {
			display: inline-flex;
			align-items: center;
			gap: 5px;
			padding: 3px 8px;
			border-radius: 999px;
			border: 1px solid var(--line);
			background: var(--panel-raised);
			color: var(--muted);
			font-size: 11px;
			line-height: 1.2;
			white-space: nowrap;
		}

		.pill.pill-reveal {
			max-width: min(100%, 28rem);
		}

		.pill-reveal-value {
			display: inline-block;
			max-width: 0;
			overflow: hidden;
			opacity: 0;
			transition: max-width 140ms ease, opacity 140ms ease;
			white-space: nowrap;
		}

		.pill.pill-reveal:hover .pill-reveal-value {
			max-width: 24rem;
			opacity: 1;
		}

		.pill.is-primary {
			color: var(--text);
			border-color: color-mix(in srgb, var(--accent) 50%, var(--line));
		}

		.pill.is-status {
			color: var(--text);
			border-color: color-mix(in srgb, var(--line) 75%, var(--accent));
			background: color-mix(in srgb, var(--panel-raised) 84%, var(--accent) 16%);
		}

		.pill.is-warning {
			color: var(--text);
			border-color: color-mix(in srgb, var(--warning) 45%, var(--line));
		}

		.pill.is-danger {
			color: var(--text);
			border-color: color-mix(in srgb, var(--danger) 45%, var(--line));
		}

		.feed {
			flex: 1 1 auto;
			overflow-y: auto;
			padding: 12px;
			display: flex;
			flex-direction: column;
			gap: 10px;
			min-height: 120px;
		}

		.message {
			display: grid;
			gap: 5px;
			line-height: 1.45;
		}

		.message-label {
			color: var(--muted);
			font-size: 11px;
			font-weight: 600;
		}

		.message-body {
			white-space: pre-wrap;
			word-break: break-word;
		}

		.message.user {
			align-self: flex-end;
			max-width: 92%;
			border: 1px solid var(--line);
			border-radius: 14px;
			background: var(--panel-raised);
			padding: 9px 10px;
		}

		.message.user .message-label {
			display: none;
		}

		.message.assistant {
			padding: 2px 0;
		}

		.message.error {
			border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
			border-radius: 12px;
			background: color-mix(in srgb, var(--danger) 10%, transparent);
			padding: 9px 10px;
		}

		.message.is-informational {
			color: var(--muted);
		}

		.activity-row {
			display: grid;
			grid-template-columns: 18px minmax(0, 1fr);
			gap: 8px;
			align-items: start;
			color: var(--muted);
			padding: 3px 0;
			line-height: 1.45;
		}

		.activity-dot {
			width: 8px;
			height: 8px;
			margin: 6px 0 0 5px;
			border-radius: 50%;
			background: var(--faint);
		}

		.activity-row.is-running .activity-dot {
			background: var(--accent);
			animation: pulse 1.5s ease-in-out infinite;
		}

		.activity-row.is-completed .activity-dot {
			background: var(--success);
		}

		.activity-row.is-failed .activity-dot,
		.activity-row.is-error .activity-dot {
			background: var(--danger);
		}

		.activity-label {
			color: var(--text);
			font-size: 12px;
		}

		.activity-row.is-informational .activity-label {
			color: var(--muted);
		}

		.activity-summary,
		.feed-empty,
		.composer-hint {
			color: var(--muted);
		}

		.activity-summary {
			margin-top: 2px;
			font-size: 12px;
		}

		.inline-actions,
		.card-actions {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
			align-items: center;
			margin-top: 6px;
		}

		.detail-list {
			margin: 7px 0 0;
			padding-left: 18px;
			color: var(--muted);
			display: grid;
			gap: 4px;
		}

		.detail-list li {
			line-height: 1.4;
		}

		.progress-cluster {
			align-self: flex-start;
			max-width: min(100%, 24rem);
			padding: 8px 10px;
			border-radius: 12px;
			background: transparent;
			border: 1px solid transparent;
		}

		.activity-trace {
			background: transparent;
			box-shadow: none;
			opacity: 0.96;
		}

		.progress-list {
			list-style: none;
			margin: 0;
			padding-left: 0;
			font-size: 12px;
			display: grid;
			gap: 4px;
		}

		.progress-cluster .activity-summary {
			margin-top: 6px;
			font-size: 11px;
		}

		.draft-preview {
			margin-top: 8px;
			max-width: min(100%, 46rem);
			color: var(--text);
			font-size: 13px;
			line-height: 1.55;
			opacity: 0.72;
			white-space: pre-wrap;
		}

		.draft-preview-label {
			margin-bottom: 4px;
			color: var(--muted);
			font-size: 11px;
			letter-spacing: 0.08em;
			text-transform: uppercase;
		}

		.progress-bullet {
			display: grid;
			grid-template-columns: 10px minmax(0, 1fr);
			align-items: center;
			gap: 8px;
			color: var(--muted);
		}

		.progress-bullet::before {
			content: '';
			width: 6px;
			height: 6px;
			border-radius: 50%;
			background: currentColor;
			transform: scale(0.95);
			opacity: 0.75;
		}

		.progress-bullet.is-done {
			color: var(--text);
		}

		.progress-bullet.is-active,
		.progress-bullet.is-waiting {
			color: var(--accent);
		}

		.progress-bullet-text {
			display: inline-block;
		}

		.progress-bullet.is-active .progress-bullet-text,
		.progress-bullet.is-waiting .progress-bullet-text {
			background-image: linear-gradient(
				90deg,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 0%,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 38%,
				var(--text) 50%,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 62%,
				color-mix(in srgb, var(--accent) 62%, var(--muted)) 100%
			);
			background-repeat: no-repeat;
			background-size: 360% 100%;
			background-position: 100% 50%;
			-webkit-background-clip: text;
			background-clip: text;
			color: transparent;
			animation: progressShimmer 3.4s cubic-bezier(0.42, 0, 0.2, 1) infinite;
		}

		.progress-bullet.is-failed {
			color: var(--danger);
		}

		.feed-divider {
			display: grid;
			grid-template-columns: 1fr auto 1fr;
			align-items: center;
			gap: 8px;
			margin: 6px 0 2px;
			color: var(--muted);
			font-size: 11px;
			text-transform: uppercase;
			letter-spacing: 0.04em;
		}

		.feed-divider::before,
		.feed-divider::after {
			content: '';
			height: 1px;
			background: var(--line);
		}

		.action-band {
			flex: 0 0 auto;
			padding: 8px 10px 0;
			display: grid;
			gap: 8px;
		}

		.action-card {
			padding: 10px;
			border: 1px solid var(--line);
			border-radius: 13px;
			background: var(--panel-raised);
			display: grid;
			gap: 6px;
		}

		.action-card-waiting {
			background: transparent;
			border-color: transparent;
			padding-left: 0;
			padding-right: 0;
		}

		.action-card h2 {
			margin: 0;
			font-size: 12px;
			font-weight: 600;
		}

		.action-card p {
			margin: 0;
			color: var(--muted);
			line-height: 1.45;
		}

		.footer {
			flex: 0 0 auto;
			padding: 10px;
			border-top: 1px solid var(--line);
			background: var(--bg);
		}

		.composer {
			border: 1px solid var(--line);
			border-radius: 14px;
			background: var(--panel);
			display: grid;
			gap: 8px;
			padding: 8px;
		}

		.composer-context {
			display: flex;
			flex-wrap: wrap;
			gap: 6px;
		}

		textarea {
			width: 100%;
			min-height: 42px;
			max-height: 128px;
			resize: vertical;
			border: 0;
			outline: none;
			padding: 0;
			background: transparent;
			color: var(--text);
			line-height: 1.45;
		}

		textarea::placeholder {
			color: var(--muted);
		}

		.composer-footer {
			display: flex;
			justify-content: space-between;
			align-items: center;
			gap: 8px;
		}

		.composer-hint {
			font-size: 11px;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}

		#composerSubmitButton {
			min-width: 54px;
			padding: 5px 10px;
			border-radius: 999px;
		}

		.loading {
			height: 100%;
			display: grid;
			place-items: center;
			color: var(--muted);
		}

		@keyframes pulse {
			50% {
				opacity: 0.45;
			}
		}

		@keyframes progressShimmer {
			0% {
				background-position: 100% 50%;
			}
			16% {
				background-position: 100% 50%;
			}
			84% {
				background-position: 0% 50%;
			}
			100% {
				background-position: 0% 50%;
			}
		}

		@media (max-width: 340px) {
			.session-grid {
				grid-template-columns: minmax(0, 1fr);
			}
		}
	</style>
</head>
<body>
	<div class="app" id="app" hidden>
		<header class="header">
			<div id="headerContent"></div>
		</header>
		<main class="feed" id="feed"></main>
		<section class="action-band" id="actionBand" hidden></section>
		<footer class="footer">
			<form class="composer" id="composerForm">
				<div class="composer-context" id="composerContext" hidden></div>
				<textarea
					id="composerInput"
					placeholder="Ask Corgi to work on this repo..."
				></textarea>
				<div class="composer-footer">
					<div class="composer-hint" id="composerHint">Enter to send, Shift+Enter for newline</div>
					<button type="submit" id="composerSubmitButton">Send</button>
				</div>
			</form>
		</footer>
	</div>
	<div class="loading" id="loadingState">Loading Corgi...</div>
	<script nonce="${nonce}">
		const vscode = acquireVsCodeApi();
		const shouldResetPersistedState = ${resetPersistedState ? 'true' : 'false'};
		const defaultPersistedState = {
			draft: '',
			expandedIds: [],
			scrollTop: 0,
			initialFeedCount: undefined,
			promptHistory: [],
		};
		if (shouldResetPersistedState) {
			vscode.setState(defaultPersistedState);
		}
		const persisted = shouldResetPersistedState
			? defaultPersistedState
			: (vscode.getState() ?? defaultPersistedState);

		let model = undefined;
		let hasRendered = false;
		let monitorSnapshotTimer = undefined;
		let draftPreviewTimer = undefined;
		let governorWaitTimers = [];
		const ui = {
			draft: typeof persisted.draft === 'string' ? persisted.draft : '',
			expandedIds: new Set(Array.isArray(persisted.expandedIds) ? persisted.expandedIds : []),
			scrollTop: typeof persisted.scrollTop === 'number' ? persisted.scrollTop : 0,
			initialFeedCount:
				typeof persisted.initialFeedCount === 'number'
					? persisted.initialFeedCount
					: undefined,
			promptHistory: Array.isArray(persisted.promptHistory)
				? persisted.promptHistory.filter((entry) => typeof entry === 'string' && entry.trim().length > 0)
				: [],
			historyIndex: undefined,
			historyDraft: '',
			foregroundRequest: undefined,
			pendingPermissionContextRef: undefined,
			pendingPermissionHiddenAt: undefined,
			pendingPlanContextRef: undefined,
			pendingPlanHiddenAt: undefined,
			planRevisionMode: false,
		};

		const app = document.getElementById('app');
		const loadingState = document.getElementById('loadingState');
		const headerContent = document.getElementById('headerContent');
		const feed = document.getElementById('feed');
		const actionBand = document.getElementById('actionBand');
		const composerForm = document.getElementById('composerForm');
		const composerContext = document.getElementById('composerContext');
		const composerInput = document.getElementById('composerInput');
		const composerHint = document.getElementById('composerHint');
		const composerSubmitButton = document.getElementById('composerSubmitButton');

		function persistUiState() {
			vscode.setState({
				draft: ui.draft,
				expandedIds: Array.from(ui.expandedIds),
				scrollTop: feed.scrollTop,
				initialFeedCount: ui.initialFeedCount,
				promptHistory: ui.promptHistory.slice(-50),
			});
		}

		function compactText(value, limit) {
			const text = String(value || '').replace(/\\s+/g, ' ').trim();
			if (text.length <= limit) {
				return text;
			}
			return text.slice(0, limit - 3) + '...';
		}

		function collectTextRows(root, selector, limit) {
			const rows = Array.from(root.querySelectorAll(selector))
				.map((element) => ({
					className: compactText(element.className || '', 160),
					text: compactText(element.innerText || element.textContent || '', 2000),
				}))
				.filter((entry) => entry.text.length > 0);
			return typeof limit === 'number' ? rows.slice(-limit) : rows;
		}

		function cloneForSnapshot(value) {
			if (value === undefined) {
				return null;
			}
			try {
				return JSON.parse(JSON.stringify(value));
			} catch {
				return String(value);
			}
		}

		function collectWebviewSnapshot(reason) {
			const snapshot = model?.snapshot ?? {};
			const feedItems = Array.isArray(model?.feed) ? model.feed : [];
			return {
				reason,
				renderedAt: new Date().toISOString(),
				header: compactText(headerContent.innerText || headerContent.textContent || '', 600),
				state: {
					currentActor: snapshot.currentActor || '',
					currentStage: snapshot.currentStage || '',
					permissionScope: snapshot.permissionScope || '',
					runState: snapshot.runState || '',
					transportState: snapshot.transportState || '',
					task: snapshot.task || '',
					activeForegroundRequestId: model?.activeForegroundRequestId || '',
					planReadyRequestId: model?.planReadyRequest?.id || '',
					feedCount: Array.isArray(model?.feed) ? model.feed.length : 0,
				},
				blocking: {
					activeClarification: cloneForSnapshot(model?.activeClarification),
					pendingPermissionRequest: cloneForSnapshot(snapshot.pendingPermissionRequest),
					pendingInterrupt: cloneForSnapshot(snapshot.pendingInterrupt),
					planReadyRequest: cloneForSnapshot(model?.planReadyRequest),
					pendingPermissionContextRef: ui.pendingPermissionContextRef || null,
					pendingPlanContextRef: ui.pendingPlanContextRef || null,
				},
				actions: collectTextRows(actionBand, '.action-card'),
				messages: collectTextRows(feed, '.message, .activity-row, .turn-divider, .feed-empty'),
				progress: collectTextRows(feed, '.progress-bullet, .activity-summary'),
				composer: {
					placeholder: compactText(composerInput.placeholder, 240),
					hint: compactText(composerHint.innerText || composerHint.textContent || '', 300),
					button: compactText(composerSubmitButton.innerText || composerSubmitButton.textContent || '', 120),
					disabled: Boolean(composerInput.disabled),
					context: compactText(composerContext.innerText || composerContext.textContent || '', 300),
					draftLength: ui.draft.length,
				},
				model: {
					snapshot: cloneForSnapshot(snapshot),
					activeForegroundRequestId: model?.activeForegroundRequestId || null,
					planReadyRequest: cloneForSnapshot(model?.planReadyRequest),
					activeClarification: cloneForSnapshot(model?.activeClarification),
					feed: cloneForSnapshot(feedItems),
					feedCount: feedItems.length,
					uiForegroundRequest: cloneForSnapshot(ui.foregroundRequest),
				},
				scroll: {
					top: feed.scrollTop,
					height: feed.scrollHeight,
					clientHeight: feed.clientHeight,
				},
			};
		}

		function scheduleWebviewSnapshot(reason) {
			clearTimeout(monitorSnapshotTimer);
			monitorSnapshotTimer = setTimeout(() => {
				vscode.postMessage({
					type: 'webview_snapshot',
					payload: collectWebviewSnapshot(reason),
				});
			}, 80);
		}

		function renderRevealPill(label, value, className) {
			if (!value) {
				return '';
			}
			const classes = ['pill', 'pill-reveal'];
			if (className) {
				classes.push(className);
			}
			return (
				'<span class="' + classes.join(' ') + '" title="' + escapeHtml(label + ': ' + value) + '">' +
					'<span class="pill-reveal-label">' + escapeHtml(label) + '</span>' +
					'<span class="pill-reveal-value">: ' + escapeHtml(value) + '</span>' +
				'</span>'
			);
		}

		function rememberPrompt(text) {
			const trimmed = text.trim();
			if (!trimmed) {
				return;
			}
			if (ui.promptHistory[ui.promptHistory.length - 1] !== trimmed) {
				ui.promptHistory = ui.promptHistory.concat(trimmed).slice(-50);
			}
		}

		function resetPromptHistoryNavigation() {
			ui.historyIndex = undefined;
			ui.historyDraft = '';
		}

		function navigatePromptHistory(direction) {
			if (!ui.promptHistory.length) {
				return false;
			}

			if (direction === 'up') {
				if (ui.historyIndex === undefined) {
					ui.historyDraft = ui.draft;
					ui.historyIndex = ui.promptHistory.length - 1;
				} else if (ui.historyIndex > 0) {
					ui.historyIndex -= 1;
				}
				ui.draft = ui.promptHistory[ui.historyIndex] ?? ui.draft;
			} else {
				if (ui.historyIndex === undefined) {
					return false;
				}
				if (ui.historyIndex < ui.promptHistory.length - 1) {
					ui.historyIndex += 1;
					ui.draft = ui.promptHistory[ui.historyIndex] ?? ui.draft;
				} else {
					ui.draft = ui.historyDraft;
					resetPromptHistoryNavigation();
				}
			}

			persistUiState();
			renderComposer();
			const end = composerInput.value.length;
			composerInput.setSelectionRange(end, end);
			return true;
		}

		function escapeHtml(value) {
			return String(value)
				.replace(/&/g, '&amp;')
				.replace(/</g, '&lt;')
				.replace(/>/g, '&gt;')
				.replace(/"/g, '&quot;')
				.replace(/'/g, '&#39;');
		}

		function isSnapshotStale(snapshot) {
			if (snapshot.snapshotFreshness?.stale) {
				return true;
			}

			const receivedAt = Date.parse(snapshot.snapshotFreshness?.receivedAt ?? '');
			if (Number.isNaN(receivedAt)) {
				return false;
			}

			return Date.now() - receivedAt > 45000;
		}

		function canStop(snapshot) {
			if (snapshot.pendingInterrupt) {
				return false;
			}

			return snapshot.runState === 'running';
		}

		function retainOptimisticHidesUntilAuthoritativeChange() {
			// Same-context action surfaces should not reappear on a timer after
			// the user clicks them. They clear only when authoritative state
			// removes or replaces that context.
		}

		function isPlanReady(snapshot) {
			return Boolean(
				model?.planReadyRequest &&
					snapshot.currentStage === 'plan_ready' &&
					snapshot.permissionScope === 'plan' &&
					!snapshot.pendingPermissionRequest &&
					!model?.activeClarification &&
					!snapshot.pendingInterrupt &&
					snapshot.runState !== 'running'
			);
		}

		function statusLabel(snapshot, stale) {
			if (snapshot.pendingInterrupt) {
				return 'Stop pending';
			}
			if (snapshot.pendingPermissionRequest) {
				return 'Permission needed';
			}
			if (model?.activeClarification) {
				return 'Needs input';
			}
			if (snapshot.runState === 'running') {
				return 'Running';
			}
			if (
				snapshot.transportState === 'connected' &&
				isPlanReady(snapshot)
			) {
				return 'Plan ready';
			}
			if (snapshot.transportState === 'connected' && !stale) {
				return 'Ready';
			}
			return 'Attention';
		}

		function statusDotClass(snapshot, stale) {
			if (
				snapshot.transportState === 'connected' &&
				isPlanReady(snapshot)
			) {
				return 'is-ready';
			}
			return stale ? 'is-stale' : '';
		}

		function railTitle(snapshot) {
			if (snapshot.task) {
				return snapshot.task;
			}
			if (model?.acceptedIntakeSummary?.body) {
				return model.acceptedIntakeSummary.body;
			}
			return 'Nothing active yet';
		}

		function railSummary(snapshot) {
			if (model?.activeClarification) {
				return 'One quick clarification will get this moving.';
			}
			if (snapshot.pendingPermissionRequest) {
				return 'Waiting for your permission choice before Corgi can continue.';
			}
			if (snapshot.pendingInterrupt) {
				return snapshot.pendingInterrupt.body;
			}
			if (snapshot.runState === 'running') {
				return 'Corgi is working on the current request.';
			}
			if (model?.acceptedIntakeSummary?.body) {
				return model.acceptedIntakeSummary.body;
			}
			return 'Start with a concrete task, or ask what is happening.';
		}

		function summarizeToken(value, fallback) {
			if (!value) {
				return fallback;
			}

			return String(value)
				.replace(/[_-]+/g, ' ')
				.replace(/\s+/g, ' ')
				.trim()
				.replace(/\b\w/g, (char) => char.toUpperCase());
		}

		function actorSummary(snapshot) {
			const actor = snapshot.currentActor;
			if (!actor) {
				return '';
			}

			if (actor === 'intake_shell') {
				return 'Intake';
			}

			return summarizeToken(actor, '');
		}

		function stageSummary(snapshot) {
			return summarizeToken(snapshot.currentStage, '');
		}

		function isMeaningfulMilestone(item) {
			if (!item || !item.authoritative) {
				return false;
			}

			if (
				item.type === 'clarification_request' ||
				item.type === 'permission_request' ||
				item.type === 'interrupt_request' ||
				item.type === 'error'
			) {
				return true;
			}

			if (item.type === 'system_status') {
				return item.title !== 'Ready when you are';
			}

			return false;
		}

		function latestMeaningfulMilestone() {
			if (!model) {
				return undefined;
			}

			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (isMeaningfulMilestone(item)) {
					return item;
				}
			}

			return undefined;
		}

		function shouldRenderInTranscript(item) {
			if (item.type === 'artifact_reference' || item.type === 'shell_event') {
				return false;
			}
			if (item.type === 'permission_request') {
				return Boolean(
					model?.snapshot.pendingPermissionRequest &&
					item.body === model.snapshot.pendingPermissionRequest.body
				);
			}
			if (item.type === 'clarification_request') {
				return Boolean(
					model?.activeClarification &&
					item.body === model.activeClarification.body
				);
			}
			if (item.type === 'system_status' && !isMeaningfulMilestone(item)) {
				return false;
			}
			return true;
		}

		function milestoneArtifact(item) {
			if (!model || !item?.source_artifact_ref) {
				return undefined;
			}

			return (
				model.snapshot.recentArtifacts.find(
					(artifact) => artifact.path === item.source_artifact_ref
				) ??
				model.feed.find(
					(entry) =>
						entry.type === 'artifact_reference' &&
						entry.artifact.path === item.source_artifact_ref
				)?.artifact
			);
		}

		function fallbackAcceptedArtifact() {
			if (!model) {
				return undefined;
			}

			return model.snapshot.recentArtifacts.find(
				(artifact) => artifact.authoritative
			);
		}

		function currentQuickArtifact() {
			const milestone = latestMeaningfulMilestone();
			return milestoneArtifact(milestone) ?? fallbackAcceptedArtifact();
		}

		function renderArtifactQuickAction(artifact) {
			if (!artifact) {
				return '';
			}

			return (
				'<div class="card-actions">' +
					'<button type="button" class="secondary" data-action="open_artifact" data-artifact-id="' +
					escapeHtml(artifact.id || artifact.path) +
					'">View source</button>' +
				'</div>'
			);
		}

		function renderContextChips(snapshot, limit) {
			const chips = [];
			if (model?.activeClarification) {
				chips.push('<span class="pill is-warning">Clarification</span>');
			}
			if (snapshot.pendingPermissionRequest) {
				chips.push('<span class="pill is-warning">Permission</span>');
			}
			if (snapshot.permissionScope && snapshot.permissionScope !== 'unset') {
				chips.push(
					'<span class="pill is-status">Scope: ' +
						escapeHtml(snapshot.permissionScope.charAt(0).toUpperCase() + snapshot.permissionScope.slice(1)) +
					'</span>'
				);
			}
			if (snapshot.pendingInterrupt) {
				chips.push('<span class="pill is-danger">Stop pending</span>');
			} else if (snapshot.runState === 'running') {
				chips.push('<span class="pill is-primary">Running</span>');
			}
			if (typeof limit !== 'number' || limit < 0 || chips.length <= limit) {
				return chips.join('');
			}
			return (
				chips.slice(0, limit).join('') +
				'<span class="pill">+' + String(chips.length - limit) + '</span>'
			);
		}

		function bulletId() {
			return 'bullet-' + String(Date.now()) + '-' + Math.random().toString(36).slice(2, 8);
		}

		function trimForegroundBullets() {
			if (!ui.foregroundRequest || !Array.isArray(ui.foregroundRequest.bullets)) {
				return;
			}
			ui.foregroundRequest.bullets = ui.foregroundRequest.bullets.slice(-3);
		}

		function nextForegroundRequestKey() {
			return 'corgi-request:' + String(Date.now()) + ':' + Math.random().toString(36).slice(2, 8);
		}

		function isAuthoritativeForegroundRequestKey(requestKey) {
			return Boolean(requestKey && String(requestKey).startsWith('corgi-request:'));
		}

		function foregroundRequestKeyForAction(action) {
			if (
				(action === 'set_permission_scope' || action === 'decline_permission') &&
				model?.snapshot?.pendingPermissionRequest?.foregroundRequestId
			) {
				return model.snapshot.pendingPermissionRequest.foregroundRequestId;
			}
			if (action === 'interrupt_run' && model?.activeForegroundRequestId) {
				return model.activeForegroundRequestId;
			}
			if (ui.foregroundRequest?.requestKey) {
				return ui.foregroundRequest.requestKey;
			}
			if (model?.activeForegroundRequestId) {
				return model.activeForegroundRequestId;
			}
			return nextForegroundRequestKey();
		}

		function startForegroundRequest(userText, hint, requestKey) {
			clearDraftPreviewTimer();
			clearGovernorWaitTimers();
			ui.foregroundRequest = {
				id: 'foreground-' + String(Date.now()),
				requestKey: requestKey || nextForegroundRequestKey(),
				userText: userText || '',
				status: 'live',
				hint: hint || '',
				draftPreview: '',
				draftPreviewTarget: '',
				bullets: [],
			};
		}

		function clearDraftPreviewTimer() {
			if (draftPreviewTimer) {
				clearTimeout(draftPreviewTimer);
				draftPreviewTimer = undefined;
			}
		}

		function clearGovernorWaitTimers() {
			for (const timer of governorWaitTimers) {
				clearTimeout(timer);
			}
			governorWaitTimers = [];
		}

		function clearForegroundRequest() {
			clearDraftPreviewTimer();
			clearGovernorWaitTimers();
			ui.foregroundRequest = undefined;
		}

		function resetDraftPreview() {
			clearDraftPreviewTimer();
			if (!ui.foregroundRequest) {
				return;
			}
			ui.foregroundRequest.draftPreview = '';
			ui.foregroundRequest.draftPreviewTarget = '';
		}

		function nextDraftPreviewSlice(current, target) {
			const normalizedCurrent = target.startsWith(current) ? current : '';
			const remaining = target.slice(normalizedCurrent.length);
			const nextWord = remaining.match(/^\\s*\\S+\\s*/);
			if (!nextWord) {
				return target;
			}
			return normalizedCurrent + nextWord[0];
		}

		function scheduleDraftPreviewTyping() {
			if (draftPreviewTimer || !ui.foregroundRequest) {
				return;
			}
			draftPreviewTimer = setTimeout(() => {
				draftPreviewTimer = undefined;
				if (!ui.foregroundRequest) {
					return;
				}
				const target = String(ui.foregroundRequest.draftPreviewTarget || '');
				const current = String(ui.foregroundRequest.draftPreview || '');
				if (!target || current === target) {
					return;
				}
				ui.foregroundRequest.draftPreview = nextDraftPreviewSlice(current, target);
				renderFeed();
				scheduleWebviewSnapshot('draft_preview_type');
				if (ui.foregroundRequest.draftPreview !== target) {
					scheduleDraftPreviewTyping();
				}
			}, 55);
		}

		function setDraftPreviewTarget(value) {
			if (!ui.foregroundRequest) {
				return;
			}
			const target = String(value || '').trim();
			if (!target) {
				resetDraftPreview();
				return;
			}
			if (!target.startsWith(String(ui.foregroundRequest.draftPreview || ''))) {
				ui.foregroundRequest.draftPreview = '';
			}
			ui.foregroundRequest.draftPreviewTarget = target;
			scheduleDraftPreviewTyping();
		}

		function scheduleGovernorWaitHeartbeat(event) {
			clearGovernorWaitTimers();
			const requestKey = event?.requestId;
			const runtimeRequestId = event?.runtimeRequestId || '';
			if (!requestKey) {
				return;
			}
			const isSemanticIntake = event.runtimeKind === 'semantic_intake';
			const beats = isSemanticIntake
				? [
					[12000, 'Still interpreting the request', 'Governor is still interpreting the request...'],
					[30000, 'Still checking intent and workflow state', 'Governor is still checking intent and workflow state...'],
				]
				: [
					[12000, 'Still waiting for the Governor', 'Still waiting for a reply from the Governor...'],
					[30000, 'Governor is still thinking', 'Governor is still thinking through the plan...'],
					[60000, 'Governor is taking a deeper pass', 'The Governor is still working. This model can take a little longer.'],
				];
			governorWaitTimers = beats.map(([delay, label, hint]) =>
				setTimeout(() => {
					if (
						!ui.foregroundRequest ||
						ui.foregroundRequest.requestKey !== requestKey ||
						ui.foregroundRequest.status !== 'live' ||
						(runtimeRequestId && ui.foregroundRequest.runtimeRequestId !== runtimeRequestId) ||
						ui.foregroundRequest.draftPreviewTarget ||
						latestRequestActorEvent(requestKey) ||
						latestRequestError(requestKey)
					) {
						return;
					}
					replaceForegroundTail(label, 'active', hint);
					persistUiState();
					renderFeed();
					renderComposer();
					scheduleWebviewSnapshot('governor_wait_heartbeat');
				}, delay)
			);
		}

		function authoritativePermissionContextRef() {
			return model?.snapshot?.pendingPermissionRequest?.contextRef;
		}

		function authoritativePlanContextRef() {
			return model?.planReadyRequest?.contextRef;
		}

		function ensureForegroundRequest(userText, hint, requestKey) {
			if (!ui.foregroundRequest) {
				startForegroundRequest(userText, hint, requestKey);
				return;
			}
			if (requestKey) {
				ui.foregroundRequest.requestKey = requestKey;
			}
			if (userText) {
				ui.foregroundRequest.userText = userText;
			}
			if (hint) {
				ui.foregroundRequest.hint = hint;
			}
		}

		function latestForegroundUserTextFromModel(requestKey) {
			if (!model) {
				return '';
			}

			const matchesRequest = (item) =>
				item.type === 'user_message' &&
				item.turn_type !== 'permission_action' &&
				(!isAuthoritativeForegroundRequestKey(requestKey) ||
					item.in_response_to_request_id === requestKey);

			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (matchesRequest(item)) {
					return item.body || item.title || '';
				}
			}

			return '';
		}

		function appendForegroundBullet(label, state, hint) {
			ensureForegroundRequest('', hint);
			const bullets = ui.foregroundRequest.bullets;
			const previous = bullets[bullets.length - 1];
			if (previous && previous.state === 'active') {
				previous.state = 'done';
			}
			bullets.push({
				id: bulletId(),
				label,
				state: state || 'active',
			});
			trimForegroundBullets();
			if (hint) {
				ui.foregroundRequest.hint = hint;
			}
			if ((state || '').toString() === 'failed') {
				resetDraftPreview();
			}
		}

		function replaceForegroundTail(label, state, hint) {
			ensureForegroundRequest('', hint);
			const bullets = ui.foregroundRequest.bullets;
			if (bullets.length === 0) {
				bullets.push({ id: bulletId(), label, state: state || 'active' });
			} else {
				bullets[bullets.length - 1] = {
					...bullets[bullets.length - 1],
					label,
					state: state || bullets[bullets.length - 1].state,
				};
			}
			trimForegroundBullets();
			if (hint) {
				ui.foregroundRequest.hint = hint;
			}
			if ((state || '').toString() === 'failed') {
				resetDraftPreview();
			}
		}

		function setForegroundSingleBullet(label, state, hint) {
			ensureForegroundRequest('', hint);
			ui.foregroundRequest.bullets = [
				{
					id: bulletId(),
					label,
					state: state || 'active',
				},
			];
			ui.foregroundRequest.status = 'live';
			ui.foregroundRequest.hint = hint || label;
		}

		function foregroundRequestIsLive(requestKey) {
			return Boolean(
				ui.foregroundRequest &&
					ui.foregroundRequest.status === 'live' &&
					ui.foregroundRequest.requestKey === requestKey
			);
		}

		function foregroundRequestCanReceiveTrace(requestKey) {
			if (!foregroundRequestIsLive(requestKey)) {
				return false;
			}
			if (!model) {
				return true;
			}
			const snapshot = model.snapshot;
			return !(
				model.activeClarification ||
				snapshot.pendingPermissionRequest ||
				snapshot.pendingInterrupt ||
				snapshot.runState === 'running' ||
				isPlanReady(snapshot) ||
				latestRequestActorEvent(requestKey) ||
				latestRequestError(requestKey) ||
				latestSemanticBlockStatus(requestKey)
			);
		}

		function appendTraceIfLive(requestKey, label, hint) {
			if (!foregroundRequestCanReceiveTrace(requestKey)) {
				return;
			}
			appendForegroundBullet(label, 'active', hint || label);
			persistUiState();
			renderFeed();
			renderComposer();
			scheduleWebviewSnapshot('activity_trace');
		}

		function scheduleActivityTrace(requestKey) {
			setTimeout(() => {
				appendTraceIfLive(
					requestKey,
					'Checking workflow state',
					'Checking workflow state...'
				);
			}, 1800);
			setTimeout(() => {
				appendTraceIfLive(
					requestKey,
					'Still working behind the scenes',
					'Still working behind the scenes...'
				);
			}, 6500);
		}

		function runtimeProgressMatchesForeground(event) {
			return Boolean(
				event &&
					event.requestId &&
					ui.foregroundRequest &&
					ui.foregroundRequest.requestKey === event.requestId
			);
		}

		function applyRuntimeProgress(event) {
			if (!runtimeProgressMatchesForeground(event)) {
				return;
			}
			if (event.stage === 'turn_started') {
				ui.foregroundRequest.runtimeRequestId = event.runtimeRequestId || '';
				replaceForegroundTail(
					'Governor is reading the request',
					'active',
					'Governor is reading the request...'
				);
				scheduleGovernorWaitHeartbeat(event);
			} else if (event.stage === 'first_delta') {
				clearGovernorWaitTimers();
				const isSemanticIntake = event.runtimeKind === 'semantic_intake';
				replaceForegroundTail(
					isSemanticIntake
						? 'Governor is interpreting the request'
						: 'Governor is drafting a reply',
					'active',
					isSemanticIntake
						? 'Governor is interpreting the request...'
						: 'Governor is drafting a reply...'
				);
			} else if (event.stage === 'draft_preview') {
				clearGovernorWaitTimers();
				replaceForegroundTail(
					'Governor is drafting a reply',
					'active',
					'Governor is drafting a reply...'
				);
				if (typeof event.previewText === 'string' && event.previewText.trim()) {
					setDraftPreviewTarget(event.previewText);
				}
			} else if (event.stage === 'governor_runtime_failed') {
				clearGovernorWaitTimers();
				replaceForegroundTail(
					'Governor runtime had trouble',
					'failed',
					'Governor did not reply. Corgi is updating the state now.'
				);
				resetDraftPreview();
			} else if (event.stage === 'governor_runtime_completed') {
				clearGovernorWaitTimers();
			} else {
				return;
			}
			persistUiState();
			renderFeed();
			renderComposer();
			scheduleWebviewSnapshot('runtime_progress');
		}

		function freezeForegroundRequest(label, state, hint) {
			if (!ui.foregroundRequest) {
				return;
			}
			ui.foregroundRequest.bullets = ui.foregroundRequest.bullets.map((bullet, index, bullets) => ({
				...bullet,
				state:
					index === bullets.length - 1
						? bullet.state
						: bullet.state === 'failed'
							? 'failed'
							: 'done',
			}));
			if (label) {
				replaceForegroundTail(label, state || 'done', hint);
			} else if (ui.foregroundRequest.bullets.length > 0) {
				ui.foregroundRequest.bullets[ui.foregroundRequest.bullets.length - 1].state = state || 'done';
			}
			ui.foregroundRequest.status = 'frozen';
			resetDraftPreview();
			clearGovernorWaitTimers();
			if (hint) {
				ui.foregroundRequest.hint = hint;
			}
		}

		function latestRequestError(requestKey) {
			if (!model || !isAuthoritativeForegroundRequestKey(requestKey)) {
				return undefined;
			}
			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (
					item.type === 'error' &&
					item.in_response_to_request_id === requestKey
				) {
					return item;
				}
			}
			return undefined;
		}

		function latestSemanticBlockStatus(requestKey) {
			if (!model || !ui.foregroundRequest) {
				return undefined;
			}
			const expectedUserText = normalizeUiText(ui.foregroundRequest.userText);
			if (!expectedUserText) {
				return undefined;
			}
			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (
					item.type === 'system_status' &&
					item.source_layer === 'dialog_controller' &&
					item.source_actor === 'semantic_sidecar'
				) {
					const previous = model.feed[index - 1];
					if (
						previous?.type === 'user_message' &&
						normalizeUiText(previous.body || previous.title) === expectedUserText &&
						(!isAuthoritativeForegroundRequestKey(requestKey) ||
							!previous.in_response_to_request_id ||
							previous.in_response_to_request_id === requestKey)
					) {
						return item;
					}
				}
			}
			return undefined;
		}

		function latestRequestActorEvent(requestKey) {
			if (!model || !isAuthoritativeForegroundRequestKey(requestKey)) {
				return undefined;
			}
			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (
					item.type === 'actor_event' &&
					item.in_response_to_request_id === requestKey
				) {
					return item;
				}
			}
			return undefined;
		}

		function latestGovernorReplyForRequest(requestKey) {
			const actorEvent = latestRequestActorEvent(requestKey);
			if (actorEvent?.source_actor === 'governor') {
				return actorEvent;
			}
			return undefined;
		}

		function syncForegroundRequestIdentityFromModel() {
			if (!model) {
				return;
			}
			const requestKey = model.activeForegroundRequestId;
			if (!requestKey) {
				return;
			}
			const userText = latestForegroundUserTextFromModel(requestKey);
			if (!ui.foregroundRequest) {
				startForegroundRequest(userText, '', requestKey);
				return;
			}
			if (ui.foregroundRequest.requestKey === requestKey) {
				if (!ui.foregroundRequest.userText && userText) {
					ui.foregroundRequest.userText = userText;
				}
				return;
			}
			if (!isAuthoritativeForegroundRequestKey(ui.foregroundRequest.requestKey)) {
				ui.foregroundRequest.requestKey = requestKey;
				if (!ui.foregroundRequest.userText && userText) {
					ui.foregroundRequest.userText = userText;
				}
				return;
			}
			startForegroundRequest(userText || ui.foregroundRequest.userText, '', requestKey);
		}

		function foregroundRequestHasAuthoritativeSurface(requestKey) {
			if (!model || !requestKey) {
				return false;
			}
			const snapshot = model.snapshot;
			return Boolean(
				model.activeForegroundRequestId === requestKey ||
					model.activeClarification ||
					snapshot.pendingPermissionRequest?.foregroundRequestId === requestKey ||
					snapshot.pendingInterrupt ||
					model.planReadyRequest?.foregroundRequestId === requestKey ||
					(snapshot.currentActor === 'governor' && snapshot.runState === 'running') ||
					latestRequestActorEvent(requestKey) ||
					latestRequestError(requestKey) ||
					latestSemanticBlockStatus(requestKey)
			);
		}

		function reconcileLocalUiWithModel() {
			if (!model) {
				clearForegroundRequest();
				ui.pendingPermissionContextRef = undefined;
				ui.pendingPermissionHiddenAt = undefined;
				ui.pendingPlanContextRef = undefined;
				ui.pendingPlanHiddenAt = undefined;
				ui.planRevisionMode = false;
				return;
			}

			if (
				ui.pendingPermissionContextRef &&
				authoritativePermissionContextRef() !== ui.pendingPermissionContextRef
			) {
				ui.pendingPermissionContextRef = undefined;
				ui.pendingPermissionHiddenAt = undefined;
			}

			if (
				ui.pendingPlanContextRef &&
				authoritativePlanContextRef() !== ui.pendingPlanContextRef
			) {
				ui.pendingPlanContextRef = undefined;
				ui.pendingPlanHiddenAt = undefined;
			}

			if (!model.snapshot || !isPlanReady(model.snapshot)) {
				ui.planRevisionMode = false;
			}

			if (!ui.foregroundRequest) {
				return;
			}

			const requestKey = ui.foregroundRequest.requestKey;
			if (latestGovernorReplyForRequest(requestKey)) {
				clearForegroundRequest();
				return;
			}

			if (
				ui.foregroundRequest.status === 'live' &&
				!foregroundRequestHasAuthoritativeSurface(requestKey)
			) {
				clearForegroundRequest();
			}
		}

		function syncForegroundRequestFromModel() {
			if (!model) {
				return;
			}
			syncForegroundRequestIdentityFromModel();
			if (!ui.foregroundRequest) {
				return;
			}

			const snapshot = model.snapshot;
			const requestKey = ui.foregroundRequest.requestKey;
			const latestError = latestRequestError(requestKey);
			if (latestError) {
				freezeForegroundRequest(latestError.title, 'failed', 'Corgi needs your input before this can continue.');
				return;
			}

			const latestSemanticBlock = latestSemanticBlockStatus(requestKey);
			if (latestSemanticBlock) {
				freezeForegroundRequest(
					latestSemanticBlock.title,
					latestSemanticBlock.semantic_block_reason === 'semantic_sidecar_unavailable'
						? 'failed'
						: 'waiting',
					latestSemanticBlock.body || 'Corgi needs a clearer request before this can continue.'
				);
				return;
			}

			if (model.activeClarification) {
				replaceForegroundTail('Waiting for clarification', 'waiting', 'Answer the clarification to continue this request.');
				return;
			}

			if (snapshot.pendingPermissionRequest) {
				replaceForegroundTail(
					'Waiting for permission: ' + snapshot.pendingPermissionRequest.recommendedScope.charAt(0).toUpperCase() + snapshot.pendingPermissionRequest.recommendedScope.slice(1),
					'waiting',
					'Choose a permission scope to continue this request.'
				);
				return;
			}

			if (snapshot.pendingInterrupt) {
				replaceForegroundTail('Stop requested', 'waiting', 'Waiting for orchestration to handle the stop request.');
				return;
			}

			const latestActorEvent = latestRequestActorEvent(requestKey);
			if (latestActorEvent) {
				freezeForegroundRequest('Governor responded', 'done', 'Corgi is ready for the next step.');
				return;
			}

			if (snapshot.currentActor === 'governor') {
				if (snapshot.currentStage === 'semantic_intake') {
					replaceForegroundTail(
						'Governor is interpreting the request',
						'active',
						'Governor is interpreting the request...'
					);
					return;
				}
				setForegroundSingleBullet(
					'Waiting for a reply from the Governor...',
					'active',
					'Waiting for a reply from the Governor...'
				);
				return;
			}

			if (snapshot.runState === 'running') {
				replaceForegroundTail('Execution started', 'active', 'Corgi is actively working on this request.');
				return;
			}

			if (model.acceptedIntakeSummary && isAuthoritativeForegroundRequestKey(requestKey)) {
				freezeForegroundRequest('Intake accepted', 'done', 'Corgi is ready for permitted work.');
				return;
			}
		}

		function composerMode() {
			if (model?.snapshot && isPlanReady(model.snapshot) && ui.planRevisionMode) {
				return {
					placeholder: 'Tell the Governor what to add, explain, or revise...',
					hint: 'This updates the plan only. Execute still requires Execute permission.',
					buttonLabel: 'Send to Governor',
				};
			}
			if (model?.activeClarification) {
				const hasOptions =
					Array.isArray(model.activeClarification.options) &&
					model.activeClarification.options.length > 0;
				return {
					placeholder:
						model.activeClarification.placeholder ||
						'Answer the clarification so Corgi can continue.',
					hint: hasOptions
						? 'Choose an option below or type a short answer. Enter to send.'
						: 'Answering clarification. Enter to send.',
					buttonLabel: 'Answer',
				};
			}

			return {
				placeholder: 'Ask Corgi to work on this repo...',
				hint: 'Enter to send, Shift+Enter for newline',
				buttonLabel: 'Send',
			};
		}

		function renderHeader() {
			if (!model) {
				return;
			}

			const snapshot = model.snapshot;
			const stale = isSnapshotStale(snapshot);
			const railTask = railTitle(snapshot);
			const subline = [];
			const actor = actorSummary(snapshot);
			const stage = stageSummary(snapshot);
			if (actor) {
				subline.push(renderRevealPill('Actor', actor));
			}
			if (stage) {
				subline.push(renderRevealPill('Stage', stage));
			}
			subline.push(
				'<span class="pill">' +
					'<span class="status-dot ' + statusDotClass(snapshot, stale) + '"></span>' +
					escapeHtml(statusLabel(snapshot, stale)) +
				'</span>'
			);

			headerContent.innerHTML =
				'<div class="header-subline">' +
					renderRevealPill('Current work', railTask, 'is-primary') +
					subline.join('') +
				'</div>';
		}

		function renderActionBand() {
			if (!model) {
				return;
			}
			retainOptimisticHidesUntilAuthoritativeChange();

			const snapshot = model.snapshot;
			const cards = [];

			if (model.activeClarification) {
				const clarificationOptions = Array.isArray(model.activeClarification.options)
					? model.activeClarification.options
					: [];
				const optionButtons =
					clarificationOptions.length > 0
						? '<div class="card-actions">' +
							clarificationOptions
								.map(
									(option) =>
										'<button type="button" class="secondary" data-clarification-answer="' +
										escapeHtml(option.answer) +
										'" title="' +
										escapeHtml(option.description || option.answer) +
										'">' +
										escapeHtml(option.label) +
										'</button>'
								)
								.join('') +
						  '</div>'
						: '';
				cards.push(
					'<section class="action-card">' +
						'<h2>Choose a focus</h2>' +
						'<p>Pick one option, or type a short answer below.</p>' +
						optionButtons +
						renderArtifactQuickAction(currentQuickArtifact()) +
					'</section>'
				);
			}

			if (
				snapshot.pendingPermissionRequest &&
				snapshot.pendingPermissionRequest.contextRef !== ui.pendingPermissionContextRef
			) {
				const scopes = Array.isArray(snapshot.pendingPermissionRequest.allowedScopes)
					? snapshot.pendingPermissionRequest.allowedScopes
					: ['observe', 'plan', 'execute'];
				cards.push(
					'<section class="action-card">' +
						'<h2>' + escapeHtml(snapshot.pendingPermissionRequest.title) + '</h2>' +
						'<p>' + escapeHtml(snapshot.pendingPermissionRequest.body) + '</p>' +
						'<div class="card-actions">' +
							scopes.map((scope) =>
								'<button type="button" ' +
									(scope === snapshot.pendingPermissionRequest.recommendedScope ? '' : 'class="secondary" ') +
									'data-action="set_permission_scope" data-permission-scope="' + escapeHtml(scope) + '">' +
									escapeHtml(scope.charAt(0).toUpperCase() + scope.slice(1)) +
								'</button>'
							).join('') +
							'<button type="button" class="secondary" data-action="decline_permission">Decline</button>' +
						'</div>' +
						renderArtifactQuickAction(currentQuickArtifact()) +
					'</section>'
				);
			}
			if (
				snapshot.pendingPermissionRequest &&
				snapshot.pendingPermissionRequest.contextRef === ui.pendingPermissionContextRef
			) {
				const requestedScope = snapshot.pendingPermissionRequest.recommendedScope || 'permission';
				const waitingCopy =
					requestedScope === 'execute'
						? 'Execute permission choice sent. Waiting for Corgi to continue...'
						: 'Permission choice sent. Waiting for a reply from the Governor...';
				cards.push(
					'<section class="action-card action-card-waiting">' +
						'<h2>Waiting for Corgi</h2>' +
						'<p>' + escapeHtml(waitingCopy) + '</p>' +
						'<div class="card-actions">' +
							'<button type="button" class="secondary" data-action="refresh_state">Refresh state</button>' +
						'</div>' +
					'</section>'
				);
			}

			if (
				isPlanReady(snapshot) &&
				model.planReadyRequest.contextRef !== ui.pendingPlanContextRef
			) {
				const planReady = model.planReadyRequest;
				const actions = Array.isArray(planReady.allowedActions)
					? planReady.allowedActions
					: ['execute_plan', 'revise_plan'];
				cards.push(
					'<section class="action-card">' +
						'<h2>' + escapeHtml(planReady.title || 'Plan ready') + '</h2>' +
						'<p>' + escapeHtml(planReady.body || 'Review the Governor plan, then execute it or add details for a revision.') + '</p>' +
						'<div class="card-actions">' +
							(actions.includes('execute_plan')
								? '<button type="button" data-action="execute_plan" data-context-ref="' + escapeHtml(planReady.contextRef) + '">Execute this plan</button>'
								: '') +
							(actions.includes('revise_plan')
								? '<button type="button" class="secondary" data-action="revise_plan" data-context-ref="' + escapeHtml(planReady.contextRef) + '">Add details or revise plan</button>'
								: '') +
						'</div>' +
						renderArtifactQuickAction(currentQuickArtifact()) +
					'</section>'
				);
			}
			if (
				isPlanReady(snapshot) &&
				model.planReadyRequest.contextRef === ui.pendingPlanContextRef
			) {
				cards.push(
					'<section class="action-card action-card-waiting">' +
						'<h2>Waiting for Governor</h2>' +
						'<p>Plan action sent. Waiting for a reply from the Governor...</p>' +
						'<div class="card-actions">' +
							'<button type="button" class="secondary" data-action="refresh_state">Refresh state</button>' +
						'</div>' +
					'</section>'
				);
			}

			if (snapshot.pendingInterrupt) {
				cards.push(
					'<section class="action-card">' +
						'<h2>' + escapeHtml(snapshot.pendingInterrupt.title) + '</h2>' +
						'<p>' + escapeHtml(snapshot.pendingInterrupt.body) + '</p>' +
						renderArtifactQuickAction(currentQuickArtifact()) +
					'</section>'
				);
			} else if (canStop(snapshot)) {
				cards.push(
					'<section class="action-card">' +
						'<h2>Run controls</h2>' +
						'<p>Corgi is handling the current request. Stop only if you need to interrupt it.</p>' +
						'<div class="card-actions">' +
							'<button type="button" class="secondary" data-action="interrupt_run">Stop</button>' +
						'</div>' +
						renderArtifactQuickAction(currentQuickArtifact()) +
					'</section>'
				);
			}

			actionBand.innerHTML = cards.join('');
			actionBand.hidden = cards.length === 0;
		}

		function formatElapsed(ms) {
			if (typeof ms !== 'number' || ms <= 0) {
				return '';
			}

			if (ms < 1000) {
				return ' for ' + ms + 'ms';
			}

			return ' for ' + Math.round(ms / 100) / 10 + 's';
		}

		function activityLabel(item) {
			const activity = item.activity ?? {};
			const path = activity.path || item.artifact?.path;
			const query = activity.query;
			const command = activity.command;
			const elapsed = formatElapsed(activity.elapsedMs);

			switch (activity.kind) {
				case 'read':
					return 'Read ' + (path || item.title);
				case 'search':
					if (activity.state === 'running') {
						return 'Searching for ' + (query ? '"' + query + '"' : 'matches');
					}
					return 'Searched for ' + (query ? '"' + query + '"' : 'matches');
				case 'list':
					if (activity.state === 'running') {
						return 'Listing files' + (path ? ' in ' + path : '');
					}
					return 'Listed files' + (path ? ' in ' + path : '');
				case 'command':
					if (activity.state === 'running') {
						return 'Running ' + (command || 'command') + elapsed;
					}
					if (activity.state === 'failed') {
						return 'Command failed ' + (command || '') + elapsed;
					}
					if (activity.state === 'stopped') {
						return 'Stopped ' + (command || 'command') + elapsed;
					}
					return 'Ran ' + (command || 'command') + elapsed;
				case 'edit':
					if (activity.state === 'running') {
						return 'Editing ' + (path || 'files');
					}
					return 'Edited ' + (path || 'files');
				case 'artifact':
					return 'Referenced ' + (path || item.title);
				case 'status':
					return activity.summary || item.title;
				default:
					return item.title;
			}
		}

		function renderDetails(item) {
			if (item.type === 'actor_event' && item.source_actor === 'governor') {
				return '';
			}

			const details = Array.isArray(item.details) && item.details.length > 0;
			if (!details) {
				return '';
			}

			const isExpanded = ui.expandedIds.has(item.id);
			const toggle =
				'<div class="inline-actions">' +
					'<button class="ghost" type="button" data-action="toggle_details" data-feed-id="' +
					escapeHtml(item.id) +
					'">' +
					(isExpanded ? 'Hide details' : 'Show details') +
					'</button>' +
				'</div>';

			if (!isExpanded) {
				return toggle;
			}

			return (
				toggle +
				'<ul class="detail-list">' +
					item.details.map((line) => '<li>' + escapeHtml(line) + '</li>').join('') +
				'</ul>'
			);
		}

		function renderArtifactActions() {
			return '';
		}

		function displayScope(value) {
			const scope = String(value || '').trim().toLowerCase();
			if (scope === 'observe' || scope === 'plan' || scope === 'execute') {
				return scope.charAt(0).toUpperCase() + scope.slice(1);
			}
			return 'Plan';
		}

		function presentationArgs(item) {
			return item && typeof item.presentation_args === 'object' && item.presentation_args
				? item.presentation_args
				: {};
		}

		function displayCopy(item) {
			const fallback = {
				title: item.title || '',
				body: item.body || '',
			};

			if (item.type === 'actor_event' && item.source_actor === 'governor') {
				return fallback;
			}

			const args = presentationArgs(item);
			switch (item.presentation_key) {
				case 'permission.needed':
					return {
						title: 'Permission needed',
						body: 'Choose ' + displayScope(args.scope) + ' to continue this request.',
					};
				case 'permission.declined':
					return {
						title: 'Permission declined',
						body: 'This request will not continue, and the session permission scope stayed unchanged.',
					};
				case 'permission.superseded':
					return {
						title: 'Previous permission skipped',
						body: 'A new request replaced the previous permission choice.',
					};
				case 'semantic.unavailable':
					return {
						title: 'Could not classify request',
						body: 'Corgi could not classify that request right now. Try again or restate it directly.',
					};
				case 'semantic.control_unmappable':
					return {
						title: 'Need a clearer control request',
						body: 'Restate this as stop, a progress question, or a new work request.',
					};
				case 'semantic.nothing_running':
					return {
						title: 'Nothing is running',
						body: 'Ask for progress, or send a new work request.',
					};
				case 'semantic.interrupt_pending':
					return {
						title: 'Stop already requested',
						body: 'A stop request is already pending.',
					};
				case 'semantic.no_active_clarification':
					return {
						title: 'No clarification is active',
						body: 'Ask for progress, or send a new work request.',
					};
				case 'semantic.needs_clearer_request':
					return {
						title: fallback.title,
						body: fallback.body || 'Restate the request more directly.',
					};
				case 'error.semantic_route_required':
					return {
						title: 'Could not route request',
						body: 'Try again after Corgi finishes classifying the prompt.',
					};
				case 'error.session_changed':
					return {
						title: 'Session changed',
						body: 'Refresh and try again with the current session.',
					};
				case 'error.stale_context':
					return {
						title: 'State changed',
						body: 'Refresh and use the current action surface.',
					};
				case 'error.duplicate_request':
					return {
						title: 'Request already handled',
						body: 'Send a new action if you still want to proceed.',
					};
				case 'error.generic':
					return {
						title: String(args.title || fallback.title),
						body: String(args.body || fallback.body),
					};
				case 'session.switched':
					return {
						title: 'Session switched',
						body: 'Reconnect attached to a different session.',
					};
				case 'reconnect.not_needed':
					return {
						title: 'Already connected',
						body: 'The current session is connected and fresh.',
					};
				default:
					return fallback;
			}
		}

		function renderActivity(item) {
			const activity = item.activity ?? { state: item.type === 'error' ? 'failed' : 'completed' };
			const state = activity.state || 'completed';
			const summary = item.type === 'artifact_reference'
				? item.artifact.summary
				: activity.summary && activity.kind !== 'status'
					? activity.summary
					: undefined;

			return (
				'<article class="activity-row is-' + escapeHtml(state) + ' ' +
					(item.authoritative ? '' : 'is-informational') +
				'">' +
					'<div class="activity-dot"></div>' +
					'<div>' +
						'<div class="activity-label">' + escapeHtml(activityLabel(item)) + '</div>' +
						(summary ? '<div class="activity-summary">' + escapeHtml(summary) + '</div>' : '') +
						renderArtifactActions(item) +
						renderDetails(item) +
					'</div>' +
				'</article>'
			);
		}

		function renderMessage(item) {
			const copy = displayCopy(item);
			if (item.type === 'error') {
				return (
					'<article class="message error">' +
						'<div class="message-label">Error</div>' +
						'<div class="message-body">' + escapeHtml(copy.title) + '</div>' +
						(copy.body ? '<div class="activity-summary">' + escapeHtml(copy.body) + '</div>' : '') +
						renderArtifactQuickAction(milestoneArtifact(item)) +
						renderDetails(item) +
					'</article>'
				);
			}

			if (item.type === 'user_message') {
				return (
					'<article class="message user">' +
						'<div class="message-body">' + escapeHtml(item.body || item.title) + '</div>' +
					'</article>'
				);
			}

			return (
				'<article class="message assistant ' +
					(item.authoritative ? '' : 'is-informational') +
				'">' +
					'<div class="message-body">' + escapeHtml(copy.body || copy.title) + '</div>' +
					(isMeaningfulMilestone(item)
						? renderArtifactQuickAction(milestoneArtifact(item))
						: '') +
					renderDetails(item) +
				'</article>'
			);
		}

		function normalizeUiText(value) {
			return String(value || '')
				.trim()
				.toLowerCase()
				.replace(/[.!?]+$/g, '')
				.replace(/\s+/g, ' ');
		}

		function latestRenderedAssistantItem() {
			if (!model) {
				return undefined;
			}
			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (
					item.type !== 'user_message' &&
					item.type !== 'artifact_reference' &&
					shouldRenderInTranscript(item)
				) {
					return item;
				}
			}
			return undefined;
		}

		function renderForegroundRequest() {
			if (!ui.foregroundRequest) {
				return '';
			}

			const requestKey = ui.foregroundRequest.requestKey;
			if (latestGovernorReplyForRequest(requestKey)) {
				return '';
			}

			const hasAuthoritativeUserEcho =
				Boolean(model) &&
				model.feed.some(
					(item) =>
						item.type === 'user_message' &&
						(item.body || item.title) === ui.foregroundRequest.userText
				);

			const bullets = Array.isArray(ui.foregroundRequest.bullets)
				? ui.foregroundRequest.bullets
				: [];
			const visibleBullets = bullets.slice(-3);
			const latestBulletLabel =
				visibleBullets.length > 0
					? normalizeUiText(visibleBullets[visibleBullets.length - 1].label)
					: '';
			const latestAssistantItem = latestRenderedAssistantItem();
			const latestAssistantText = normalizeUiText(
				latestAssistantItem?.body || latestAssistantItem?.title
			);
			const hintText = normalizeUiText(ui.foregroundRequest.hint);
			const shouldRenderHint =
				Boolean(hintText) &&
				hintText !== latestBulletLabel &&
				!(
					ui.foregroundRequest.status === 'frozen' &&
					hintText === latestAssistantText
				);
			const bulletMarkup =
				visibleBullets.length > 0
					? '<ul class="detail-list progress-list">' +
						visibleBullets
							.map(
								(bullet) =>
									'<li class="progress-bullet is-' +
									escapeHtml(bullet.state || 'active') +
									'">' +
									'<span class="progress-bullet-text">' +
										escapeHtml(bullet.label) +
									'</span>' +
									'</li>'
							)
							.join('') +
					  '</ul>'
					: '';
			const draftPreviewText = String(ui.foregroundRequest.draftPreview || '').trim();
			const draftPreviewMarkup = draftPreviewText
				? '<div class="draft-preview" aria-live="polite">' +
					'<div class="draft-preview-label">Governor draft</div>' +
					'<div>' + escapeHtml(draftPreviewText) + '</div>' +
				  '</div>'
				: '';

			return (
				(ui.foregroundRequest.userText && !hasAuthoritativeUserEcho
					? '<article class="message user">' +
						'<div class="message-body">' + escapeHtml(ui.foregroundRequest.userText) + '</div>' +
					  '</article>'
					: '') +
				'<article class="message assistant is-informational progress-cluster ' +
					'activity-trace ' +
					(ui.foregroundRequest.status === 'frozen' ? 'is-frozen' : '') +
				'">' +
					bulletMarkup +
					draftPreviewMarkup +
					(shouldRenderHint
						? '<div class="activity-summary">' + escapeHtml(ui.foregroundRequest.hint) + '</div>'
						: '') +
				'</article>'
			);
		}

		function dividerMarkup(label) {
			return '<div class="feed-divider" role="separator">' + escapeHtml(label) + '</div>';
		}

		function renderFeedItem(item) {
			if (!shouldRenderInTranscript(item)) {
				return '';
			}

			if (item.activity) {
				return renderActivity(item);
			}

			return renderMessage(item);
		}

		function renderFeed() {
			if (!model) {
				return;
			}

			const previousScrollTop = feed.scrollTop;
			const wasNearBottom =
				feed.scrollHeight - feed.scrollTop - feed.clientHeight < 56;

			const dividerIndex =
				typeof ui.initialFeedCount === 'number' &&
				ui.initialFeedCount > 0 &&
				model.feed.length > ui.initialFeedCount
					? ui.initialFeedCount
					: -1;
			const cards = model.feed.map((item, index) => {
				const markup = renderFeedItem(item);
				if (index === dividerIndex) {
					return dividerMarkup('Current turn') + markup;
				}
				return markup;
			}).filter((markup) => markup && markup.trim().length > 0);
			const foregroundMarkup = renderForegroundRequest();
			if (foregroundMarkup) {
				cards.push(foregroundMarkup);
			}

			feed.innerHTML =
				cards.length > 0
					? cards.join('')
					: '<div class="feed-empty">No messages yet.</div>';

			if (!hasRendered && ui.scrollTop > 0) {
				feed.scrollTop = ui.scrollTop;
			} else if (!hasRendered || wasNearBottom) {
				feed.scrollTop = feed.scrollHeight;
			} else {
				feed.scrollTop = previousScrollTop;
			}

			hasRendered = true;
			persistUiState();
		}

		function renderComposer() {
			const mode = composerMode();
			const blocked = model?.snapshot?.transportState === 'disconnected';
			const hasActionSurface = Boolean(
				model?.activeClarification ||
					model?.snapshot?.pendingPermissionRequest ||
					model?.snapshot?.pendingInterrupt ||
					(model?.snapshot && isPlanReady(model.snapshot))
			);
			const busy = Boolean(
				ui.foregroundRequest &&
					ui.foregroundRequest.status === 'live' &&
					!hasActionSurface
			);
			const chips = model ? renderContextChips(model.snapshot) : '';
			composerInput.placeholder = mode.placeholder;
			composerHint.textContent = blocked
				? 'Open the repo/workspace folder that contains orchestration/scripts/orchestrate.py, then reopen Corgi.'
				: busy
					? (ui.foregroundRequest?.hint || 'Corgi is processing your request...')
				: mode.hint;
			composerSubmitButton.textContent = busy ? 'Sending...' : mode.buttonLabel;
			composerInput.value = ui.draft;
			composerInput.disabled = blocked || busy;
			composerSubmitButton.disabled = blocked || busy;
			composerContext.innerHTML = chips;
			composerContext.hidden = chips.length === 0;
		}

		function render() {
			if (!model) {
				return;
			}

			loadingState.hidden = true;
			app.hidden = false;
			renderHeader();
			renderActionBand();
			renderFeed();
			renderComposer();
			scheduleWebviewSnapshot('render');
		}

		function handleSubmit(event) {
			event.preventDefault();
			const text = ui.draft.trim();
			if (!text) {
				return;
			}

			rememberPrompt(text);
			resetPromptHistoryNavigation();
			const requestId = nextForegroundRequestKey();
			if (model?.snapshot && isPlanReady(model.snapshot) && ui.planRevisionMode) {
				startForegroundRequest(text, 'Waiting for a reply from the Governor...', requestId);
				ui.pendingPlanContextRef = model.planReadyRequest?.contextRef;
				ui.pendingPlanHiddenAt = Date.now();
				setForegroundSingleBullet(
					'Waiting for a reply from the Governor...',
					'active',
					'Waiting for a reply from the Governor...'
				);
				scheduleActivityTrace(requestId);
				vscode.postMessage({ type: 'revise_plan', text, requestId });
				ui.planRevisionMode = false;
			} else {
				startForegroundRequest(text, 'Interpreting request...', requestId);
				appendForegroundBullet('Interpreting request', 'active', 'Interpreting request...');
				scheduleActivityTrace(requestId);
				vscode.postMessage({ type: 'submit_prompt', text, requestId });
			}

			ui.draft = '';
			persistUiState();
			renderActionBand();
			renderFeed();
			renderComposer();
			scheduleWebviewSnapshot('submit');
		}

		composerForm.addEventListener('submit', handleSubmit);
		composerInput.addEventListener('input', (event) => {
			ui.draft = event.target.value;
			resetPromptHistoryNavigation();
			persistUiState();
		});
		composerInput.addEventListener('keydown', (event) => {
			if (
				event.key === 'ArrowUp' &&
				!event.shiftKey &&
				!event.altKey &&
				!event.metaKey &&
				!event.ctrlKey &&
				composerInput.selectionStart === 0 &&
				composerInput.selectionEnd === 0
			) {
				if (navigatePromptHistory('up')) {
					event.preventDefault();
					return;
				}
			}
			if (
				event.key === 'ArrowDown' &&
				!event.shiftKey &&
				!event.altKey &&
				!event.metaKey &&
				!event.ctrlKey &&
				ui.historyIndex !== undefined &&
				composerInput.selectionStart === composerInput.value.length &&
				composerInput.selectionEnd === composerInput.value.length
			) {
				if (navigatePromptHistory('down')) {
					event.preventDefault();
					return;
				}
			}
			if (event.key === 'Enter' && !event.shiftKey) {
				event.preventDefault();
				composerForm.requestSubmit();
			}
		});
		feed.addEventListener('scroll', () => {
			ui.scrollTop = feed.scrollTop;
			persistUiState();
			scheduleWebviewSnapshot('scroll');
		});

		document.addEventListener('click', (event) => {
			const target = event.target.closest('button[data-action]');
			const clarificationTarget = event.target.closest('button[data-clarification-answer]');
			if (clarificationTarget) {
				const clarificationAnswer = clarificationTarget.dataset.clarificationAnswer;
				if (clarificationAnswer) {
					const requestId = nextForegroundRequestKey();
					ensureForegroundRequest('', '', requestId);
					appendForegroundBullet('Clarification received', 'done', 'Applying your clarification...');
					appendForegroundBullet('Continuing request', 'active', 'Applying your clarification...');
					renderFeed();
					renderComposer();
					scheduleWebviewSnapshot('clarification_click');
					vscode.postMessage({
						type: 'answer_clarification',
						text: clarificationAnswer,
						requestId,
					});
				}
				return;
			}
			if (!target) {
				return;
			}

			const action = target.dataset.action;
			if (action === 'refresh_state') {
				vscode.postMessage({ type: 'refresh_state' });
				scheduleWebviewSnapshot('refresh_state_click');
				return;
			}
			if (action === 'execute_plan') {
				const requestId = nextForegroundRequestKey();
				startForegroundRequest('Execute this plan', 'Requesting Execute permission...', requestId);
				setForegroundSingleBullet(
					'Requesting Execute permission...',
					'active',
					'Requesting Execute permission...'
				);
				scheduleActivityTrace(requestId);
				ui.planRevisionMode = false;
				ui.pendingPlanContextRef = model?.planReadyRequest?.contextRef;
				ui.pendingPlanHiddenAt = Date.now();
				renderActionBand();
				renderFeed();
				renderComposer();
				scheduleWebviewSnapshot('execute_plan_click');
				vscode.postMessage({ type: 'execute_plan', requestId });
				return;
			}
			if (action === 'revise_plan') {
				ui.planRevisionMode = true;
				ui.draft = '';
				resetPromptHistoryNavigation();
				persistUiState();
				renderActionBand();
				renderComposer();
				scheduleWebviewSnapshot('revise_plan_click');
				composerInput.focus();
				return;
			}
			if (action === 'toggle_details') {
				const feedId = target.dataset.feedId;
				if (!feedId) {
					return;
				}
				if (ui.expandedIds.has(feedId)) {
					ui.expandedIds.delete(feedId);
				} else {
					ui.expandedIds.add(feedId);
				}
				persistUiState();
				renderFeed();
				scheduleWebviewSnapshot('toggle_details');
				return;
			}

			const artifactId = target.dataset.artifactId;
			if (
				action === 'open_artifact' ||
				action === 'reveal_artifact_path' ||
				action === 'copy_artifact_path'
			) {
				vscode.postMessage({
					type: action,
					artifactId,
				});
				return;
			}

			if (
				action === 'set_permission_scope' ||
				action === 'decline_permission' ||
				action === 'interrupt_run'
			) {
				if (action === 'set_permission_scope') {
					const scope = target.dataset.permissionScope;
					const requestId = nextForegroundRequestKey();
					const requestKey = foregroundRequestKeyForAction(action);
					ensureForegroundRequest('', '', requestKey);
					ui.pendingPermissionContextRef =
						model?.snapshot?.pendingPermissionRequest?.contextRef;
					ui.pendingPermissionHiddenAt = Date.now();
					setForegroundSingleBullet(
						scope === 'execute'
							? 'Starting execution...'
							: 'Waiting for a reply from the Governor...',
						'active',
						scope === 'execute'
							? 'Starting execution...'
							: 'Waiting for a reply from the Governor...'
					);
					scheduleActivityTrace(requestKey);
					renderActionBand();
					renderFeed();
					renderComposer();
					scheduleWebviewSnapshot('permission_click');
					vscode.postMessage({
						type: 'set_permission_scope',
						permissionScope: scope,
						requestId,
					});
					return;
				}
				if (action === 'decline_permission') {
					const requestId = nextForegroundRequestKey();
					const requestKey = foregroundRequestKeyForAction(action);
					ensureForegroundRequest('', '', requestKey);
					appendForegroundBullet('Permission declined', 'failed', 'This request will not continue.');
					freezeForegroundRequest(undefined, 'failed', 'This request will not continue.');
					vscode.postMessage({ type: action, requestId });
				} else {
					const requestId = nextForegroundRequestKey();
					const requestKey = foregroundRequestKeyForAction(action);
					ensureForegroundRequest('', '', requestKey);
					appendForegroundBullet('Stop requested', 'waiting', 'Requesting stop...');
					vscode.postMessage({ type: action, requestId });
				}
				renderFeed();
				renderComposer();
				scheduleWebviewSnapshot('action_click');
			}
		});

		window.addEventListener('message', (event) => {
			const message = event.data;
			if (message?.type === 'runtime_progress') {
				applyRuntimeProgress(message.payload || {});
				return;
			}
			if (message?.type !== 'state') {
				return;
			}

			model = message.payload;
			reconcileLocalUiWithModel();
			syncForegroundRequestFromModel();
			if (
				typeof ui.initialFeedCount !== 'number' ||
				(model?.feed?.length ?? 0) < ui.initialFeedCount
			) {
				ui.initialFeedCount = Array.isArray(model?.feed) ? model.feed.length : 0;
				persistUiState();
			}
			render();
		});

		setInterval(() => {
			if (model) {
				renderHeader();
				renderActionBand();
				renderComposer();
				scheduleWebviewSnapshot('heartbeat');
			}
		}, 5000);

		vscode.postMessage({ type: 'ready' });
	</script>
</body>
</html>`;
}

function getNonce() {
	let text = '';
	const possible =
		'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
	for (let i = 0; i < 32; i += 1) {
		text += possible.charAt(Math.floor(Math.random() * possible.length));
	}
	return text;
}
