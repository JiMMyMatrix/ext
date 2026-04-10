import * as vscode from 'vscode';
import {
	appendError,
	applyModelAction,
	createInitialModel,
	getArtifactById,
	type ExecutionWindowModel,
} from './phase1Model';

export const OPEN_EXECUTION_WINDOW_COMMAND = 'ext.openExecutionWindow';
export const EXECUTION_WINDOW_CONTAINER_ID = 'extExecutionWindowSidebar';
export const EXECUTION_WINDOW_VIEW_ID = 'ext.executionWindowView';

type WebviewMessage =
	| { type: 'ready' }
	| { type: 'submit_prompt'; text?: string }
	| { type: 'answer_clarification'; text?: string }
	| { type: 'approve' }
	| { type: 'decline_or_hold' }
	| { type: 'interrupt_run' }
	| { type: 'reconnect' }
	| { type: 'open_artifact'; artifactId?: string }
	| { type: 'reveal_artifact_path'; artifactId?: string }
	| { type: 'copy_artifact_path'; artifactId?: string };

export class ExecutionWindowPanel implements vscode.WebviewViewProvider {
	public static register(context: vscode.ExtensionContext): ExecutionWindowPanel {
		const provider = new ExecutionWindowPanel();

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
	private view: vscode.WebviewView | undefined;
	private readonly workspaceRoot: vscode.Uri | undefined;
	private readonly disposables: vscode.Disposable[] = [];
	private readonly webviewDisposables: vscode.Disposable[] = [];

	private constructor() {
		this.workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
		this.model = createInitialModel();
	}

	public async createOrShow() {
		await this.executeQuietly(`workbench.view.extension.${EXECUTION_WINDOW_CONTAINER_ID}`);
		await this.executeQuietly(`${EXECUTION_WINDOW_VIEW_ID}.focus`);
		this.view?.show?.(true);
		this.postState();
	}

	public resolveWebviewView(webviewView: vscode.WebviewView) {
		this.disposeWebviewListeners();
		this.view = webviewView;
		this.view.title = 'Codex';
		this.view.webview.options = {
			enableScripts: true,
		};
		this.view.webview.html = this.getHtml(this.view.webview);
		this.webviewDisposables.push(
			this.view.webview.onDidReceiveMessage((message) => {
				void this.handleMessage(message as WebviewMessage);
			})
		);
		this.postState();
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

	private async executeQuietly(command: string) {
		try {
			await vscode.commands.executeCommand(command);
		} catch {
			// Focus commands can be unavailable in some test hosts.
		}
	}

	private postState() {
		void this.view?.webview.postMessage({
			type: 'state',
			payload: this.model,
		});
	}

	private applyAction(action: Parameters<typeof applyModelAction>[1]) {
		this.model = applyModelAction(this.model, action);
		this.postState();
	}

	private async handleMessage(message: WebviewMessage) {
		switch (message.type) {
			case 'ready':
				this.postState();
				return;
			case 'submit_prompt':
				this.applyAction({
					type: 'submit_prompt',
					text: message.text ?? '',
				});
				return;
			case 'answer_clarification':
				this.applyAction({
					type: 'answer_clarification',
					text: message.text ?? '',
				});
				return;
			case 'approve':
				this.applyAction({ type: 'approve' });
				return;
			case 'decline_or_hold':
				this.applyAction({ type: 'decline_or_hold' });
				return;
			case 'interrupt_run':
				this.applyAction({ type: 'interrupt_run' });
				return;
			case 'reconnect':
				this.applyAction({ type: 'reconnect' });
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

		const artifact = getArtifactById(this.model, artifactId);
		if (!artifact) {
			this.pushLocalError(
				'Artifact unavailable',
				`The artifact "${artifactId}" could not be found in the current execution window state.`
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

	private pushLocalError(title: string, body: string, details?: string[]) {
		this.model = appendError(this.model, title, body, details);
		this.postState();
	}

	private getHtml(webview: vscode.Webview): string {
		const nonce = getNonce();

		return `<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta
		http-equiv="Content-Security-Policy"
		content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';"
	/>
	<meta name="viewport" content="width=device-width, initial-scale=1.0" />
	<title>Codex</title>
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

		.header-row {
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 10px;
		}

		.brand {
			display: inline-flex;
			align-items: center;
			gap: 8px;
			min-width: 0;
		}

		.brand-mark {
			width: 22px;
			height: 22px;
			display: grid;
			place-items: center;
			border: 1px solid var(--line);
			border-radius: 7px;
			color: var(--muted);
			font-weight: 700;
			font-size: 11px;
		}

		.header-title {
			margin: 0;
			font-size: 13px;
			font-weight: 600;
			white-space: nowrap;
			overflow: hidden;
			text-overflow: ellipsis;
		}

		.header-status {
			display: inline-flex;
			align-items: center;
			gap: 6px;
			color: var(--muted);
			font-size: 11px;
			white-space: nowrap;
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

		.request-marker {
			color: var(--muted);
			font-size: 12px;
			border-left: 2px solid var(--line);
			padding-left: 8px;
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
			gap: 6px;
			padding: 8px;
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
				<textarea
					id="composerInput"
					placeholder="Ask Codex to work on this repo..."
				></textarea>
				<div class="composer-footer">
					<div class="composer-hint" id="composerHint">Enter to send, Shift+Enter for newline</div>
					<button type="submit" id="composerSubmitButton">Send</button>
				</div>
			</form>
		</footer>
	</div>
	<div class="loading" id="loadingState">Loading Codex...</div>
	<script nonce="${nonce}">
		const vscode = acquireVsCodeApi();
		const persisted = vscode.getState() ?? {
			draft: '',
			expandedIds: [],
			scrollTop: 0,
		};

		let model = undefined;
		let hasRendered = false;
		const ui = {
			draft: typeof persisted.draft === 'string' ? persisted.draft : '',
			expandedIds: new Set(Array.isArray(persisted.expandedIds) ? persisted.expandedIds : []),
			scrollTop: typeof persisted.scrollTop === 'number' ? persisted.scrollTop : 0,
		};

		const app = document.getElementById('app');
		const loadingState = document.getElementById('loadingState');
		const headerContent = document.getElementById('headerContent');
		const feed = document.getElementById('feed');
		const actionBand = document.getElementById('actionBand');
		const composerForm = document.getElementById('composerForm');
		const composerInput = document.getElementById('composerInput');
		const composerHint = document.getElementById('composerHint');
		const composerSubmitButton = document.getElementById('composerSubmitButton');

		function persistUiState() {
			vscode.setState({
				draft: ui.draft,
				expandedIds: Array.from(ui.expandedIds),
				scrollTop: feed.scrollTop,
			});
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

		function needsReconnect(snapshot) {
			return snapshot.transportState !== 'connected' || isSnapshotStale(snapshot);
		}

		function canInterrupt(snapshot) {
			if (snapshot.pendingInterrupt) {
				return false;
			}

			return snapshot.currentActor === 'executor' && snapshot.currentStage === 'running';
		}

		function composerMode() {
			if (model?.activeClarification) {
				return {
					placeholder:
						model.activeClarification.placeholder ||
						'Answer the clarification so Codex can continue.',
					hint: 'Answering clarification. Enter to send.',
					buttonLabel: 'Answer',
				};
			}

			return {
				placeholder: 'Ask Codex to work on this repo...',
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
			const statusLabel =
				snapshot.transportState === 'connected' && !stale
					? 'Ready'
					: 'Reconnect';

			headerContent.innerHTML =
				'<div class="header-row">' +
					'<div class="brand">' +
						'<div class="brand-mark">C</div>' +
						'<h1 class="header-title">Codex</h1>' +
					'</div>' +
					'<div class="header-status">' +
						'<span class="status-dot ' + (stale ? 'is-stale' : '') + '"></span>' +
						'<span>' + escapeHtml(statusLabel) + '</span>' +
					'</div>' +
				'</div>';
		}

		function renderActionBand() {
			if (!model) {
				return;
			}

			const snapshot = model.snapshot;
			const cards = [];

			if (model.activeClarification) {
				cards.push(
					'<section class="action-card">' +
						'<h2>' + escapeHtml(model.activeClarification.title) + '</h2>' +
						'<p>' + escapeHtml(model.activeClarification.body) + '</p>' +
					'</section>'
				);
			}

			if (snapshot.pendingApproval) {
				cards.push(
					'<section class="action-card">' +
						'<h2>' + escapeHtml(snapshot.pendingApproval.title) + '</h2>' +
						'<p>' + escapeHtml(snapshot.pendingApproval.body) + '</p>' +
						'<div class="card-actions">' +
							'<button type="button" data-action="approve">Approve</button>' +
							'<button type="button" class="secondary" data-action="decline_or_hold">Hold</button>' +
						'</div>' +
					'</section>'
				);
			}

			if (snapshot.pendingInterrupt) {
				cards.push(
					'<section class="action-card">' +
						'<h2>' + escapeHtml(snapshot.pendingInterrupt.title) + '</h2>' +
						'<p>' + escapeHtml(snapshot.pendingInterrupt.body) + '</p>' +
					'</section>'
				);
			} else if (canInterrupt(snapshot)) {
				cards.push(
					'<section class="action-card">' +
						'<h2>Running</h2>' +
						'<p>Codex is working. You can request an interrupt if needed.</p>' +
						'<div class="card-actions">' +
							'<button type="button" class="secondary" data-action="interrupt_run">Interrupt</button>' +
						'</div>' +
					'</section>'
				);
			}

			if (needsReconnect(snapshot)) {
				cards.push(
					'<section class="action-card">' +
						'<h2>Reconnect</h2>' +
						'<p>The latest snapshot is stale or the transport is degraded.</p>' +
						'<div class="card-actions">' +
							'<button type="button" class="secondary" data-action="reconnect">Reconnect</button>' +
						'</div>' +
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

		function renderArtifactActions(item) {
			if (item.type !== 'artifact_reference') {
				return '';
			}

			return (
				'<div class="inline-actions">' +
					'<button type="button" class="secondary" data-action="open_artifact" data-artifact-id="' + escapeHtml(item.artifact.id) + '">Open</button>' +
					'<button type="button" class="ghost" data-action="reveal_artifact_path" data-artifact-id="' + escapeHtml(item.artifact.id) + '">Reveal</button>' +
					'<button type="button" class="ghost" data-action="copy_artifact_path" data-artifact-id="' + escapeHtml(item.artifact.id) + '">Copy path</button>' +
				'</div>'
			);
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

		function renderRequestMarker(item) {
			return (
				'<article class="request-marker">' +
					escapeHtml(item.title) +
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
					'<div class="message-label">Codex</div>' +
					'<div class="message-body">' + escapeHtml(item.body || item.title) + '</div>' +
					renderDetails(item) +
				'</article>'
			);
		}

		function renderFeedItem(item) {
			if (
				item.type === 'clarification_request' ||
				item.type === 'approval_request' ||
				item.type === 'interrupt_request'
			) {
				return renderRequestMarker(item);
			}

			if (item.activity || item.type === 'artifact_reference') {
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

			const cards = model.feed.map(renderFeedItem);

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
			composerInput.placeholder = mode.placeholder;
			composerHint.textContent = mode.hint;
			composerSubmitButton.textContent = mode.buttonLabel;
			composerInput.value = ui.draft;
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

			if (model?.activeClarification) {
				vscode.postMessage({ type: 'answer_clarification', text });
			} else {
				vscode.postMessage({ type: 'submit_prompt', text });
			}

			ui.draft = '';
			persistUiState();
			renderComposer();
		}

		composerForm.addEventListener('submit', handleSubmit);
		composerInput.addEventListener('input', (event) => {
			ui.draft = event.target.value;
			persistUiState();
		});
		composerInput.addEventListener('keydown', (event) => {
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
				action === 'approve' ||
				action === 'decline_or_hold' ||
				action === 'interrupt_run' ||
				action === 'reconnect'
			) {
				vscode.postMessage({ type: action });
			}
		});

		window.addEventListener('message', (event) => {
			const message = event.data;
			if (message?.type !== 'state') {
				return;
			}

			model = message.payload;
			render();
		});

		setInterval(() => {
			if (model) {
				renderHeader();
				renderActionBand();
			}
		}, 5000);

		vscode.postMessage({ type: 'ready' });
	</script>
</body>
</html>`;
	}
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
