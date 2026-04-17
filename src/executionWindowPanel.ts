import { randomUUID } from 'crypto';
import * as vscode from 'vscode';
import {
	appendError,
	appendControllerSemanticClarification,
	createInitialModel,
	getArtifactById,
	type ExecutionWindowModel,
	type ModelAction,
} from './phase1Model';
import {
	createExecutionTransport,
	TransportUnavailableError,
	type ExecutionTransport,
} from './executionTransport';
import { SemanticSidecar, type SemanticLoopState } from './semanticSidecar';

export const EXECUTION_WINDOW_CONTAINER_ID = 'extExecutionWindowSidebar';
export const EXECUTION_WINDOW_VIEW_ID = 'ext.executionWindowView';

function shouldResetDevelopmentWebviewState(context: vscode.ExtensionContext): boolean {
	return context.extensionMode === vscode.ExtensionMode.Development;
}

type WebviewMessage =
	| { type: 'ready' }
	| { type: 'submit_prompt'; text?: string }
	| { type: 'answer_clarification'; text?: string }
	| { type: 'set_permission_scope'; permissionScope?: 'observe' | 'plan' | 'execute' }
	| { type: 'decline_permission' }
	| { type: 'interrupt_run' }
	| { type: 'open_artifact'; artifactId?: string }
	| { type: 'reveal_artifact_path'; artifactId?: string }
	| { type: 'copy_artifact_path'; artifactId?: string };

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
	private semanticLoopState: SemanticLoopState | undefined;

	private constructor(context: vscode.ExtensionContext) {
		this.context = context;
		this.workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
		this.model = createInitialModel();
		this.transport = createExecutionTransport(
			context.extensionMode,
			this.workspaceRoot,
			context.extensionUri
		);
		this.semanticSidecar = new SemanticSidecar();
	}

	public resolveWebviewView(webviewView: vscode.WebviewView) {
		this.disposeWebviewListeners();
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
	}

	public dispose() {
		this.disposeWebviewListeners();

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

	private async refreshState() {
		try {
			this.model = await this.transport.load();
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
			case 'interrupt_run':
				return this.model.snapshot.snapshotFreshness.receivedAt
					? `interrupt:${this.model.snapshot.snapshotFreshness.receivedAt}`
					: undefined;
			default:
				return undefined;
		}
	}

	private buildControllerAction(action: ModelAction): ModelAction {
		return {
			...action,
			request_id: action.request_id ?? this.nextRequestId(),
			context_ref: action.context_ref ?? this.contextRefForAction(action.type),
			session_ref: action.session_ref ?? this.model.snapshot.sessionRef,
		};
	}

	private async routeFreeText(text: string) {
		const rawText = text.trim();
		if (!rawText) {
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
				'Semantic routing failed',
				error instanceof Error
					? error.message
					: 'Corgi could not classify that request.'
			);
			return;
		}

		if (resolution.kind === 'block') {
			this.semanticLoopState = resolution.nextLoopState;
			this.model = appendControllerSemanticClarification(
				this.model,
				rawText,
				resolution.body,
				resolution.semantic
			);
			this.postState();
			return;
		}

		await this.applyAction(this.buildControllerAction(resolution.action));
	}

	private async handleMessage(message: WebviewMessage) {
		switch (message.type) {
			case 'ready':
				await this.refreshState();
				return;
			case 'submit_prompt':
				await this.routeFreeText(message.text ?? '');
				return;
			case 'answer_clarification':
				await this.applyAction(this.buildControllerAction({
					type: 'answer_clarification',
					text: message.text ?? '',
				}));
				return;
			case 'set_permission_scope':
				if (!message.permissionScope) {
					return;
				}
				await this.applyAction(this.buildControllerAction({
					type: 'set_permission_scope',
					permission_scope: message.permissionScope,
				}));
				return;
			case 'decline_permission':
				await this.applyAction(this.buildControllerAction({ type: 'decline_permission' }));
				return;
			case 'interrupt_run':
				await this.applyAction(this.buildControllerAction({ type: 'interrupt_run' }));
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
			error instanceof Error ? error.message : fallbackBody
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
			padding-top: 4px;
		}

		.progress-list {
			margin-top: 2px;
			padding-left: 16px;
			font-size: 12px;
		}

		.progress-bullet {
			color: var(--muted);
		}

		.progress-bullet.is-done {
			color: var(--text);
		}

		.progress-bullet.is-active,
		.progress-bullet.is-waiting {
			color: var(--accent);
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
			if (snapshot.transportState === 'connected' && !stale) {
				return 'Ready';
			}
			return 'Attention';
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
				chips.push('<span class="pill is-primary">' + escapeHtml(snapshot.permissionScope) + '</span>');
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

		function ensureForegroundRequest(userText, hint) {
			if (!ui.foregroundRequest) {
				ui.foregroundRequest = {
					id: 'foreground-' + String(Date.now()),
					userText: userText || '',
					status: 'live',
					hint: hint || '',
					bullets: [],
				};
			}
			if (userText) {
				ui.foregroundRequest.userText = userText;
			}
			if (hint) {
				ui.foregroundRequest.hint = hint;
			}
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
			if (hint) {
				ui.foregroundRequest.hint = hint;
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
			if (hint) {
				ui.foregroundRequest.hint = hint;
			}
		}

		function freezeForegroundRequest(label, state, hint) {
			if (!ui.foregroundRequest) {
				return;
			}
			if (label) {
				replaceForegroundTail(label, state || 'done', hint);
			} else if (ui.foregroundRequest.bullets.length > 0) {
				ui.foregroundRequest.bullets[ui.foregroundRequest.bullets.length - 1].state = state || 'done';
			}
			ui.foregroundRequest.status = 'frozen';
			if (hint) {
				ui.foregroundRequest.hint = hint;
			}
		}

		function latestRequestError() {
			if (!model) {
				return undefined;
			}
			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (item.type === 'error') {
					return item;
				}
			}
			return undefined;
		}

		function syncForegroundRequestFromModel() {
			if (!ui.foregroundRequest || !model) {
				return;
			}

			const snapshot = model.snapshot;
			const latestError = latestRequestError();
			if (latestError) {
				freezeForegroundRequest(latestError.title, 'failed', 'Corgi needs your input before this can continue.');
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

			if (snapshot.runState === 'running') {
				replaceForegroundTail('Execution started', 'active', 'Corgi is actively working on this request.');
				return;
			}

			const latestItem = model.feed[model.feed.length - 1];
			if (latestItem?.type === 'actor_event') {
				freezeForegroundRequest('Governor responded', 'done', 'Corgi finished this request.');
				return;
			}

			if (model.acceptedIntakeSummary) {
				freezeForegroundRequest('Completed', 'done', 'Corgi finished this request.');
				return;
			}
		}

		function composerMode() {
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
					'<span class="status-dot ' + (stale ? 'is-stale' : '') + '"></span>' +
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

			if (snapshot.pendingPermissionRequest) {
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
			if (item.type === 'error') {
				return (
					'<article class="message error">' +
						'<div class="message-label">Error</div>' +
						'<div class="message-body">' + escapeHtml(item.title) + '</div>' +
						(item.body ? '<div class="activity-summary">' + escapeHtml(item.body) + '</div>' : '') +
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
					'<div class="message-label">Corgi</div>' +
					'<div class="message-body">' + escapeHtml(item.body || item.title) + '</div>' +
					(isMeaningfulMilestone(item)
						? renderArtifactQuickAction(milestoneArtifact(item))
						: '') +
					renderDetails(item) +
				'</article>'
			);
		}

		function renderForegroundRequest() {
			if (!ui.foregroundRequest) {
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
			const bulletMarkup =
				bullets.length > 0
					? '<ul class="detail-list progress-list">' +
						bullets
							.map(
								(bullet) =>
									'<li class="progress-bullet is-' +
									escapeHtml(bullet.state || 'active') +
									'">' +
									escapeHtml(bullet.label) +
									'</li>'
							)
							.join('') +
					  '</ul>'
					: '';

			return (
				(ui.foregroundRequest.userText && !hasAuthoritativeUserEcho
					? '<article class="message user">' +
						'<div class="message-body">' + escapeHtml(ui.foregroundRequest.userText) + '</div>' +
					  '</article>'
					: '') +
				'<article class="message assistant is-informational progress-cluster ' +
					(ui.foregroundRequest.status === 'frozen' ? 'is-frozen' : '') +
				'">' +
					'<div class="message-label">Corgi</div>' +
					bulletMarkup +
					(ui.foregroundRequest.hint
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
			const busy = Boolean(ui.foregroundRequest && ui.foregroundRequest.status === 'live');
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
		}

		function handleSubmit(event) {
			event.preventDefault();
			const text = ui.draft.trim();
			if (!text) {
				return;
			}

			rememberPrompt(text);
			resetPromptHistoryNavigation();
			ui.foregroundRequest = undefined;
			ensureForegroundRequest(text, 'Model clarifying...');
			appendForegroundBullet('Model clarifying', 'active', 'Model clarifying...');
			vscode.postMessage({ type: 'submit_prompt', text });

			ui.draft = '';
			persistUiState();
			renderFeed();
			renderComposer();
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
		});

		document.addEventListener('click', (event) => {
			const target = event.target.closest('button[data-action]');
			const clarificationTarget = event.target.closest('button[data-clarification-answer]');
			if (clarificationTarget) {
				const clarificationAnswer = clarificationTarget.dataset.clarificationAnswer;
				if (clarificationAnswer) {
					appendForegroundBullet('Clarification received', 'done', 'Applying your clarification...');
					appendForegroundBullet('Continuing request', 'active', 'Applying your clarification...');
					renderFeed();
					renderComposer();
					vscode.postMessage({
						type: 'answer_clarification',
						text: clarificationAnswer,
					});
				}
				return;
			}
			if (!target) {
				return;
			}

			const action = target.dataset.action;
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
					appendForegroundBullet(
						scope
							? 'Permission confirmed: ' + scope.charAt(0).toUpperCase() + scope.slice(1)
							: 'Permission confirmed',
						'done',
						'Applying your permission choice...'
					);
					appendForegroundBullet('Continuing request', 'active', 'Applying your permission choice...');
					renderFeed();
					renderComposer();
					vscode.postMessage({ type: 'set_permission_scope', permissionScope: scope });
					return;
				}
				if (action === 'decline_permission') {
					appendForegroundBullet('Permission declined', 'failed', 'This request will not continue.');
					freezeForegroundRequest(undefined, 'failed', 'This request will not continue.');
				} else {
					appendForegroundBullet('Stop requested', 'waiting', 'Requesting stop...');
				}
				renderFeed();
				renderComposer();
				vscode.postMessage({ type: action });
			}
		});

		window.addEventListener('message', (event) => {
			const message = event.data;
			if (message?.type !== 'state') {
				return;
			}

			model = message.payload;
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
