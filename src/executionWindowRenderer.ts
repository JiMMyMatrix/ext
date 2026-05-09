import { executionWindowStyles } from './executionWindowStyles';

export type TestWindowAutoStepMode = 'off' | 'plan' | 'execute';

export function getExecutionWindowHtml(
	cspSource: string,
	nonce: string = getNonce(),
	resetPersistedState: boolean = false,
	testAutoStepMode: TestWindowAutoStepMode = 'off'
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
	<style>${executionWindowStyles}</style>
</head>
<body>
	<div class="app" id="app" hidden>
		<header class="header">
			<div class="goal-strip" id="headerContent"></div>
		</header>
		<main class="feed" id="feed"></main>
		<footer class="footer">
			<form class="composer" id="composerForm">
				<div class="composer-context" id="composerContext" hidden></div>
				<div class="composer-actions" id="composerActions" hidden></div>
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
		const testWindowAutoStepMode = ${JSON.stringify(testAutoStepMode)};
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
			lastRuntimeTimings: [],
		};
		const testWindowAutoStepState = {
			timer: undefined,
			appliedKeys: new Set(),
		};

		const app = document.getElementById('app');
		const loadingState = document.getElementById('loadingState');
		const headerContent = document.getElementById('headerContent');
		const feed = document.getElementById('feed');
		const composerForm = document.getElementById('composerForm');
		const composerContext = document.getElementById('composerContext');
		const composerActions = document.getElementById('composerActions');
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
				goalStrip: compactText(headerContent.innerText || headerContent.textContent || '', 600),
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
				actions: collectTextRows(composerActions, 'button'),
				messages: collectTextRows(feed, '.message, .activity-row, .turn-divider, .feed-empty'),
				transcript: collectTextRows(feed, '.message'),
				activity: collectTextRows(feed, '.activity-row'),
				activityOverflow: collectTextRows(feed, '.activity-overflow'),
				progress: collectTextRows(feed, '.progress-bullet, .activity-summary'),
				detailsHidden: Array.from(
					feed.querySelectorAll('details:not([open]), .inline-actions button')
				).length,
				runtimeTimings: cloneForSnapshot(
					ui.foregroundRequest?.runtimeTimings || ui.lastRuntimeTimings || []
				),
				composer: {
					placeholder: compactText(composerInput.placeholder, 240),
					hint: compactText(composerHint.innerText || composerHint.textContent || '', 300),
					button: compactText(composerSubmitButton.innerText || composerSubmitButton.textContent || '', 120),
					disabled: Boolean(composerInput.disabled),
					context: compactText(composerContext.innerText || composerContext.textContent || '', 300),
					draftLength: ui.draft.length,
				},
				autoStep: {
					mode: testWindowAutoStepMode,
					appliedCount: testWindowAutoStepState.appliedKeys.size,
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

		function testWindowAutoStepsEnabled() {
			return testWindowAutoStepMode === 'plan' || testWindowAutoStepMode === 'execute';
		}

		function scheduleTestWindowAutoStep(reason) {
			if (!testWindowAutoStepsEnabled() || !model) {
				return;
			}

			clearTimeout(testWindowAutoStepState.timer);
			testWindowAutoStepState.timer = setTimeout(() => {
				runTestWindowAutoStep(reason);
			}, 350);
		}

		function clickTestWindowAutoButton(button, key, reason) {
			if (!button || button.disabled || testWindowAutoStepState.appliedKeys.has(key)) {
				return false;
			}

			testWindowAutoStepState.appliedKeys.add(key);
			button.click();
			scheduleWebviewSnapshot('auto_step_' + reason);
			return true;
		}

		function chooseTestWindowClarificationButton() {
			const buttons = Array.from(
				composerActions.querySelectorAll('button[data-clarification-answer]')
			);
			return (
				buttons.find((button) => /architecture/i.test(button.textContent || '')) ||
				buttons[0]
			);
		}

		function chooseTestWindowPermissionScope(permissionRequest) {
			const allowedScopes = Array.isArray(permissionRequest?.allowedScopes)
				? permissionRequest.allowedScopes
				: ['observe', 'plan', 'execute'];
			const recommendedScope = permissionRequest?.recommendedScope;
			if (
				testWindowAutoStepMode === 'execute' &&
				recommendedScope === 'execute' &&
				allowedScopes.includes('execute')
			) {
				return 'execute';
			}
			if (allowedScopes.includes('plan')) {
				return 'plan';
			}
			if (recommendedScope && allowedScopes.includes(recommendedScope)) {
				return recommendedScope;
			}
			return allowedScopes[0];
		}

		function runTestWindowAutoStep(reason) {
			if (!testWindowAutoStepsEnabled() || !model) {
				return;
			}

			const snapshot = model.snapshot || {};
			if (model.activeClarification?.contextRef) {
				const key = 'clarification:' + model.activeClarification.contextRef;
				if (
					clickTestWindowAutoButton(
						chooseTestWindowClarificationButton(),
						key,
						'clarification'
					)
				) {
					return;
				}
			}

			const permissionRequest = snapshot.pendingPermissionRequest;
			if (permissionRequest?.contextRef) {
				const scope = chooseTestWindowPermissionScope(permissionRequest);
				const key = 'permission:' + permissionRequest.contextRef + ':' + scope;
				const button = composerActions.querySelector(
					'button[data-action="set_permission_scope"][data-permission-scope="' + scope + '"]'
				);
				if (clickTestWindowAutoButton(button, key, 'permission_' + scope)) {
					return;
				}
			}

			if (
				testWindowAutoStepMode === 'execute' &&
				snapshot &&
				isPlanReady(snapshot) &&
				model.planReadyRequest?.contextRef
			) {
				const key = 'execute_plan:' + model.planReadyRequest.contextRef;
				clickTestWindowAutoButton(
					composerActions.querySelector('button[data-action="execute_plan"]'),
					key,
					'execute_plan'
				);
			}
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

		function isDispatchQueued(snapshot) {
			return Boolean(snapshot.currentStage === 'dispatch_queued' || snapshot.runState === 'queued');
		}

		function isExecutorCompleted(snapshot) {
			return snapshot.currentStage === 'executor_completed';
		}

		function isReviewerCompleted(snapshot) {
			return snapshot.currentStage === 'reviewer_completed';
		}

		function isGovernorDecisionRecorded(snapshot) {
			return snapshot.currentStage === 'governor_decision_recorded';
		}

			function retainOptimisticHidesUntilAuthoritativeChange() {
				// Same-context action surfaces should not reappear on a timer after
				// the user clicks them. They clear only when authoritative state
				// removes or replaces that context.
			}

			function clearOptimisticActionHides() {
				ui.pendingPermissionContextRef = undefined;
				ui.pendingPermissionHiddenAt = undefined;
				ui.pendingPlanContextRef = undefined;
				ui.pendingPlanHiddenAt = undefined;
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
			if (snapshot.currentStage === 'plan_executing') {
				return 'Running';
			}
			if (isDispatchQueued(snapshot)) {
				return 'Ready to write';
			}
			if (isGovernorDecisionRecorded(snapshot)) {
				return 'Finalized';
			}
			if (isReviewerCompleted(snapshot)) {
				return 'Done';
			}
			if (isExecutorCompleted(snapshot)) {
				return 'Done';
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

		function goalStepLabel(snapshot) {
			const activeParallel =
				typeof snapshot.activeParallelDispatchCount === 'number' &&
				snapshot.activeParallelDispatchCount > 1
					? snapshot.activeParallelDispatchCount
					: 0;
			if (activeParallel) {
				return activeParallel + ' tasks running';
			}
			const attempt =
				typeof snapshot.currentAttemptNumber === 'number' && snapshot.currentAttemptNumber > 0
					? ' · Attempt ' + snapshot.currentAttemptNumber
					: '';
			const nextAttempt =
				typeof snapshot.currentAttemptNumber === 'number' && snapshot.currentAttemptNumber > 0
					? ' · Attempt ' + (snapshot.currentAttemptNumber + 1)
					: '';
			if (model?.activeClarification) {
				return 'Clarification needed';
			}
			if (snapshot.pendingPermissionRequest) {
				return 'Permission needed';
			}
			if (snapshot.pendingInterrupt) {
				return 'Stop requested';
			}
			if (snapshot.currentStage === 'semantic_intake') {
				return 'Understanding request';
			}
			if (isPlanReady(snapshot)) {
				return 'Plan ready' + nextAttempt;
			}
			if (snapshot.currentStage === 'plan_executing') {
				return 'Writing' + attempt;
			}
			if (isDispatchQueued(snapshot)) {
				return 'Ready to write' + attempt;
			}
			if (isGovernorDecisionRecorded(snapshot)) {
				if (snapshot.latestGovernorDecision) {
					return 'Final decision ' + summarizeToken(snapshot.latestGovernorDecision, '') + attempt;
				}
				return 'Final decision recorded' + attempt;
			}
			if (isReviewerCompleted(snapshot)) {
				if (snapshot.latestReviewVerdict) {
					return 'Check ' + summarizeToken(snapshot.latestReviewVerdict, '') + attempt;
				}
				return 'Checked result' + attempt;
			}
			if (isExecutorCompleted(snapshot)) {
				return 'Changes written' + attempt;
			}
			if (snapshot.currentActor === 'governor' && snapshot.runState === 'running') {
				return 'Planning';
			}
			if (snapshot.currentActor === 'executor') {
				return 'Writing' + attempt;
			}
			if (snapshot.currentActor === 'reviewer') {
				return 'Checking' + attempt;
			}
			if (snapshot.runState === 'running') {
				return 'Corgi is working';
			}
			return snapshot.task ? 'Ready to continue' : 'Ready';
		}

		function goalDisplayState(snapshot, stale) {
			return {
				title: compactText(railTitle(snapshot), 96),
				step: goalStepLabel(snapshot),
				status: statusLabel(snapshot, stale),
			};
		}

		function goalDetailLabel(snapshot) {
			const details = [];
			const actor = actorSummary(snapshot);
			const stage = stageSummary(snapshot);
			if (actor) {
				details.push('Actor: ' + actor);
			}
			if (stage) {
				details.push('Stage: ' + stage);
			}
			return details.join(' · ');
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
			switch (snapshot.currentStage) {
				case 'dispatch_queued':
					return 'Ready to write';
				case 'plan_executing':
					return 'Writing';
				case 'reviewer_completed':
					return 'Checked result';
				case 'permission_needed':
					return 'Permission needed';
				case 'semantic_intake':
					return 'Understanding request';
				case 'executor_completed':
					return 'Changes written';
				case 'governor_decision_recorded':
					return 'Finalized';
				case 'plan_ready':
					return 'Plan ready';
				default:
					return summarizeToken(snapshot.currentStage, '');
			}
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
				if (item.title === 'Dispatch queued' || item.title === 'Executor starting') {
					return false;
				}
				return item.title !== 'Ready when you are' && item.title !== 'Accepted and ready';
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

			function runtimeErgonomics() {
				return model?.runtimeErgonomics && typeof model.runtimeErgonomics === 'object'
					? model.runtimeErgonomics
					: {};
			}

			function runtimeActivityForItem(item) {
				const activities = Array.isArray(runtimeErgonomics().activities)
					? runtimeErgonomics().activities
					: [];
				return activities.find((activity) => activity.sourceRef === item.id);
			}

			function lifecycleActivitySummaryKey(item) {
				const title = String(item.title || '').trim().toLowerCase();
				if (title === 'dispatch queued') {
					return 'dispatch_queued';
				}
				if (title === 'executor starting') {
					return 'executor_running';
				}
				if (title === 'executor completed') {
					return 'executor_completed';
				}
				if (title === 'reviewer completed') {
					return 'reviewer_completed';
				}
				if (title === 'reviewer requested changes') {
					return 'reviewer_request_changes';
				}
				if (title === 'governor decision recorded') {
					return 'governor_decision_recorded';
				}
				return undefined;
			}

			function summaryForActivityKey(summaryKey, summaryArgs) {
				if (summaryKey === 'parallel_running') {
					const count = Number(summaryArgs?.count || 0);
					return count > 1 ? count + ' tasks running' : 'Writing';
				}
				switch (summaryKey) {
					case 'semantic_intake':
						return 'Understanding request';
					case 'governor_drafting_plan':
						return 'Drafting plan';
					case 'dispatch_queued':
						return 'Ready to write';
					case 'executor_running':
						return 'Writing';
					case 'executor_completed':
						return 'Changes written';
					case 'reviewer_running':
						return 'Checking';
					case 'reviewer_request_changes':
						return 'Changes requested';
					case 'reviewer_completed':
						return 'Checked result';
					case 'plan_revision':
						return 'Revising plan';
					case 'advisor_consulting':
						return 'Consulting advisor';
					case 'governor_decision_recorded':
						return 'Final decision recorded';
					default:
						return String(summaryKey || '').replace(/_/g, ' ');
				}
			}

			function isAdvisorActivityItem(item) {
				const text = [
					item.source_actor,
					item.source_layer,
					item.title,
					item.body,
				].join('\\n').toLowerCase();
				return text.includes('advisor') || text.includes('consult');
			}

			function runtimeFeedItemVisibility(item) {
				const ergonomics = runtimeErgonomics();
				const lists = [
					['transcript', ergonomics.transcriptFeedItemIds],
					['activity', ergonomics.activityFeedItemIds],
					['detail', ergonomics.detailFeedItemIds],
					['internal', ergonomics.internalFeedItemIds],
				];
				for (const [visibility, ids] of lists) {
					if (Array.isArray(ids) && ids.includes(item.id)) {
						return visibility;
					}
				}
				return undefined;
			}

			function fallbackFeedItemVisibility(item) {
				if (item.type === 'artifact_reference' || item.type === 'shell_event') {
					return 'detail';
				}
				if (item.type === 'user_message' && item.turn_type === 'permission_action') {
					return 'internal';
				}
				if (
					item.type === 'actor_event' &&
					item.source_actor === 'governor'
				) {
					return 'transcript';
				}
				if (item.type === 'user_message') {
					return 'transcript';
				}
				if (
					item.activity ||
					lifecycleActivitySummaryKey(item) ||
					(item.type === 'actor_event' && item.source_actor !== 'governor') ||
					isAdvisorActivityItem(item)
				) {
					return 'activity';
				}
				if (item.type === 'permission_request') {
					const itemContextRef = item.presentation_args?.contextRef;
					const activeContextRef = model?.snapshot.pendingPermissionRequest?.contextRef;
					if (typeof itemContextRef === 'string' && typeof activeContextRef === 'string') {
						return itemContextRef === activeContextRef ? 'transcript' : 'internal';
					}
					return Boolean(
						model?.snapshot.pendingPermissionRequest &&
						item.body === model.snapshot.pendingPermissionRequest.body
					) ? 'transcript' : 'internal';
				}
				if (item.type === 'clarification_request') {
					const itemContextRef = item.presentation_args?.contextRef;
					const activeContextRef = model?.activeClarification?.contextRef;
					if (typeof itemContextRef === 'string' && typeof activeContextRef === 'string') {
						return itemContextRef === activeContextRef ? 'transcript' : 'internal';
					}
					return Boolean(
						model?.activeClarification &&
						item.body === model.activeClarification.body
					) ? 'transcript' : 'internal';
				}
				if (item.type === 'system_status' && !isMeaningfulMilestone(item)) {
					return 'internal';
				}
				return 'transcript';
			}

			function feedItemVisibility(item) {
				return runtimeFeedItemVisibility(item) || fallbackFeedItemVisibility(item);
			}

			function shouldRenderInTranscript(item) {
				return feedItemVisibility(item) === 'transcript';
			}

			function runtimeGoalDisplay(snapshot, stale) {
				const goal = runtimeErgonomics().goal;
				if (!goal || typeof goal !== 'object') {
					return goalDisplayState(snapshot, stale);
				}
				return {
					title: compactText(goal.goal || railTitle(snapshot), 96),
					step: goal.step || goalStepLabel(snapshot),
					status: goal.status || statusLabel(snapshot, stale),
				};
			}

			function runtimeActionLabel(actionId, fallbackLabel) {
				const ergonomics = runtimeErgonomics();
				const candidates = [
					ergonomics.primaryAction,
					...(Array.isArray(ergonomics.secondaryActions)
						? ergonomics.secondaryActions
						: []),
				];
				const match = candidates.find((action) => action?.id === actionId);
				return match?.label || fallbackLabel;
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

		function renderArtifactQuickButton(artifact) {
			if (!artifact) {
				return '';
			}

			return (
				'<button type="button" class="secondary" data-action="open_artifact" data-artifact-id="' +
				escapeHtml(artifact.id || artifact.path) +
				'">View source</button>'
			);
		}

		function renderSourceActionForItem(item) {
			const artifact = milestoneArtifact(item);
			if (!artifact) {
				return '';
			}
			return (
				'<div class="inline-actions">' +
					renderArtifactQuickButton(artifact) +
				'</div>'
			);
		}

		function renderContextChips(snapshot, limit) {
			const chips = [];
			if (snapshot.permissionScope && snapshot.permissionScope !== 'unset') {
				chips.push(
					'<span class="pill is-status">Scope: ' +
						escapeHtml(snapshot.permissionScope.charAt(0).toUpperCase() + snapshot.permissionScope.slice(1)) +
					'</span>'
				);
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
			ui.lastRuntimeTimings = [];
			ui.foregroundRequest = {
				id: 'foreground-' + String(Date.now()),
				requestKey: requestKey || nextForegroundRequestKey(),
				userText: userText || '',
				status: 'live',
				hint: hint || '',
				draftPreview: '',
				draftPreviewTarget: '',
				runtimeTimings: [],
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
			if (
				Array.isArray(ui.foregroundRequest?.runtimeTimings) &&
				ui.foregroundRequest.runtimeTimings.length > 0
			) {
				ui.lastRuntimeTimings = ui.foregroundRequest.runtimeTimings;
			}
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
			const isPlan = event.runtimeKind === 'plan';
			const beats = isSemanticIntake
				? [
					[12000, 'Still understanding request', 'Still understanding the request...'],
					[30000, 'Still checking workflow state', 'Still checking intent and workflow state...'],
				]
				: isPlan
					? [
						[12000, 'Still drafting plan', 'Still drafting the plan...'],
						[30000, 'Shaping the plan', 'Still shaping the plan checkpoint...'],
						[60000, 'Taking a deeper planning pass', 'This model can take a little longer.'],
					]
				: [
					[12000, 'Still waiting for reply', 'Still waiting for a reply...'],
					[30000, 'Still thinking', 'Still thinking through the plan...'],
					[60000, 'Taking a deeper pass', 'This model can take a little longer.'],
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

		function runtimeTimingFromEvent(event) {
			const timing = {
				stage: String(event.stage || ''),
				message: compactText(event.message || '', 180),
				recordedAt: new Date().toISOString(),
			};
			if (typeof event.elapsedMs === 'number') {
				timing.elapsedMs = event.elapsedMs;
			}
			if (typeof event.totalElapsedMs === 'number') {
				timing.totalElapsedMs = event.totalElapsedMs;
			}
			if (typeof event.promptChars === 'number') {
				timing.promptChars = event.promptChars;
			}
			if (event.modelName) {
				timing.modelName = String(event.modelName);
			}
			if (event.reasoning) {
				timing.reasoning = String(event.reasoning);
			}
			if (event.emittedAt) {
				const emittedAt = Date.parse(event.emittedAt);
				if (!Number.isNaN(emittedAt)) {
					timing.uiLagMs = Math.max(0, Date.now() - emittedAt);
				}
			}
			return timing;
		}

		function recordRuntimeTiming(event) {
			if (!runtimeProgressMatchesForeground(event) || !ui.foregroundRequest) {
				return;
			}
			ui.foregroundRequest.runtimeTimings = [
				...(Array.isArray(ui.foregroundRequest.runtimeTimings)
					? ui.foregroundRequest.runtimeTimings
					: []),
				runtimeTimingFromEvent(event),
			].slice(-16);
			ui.lastRuntimeTimings = ui.foregroundRequest.runtimeTimings;
		}

		function applyRuntimeProgress(event) {
			if (!runtimeProgressMatchesForeground(event)) {
				return;
			}
			recordRuntimeTiming(event);
			if (event.stage === 'governor_runtime_requested') {
				ui.foregroundRequest.runtimeRequestId = event.runtimeRequestId || '';
				replaceForegroundTail(
					'Preparing request',
					'active',
					'Preparing the request...'
				);
				scheduleGovernorWaitHeartbeat(event);
			} else if (event.stage === 'executor_run_started') {
				replaceForegroundTail(
					'Writing',
					'active',
					'Writing from the accepted plan...'
				);
			} else if (event.stage === 'turn_request_sent') {
				ui.foregroundRequest.runtimeRequestId = event.runtimeRequestId || '';
				replaceForegroundTail(
					'Request sent',
					'active',
					'The request is in progress...'
				);
				scheduleGovernorWaitHeartbeat(event);
			} else if (event.stage === 'turn_started') {
				ui.foregroundRequest.runtimeRequestId = event.runtimeRequestId || '';
				const isPlan = event.runtimeKind === 'plan';
				replaceForegroundTail(
					isPlan ? 'Reading plan request' : 'Reading request',
					'active',
					isPlan ? 'Reading the plan request...' : 'Reading the request...'
				);
				scheduleGovernorWaitHeartbeat(event);
			} else if (event.stage === 'first_delta') {
				clearGovernorWaitTimers();
				const isSemanticIntake = event.runtimeKind === 'semantic_intake';
				const isPlan = event.runtimeKind === 'plan';
				replaceForegroundTail(
					isSemanticIntake
						? 'Understanding request'
						: isPlan
							? 'Drafting plan'
							: 'Drafting reply',
					'active',
					isSemanticIntake
						? 'Understanding request...'
						: isPlan
							? 'Drafting the plan...'
							: 'Drafting a reply...'
				);
			} else if (event.stage === 'draft_preview') {
				clearGovernorWaitTimers();
				const isPlan = event.runtimeKind === 'plan';
				replaceForegroundTail(
					isPlan ? 'Drafting plan' : 'Drafting reply',
					'active',
					isPlan ? 'Drafting the plan...' : 'Drafting a reply...'
				);
				if (typeof event.previewText === 'string' && event.previewText.trim()) {
					setDraftPreviewTarget(event.previewText);
				}
			} else if (event.stage === 'governor_runtime_failed') {
				clearGovernorWaitTimers();
				replaceForegroundTail(
					'Runtime had trouble',
					'failed',
					'Corgi is updating the state now.'
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

		function latestDispatchQueuedStatus(requestKey) {
			if (!model || !isAuthoritativeForegroundRequestKey(requestKey)) {
				return undefined;
			}
			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (
					item.type === 'system_status' &&
					item.title === 'Dispatch queued' &&
					item.in_response_to_request_id === requestKey
				) {
					return item;
				}
			}
			return undefined;
		}

		function latestPostExecutionStatus(requestKey) {
			if (!model || !isAuthoritativeForegroundRequestKey(requestKey)) {
				return undefined;
			}
			const terminalTitles = new Set([
				'Executor completed',
				'Reviewer completed',
				'Governor decision recorded',
			]);
			for (let index = model.feed.length - 1; index >= 0; index -= 1) {
				const item = model.feed[index];
				if (
					item.type === 'system_status' &&
					terminalTitles.has(item.title) &&
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
					latestPostExecutionStatus(requestKey) ||
					latestDispatchQueuedStatus(requestKey) ||
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
				if (latestPostExecutionStatus(requestKey) || latestDispatchQueuedStatus(requestKey)) {
					clearForegroundRequest();
					return;
				}
				if (latestRequestError(requestKey)) {
					clearOptimisticActionHides();
				}
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
			if (latestPostExecutionStatus(requestKey) || latestDispatchQueuedStatus(requestKey)) {
				clearForegroundRequest();
				return;
			}
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

			const latestTerminalStatus = latestPostExecutionStatus(requestKey);

			if (
				isGovernorDecisionRecorded(snapshot) ||
				latestTerminalStatus?.title === 'Governor decision recorded'
			) {
				freezeForegroundRequest(
					'Final decision recorded',
					'done',
					'Final dispatch decision recorded.'
				);
				return;
			}

			if (
				isReviewerCompleted(snapshot) ||
				latestTerminalStatus?.title === 'Reviewer completed'
			) {
				freezeForegroundRequest(
					'Checked result',
					'done',
					'Read-only check finished.'
				);
				return;
			}

			if (
				isExecutorCompleted(snapshot) ||
				latestTerminalStatus?.title === 'Executor completed'
			) {
				freezeForegroundRequest(
					'Changes written',
					'done',
					'Bounded result artifact written.'
				);
				return;
			}

			if (isDispatchQueued(snapshot) || latestDispatchQueuedStatus(requestKey)) {
				freezeForegroundRequest(
					'Ready to write',
					'done',
					'Corgi created dispatch truth for the accepted plan.'
				);
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
						'Understanding request',
						'active',
						'Understanding request...'
					);
					return;
				}
				setForegroundSingleBullet(
					'Waiting for reply',
					'active',
					'Waiting for a reply...'
				);
				return;
			}

			if (snapshot.runState === 'running') {
				replaceForegroundTail('Ready to write', 'active', 'Corgi queued dispatch truth for the accepted plan.');
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
					placeholder: 'Add details or revise the plan...',
					hint: 'This updates the plan only. Choose Execute plan when it is ready.',
					buttonLabel: 'Send revision',
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
				const goal = runtimeGoalDisplay(snapshot, stale);
			const goalDetail = goalDetailLabel(snapshot);
			headerContent.innerHTML =
				'<div class="goal-main">' +
					'<span class="status-dot ' + statusDotClass(snapshot, stale) + '"></span>' +
					'<span class="goal-title"><span class="goal-label">Goal:</span> ' +
						escapeHtml(goal.title) +
					'</span>' +
				'</div>' +
				'<div class="goal-meta" title="' + escapeHtml(goalDetail) + '">' +
					'<span class="goal-step"><span class="goal-label">Step:</span> ' +
						escapeHtml(goal.step) +
					'</span>' +
					'<span class="goal-separator">·</span>' +
					'<span>' + escapeHtml(goal.status) + '</span>' +
				'</div>';
		}

		function renderComposerActions() {
			if (!model) {
				return;
			}
			retainOptimisticHidesUntilAuthoritativeChange();

			const snapshot = model.snapshot;
			const buttons = [];

			if (model.activeClarification) {
				const clarificationOptions = Array.isArray(model.activeClarification.options)
					? model.activeClarification.options
					: [];
				buttons.push(
					...clarificationOptions.map(
						(option) =>
							'<button type="button" class="secondary" data-clarification-answer="' +
							escapeHtml(option.answer) +
							'" title="' +
							escapeHtml(option.description || option.answer) +
							'">' +
							escapeHtml(option.label) +
							'</button>'
					)
				);
			}

			if (
				snapshot.pendingPermissionRequest &&
				snapshot.pendingPermissionRequest.contextRef !== ui.pendingPermissionContextRef
			) {
				const scopes = Array.isArray(snapshot.pendingPermissionRequest.allowedScopes)
					? snapshot.pendingPermissionRequest.allowedScopes
					: ['observe', 'plan', 'execute'];
				buttons.push(
					...scopes.map((scope) =>
						'<button type="button" ' +
							(scope === snapshot.pendingPermissionRequest.recommendedScope ? '' : 'class="secondary" ') +
							'data-action="set_permission_scope" data-permission-scope="' + escapeHtml(scope) + '">' +
							escapeHtml(scope.charAt(0).toUpperCase() + scope.slice(1)) +
						'</button>'
					),
					'<button type="button" class="secondary" data-action="decline_permission">Decline</button>'
				);
			}
			if (
				snapshot.pendingPermissionRequest &&
				snapshot.pendingPermissionRequest.contextRef === ui.pendingPermissionContextRef
			) {
				buttons.push('<button type="button" class="secondary" data-action="refresh_state">Refresh state</button>');
			}

			if (
				isPlanReady(snapshot) &&
				model.planReadyRequest.contextRef !== ui.pendingPlanContextRef
			) {
				const planReady = model.planReadyRequest;
				const actions = Array.isArray(planReady.allowedActions)
					? planReady.allowedActions
					: ['execute_plan', 'revise_plan'];
				if (actions.includes('execute_plan')) {
					buttons.push(
							'<button type="button" data-action="execute_plan" data-context-ref="' +
							escapeHtml(planReady.contextRef) +
							'">' + escapeHtml(runtimeActionLabel('execute_plan', 'Execute plan')) + '</button>'
						);
					}
					if (actions.includes('revise_plan')) {
						buttons.push(
							'<button type="button" class="secondary" data-action="revise_plan" data-context-ref="' +
							escapeHtml(planReady.contextRef) +
							'">' + escapeHtml(runtimeActionLabel('revise_plan', 'Revise')) + '</button>'
						);
					}
				}
			if (
				isPlanReady(snapshot) &&
				model.planReadyRequest.contextRef === ui.pendingPlanContextRef
			) {
				buttons.push('<button type="button" class="secondary" data-action="refresh_state">Refresh state</button>');
			}

			if (!snapshot.pendingInterrupt && canStop(snapshot)) {
				buttons.push('<button type="button" class="secondary" data-action="interrupt_run">Stop</button>');
			}

			const sourceButton = renderArtifactQuickButton(currentQuickArtifact());
			if (sourceButton) {
				buttons.push(sourceButton);
			}

			composerActions.innerHTML = buttons.join('');
			composerActions.hidden = buttons.length === 0;
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
				const runtimeActivity = runtimeActivityForItem(item);
				if (runtimeActivity?.summary) {
					return runtimeActivity.summary;
				}
				const lifecycleSummaryKey = lifecycleActivitySummaryKey(item);
				if (lifecycleSummaryKey) {
					return summaryForActivityKey(lifecycleSummaryKey, {});
				}
				if (isAdvisorActivityItem(item)) {
					return summaryForActivityKey('advisor_consulting', {});
				}
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

			function activityDetailLabel(item, runtimeActivity) {
				const details = [];
				const actor = runtimeActivity?.actor || item.source_actor || item.source_layer;
				const phase = runtimeActivity?.phase || item.activity?.kind;
				if (actor) {
					details.push('Actor: ' + summarizeToken(String(actor), String(actor)));
				}
				if (phase) {
					details.push('Phase: ' + summarizeToken(String(phase), String(phase)));
				}
				return details.join(' · ');
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

			function isGovernorMessage(item) {
				return item?.type === 'actor_event' && item.source_actor === 'governor';
			}

			function splitGovernorParagraphs(value) {
				const text = String(value || '').replace(/\\s+/g, ' ').trim();
				if (!text) {
					return [];
				}

				const explicitParagraphs = String(value || '')
					.split(/\\n\\s*\\n/g)
					.map((part) => part.replace(/\\s+/g, ' ').trim())
					.filter(Boolean);
				if (explicitParagraphs.length > 1) {
					return explicitParagraphs;
				}

				return text
					.replace(/\\s+(Proposed steps:)/gi, '\\n$1')
					.replace(/\\s+(Likely (?:files\\/areas|files|areas)(?: include| involved)?[:]?)/gi, '\\n$1')
					.replace(/\\s+(Risks?\\s+or\\s+unknowns[:]?)/gi, '\\n$1')
					.replace(/\\s+(Risks?[:]?)/gi, '\\n$1')
					.replace(/(^|[.!?])\\s+(Unknowns[:]?)/gi, '$1\\n$2')
					.replace(/\\s+(Execution readiness[:]?)/gi, '\\n$1')
					.replace(/\\s+(Readiness[:]?)/gi, '\\n$1')
					.replace(/\\s+(Main risk(?: is)?)/gi, '\\n$1')
					.replace(/\\s+(Key risks?(?: are)?)/gi, '\\n$1')
					.replace(/\\s+(This is plan-ready only)/gi, '\\n$1')
					.replace(/\\s+(Execution should wait)/gi, '\\n$1')
					.split('\\n')
					.map((part) => part.trim())
					.filter(Boolean);
			}

			function renderInlineGovernorText(value) {
				const marker = String.fromCharCode(96);
				const text = String(value || '');
				let html = '';
				let cursor = 0;
				while (cursor < text.length) {
					const start = text.indexOf(marker, cursor);
					if (start < 0) {
						html += escapeHtml(text.slice(cursor));
						break;
					}
					const end = text.indexOf(marker, start + 1);
					if (end < 0) {
						html += escapeHtml(text.slice(cursor));
						break;
					}
					html += escapeHtml(text.slice(cursor, start));
					html += '<code class="inline-code">' + escapeHtml(text.slice(start + 1, end)) + '</code>';
					cursor = end + 1;
				}
				return html;
			}

			function renderGovernorParagraph(value) {
				const text = String(value || '').trim();
				const labelMatch = text.match(
					/^(Objective|Proposed steps|Likely files\\/areas|Likely files|Likely areas|Risks or unknowns|Risks|Unknowns|Execution readiness|Readiness|Main risk|Key risks)(?::|\\s+is|\\s+are)?\\s*/i
				);
				if (!labelMatch) {
					return '<p>' + renderInlineGovernorText(text) + '</p>';
				}
				const label = labelMatch[1];
				const rest = text.slice(labelMatch[0].length).trim();
				return (
					'<p><strong>' +
					escapeHtml(label.charAt(0).toUpperCase() + label.slice(1)) +
					(rest ? ':</strong> ' + renderInlineGovernorText(rest) : '</strong>') +
					'</p>'
				);
			}

			function renderGovernorMessageBody(value) {
				const paragraphs = splitGovernorParagraphs(value);
				if (paragraphs.length === 0) {
					return '';
				}
				return paragraphs.map(renderGovernorParagraph).join('');
			}

		function renderStructuredAssistantBody(value) {
			const text = String(value || '').trim();
			if (!text.includes('\\n')) {
				return renderGovernorMessageBody(text);
				}
				const lines = text.split('\\n');
				let html = '';
				let listItems = [];
				const flushList = () => {
					if (listItems.length === 0) {
						return;
					}
					html += '<ul>' + listItems.map((item) => '<li>' + renderInlineGovernorText(item) + '</li>').join('') + '</ul>';
					listItems = [];
				};
				for (const rawLine of lines) {
					const line = rawLine.trim();
					if (!line) {
						flushList();
						continue;
					}
					const heading = line.match(/^#{1,3}\\s+(.+)$/);
					if (heading) {
						flushList();
						html += '<p><strong>' + renderInlineGovernorText(heading[1]) + '</strong></p>';
						continue;
					}
					const bullet = line.match(/^-\\s+(.+)$/);
					if (bullet) {
						listItems.push(bullet[1]);
						continue;
					}
					flushList();
					html += renderGovernorParagraph(line);
				}
				flushList();
				return html;
			}

			function compactResultCopy(item, copy) {
				switch (item.title) {
					case 'Executor completed':
						return {
							title: 'Changes written',
							body: 'A bounded result artifact was written for this goal.',
						};
					case 'Reviewer completed':
						return {
							title: 'Checked result',
							body: 'A read-only check of the output finished.',
						};
					case 'Governor decision recorded':
						return {
							title: 'Final decision recorded',
							body: 'The final dispatch decision was recorded.',
						};
					default:
						return copy;
				}
			}

			function renderCompactResultMessage(item, copy, renderedBody) {
				const compact = compactResultCopy(item, copy);
				const details =
					copy.body && copy.body !== compact.body
						? '<details class="result-details">' +
							'<summary>Details</summary>' +
							'<div class="message-body is-governor-copy">' + renderedBody + '</div>' +
						  '</details>'
						: '';
				return (
					'<article class="message assistant result-summary">' +
						'<div class="result-title">' + escapeHtml(compact.title) + '</div>' +
						'<div class="result-body">' + escapeHtml(compact.body) + '</div>' +
						renderSourceActionForItem(item) +
						details +
					'</article>'
				);
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
				case 'error.plan_not_ready':
					return {
						title: fallback.title || 'Plan not ready',
						body: fallback.body || 'Refresh and use the current plan action.',
					};
				case 'error.permission_scope_too_low':
					return {
						title: fallback.title || 'Permission needed',
						body: fallback.body || 'Choose the required permission scope before continuing.',
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

		function renderActivity(item, overflow) {
			const activity = item.activity ?? { state: item.type === 'error' ? 'failed' : 'completed' };
			const runtimeActivity = runtimeActivityForItem(item);
			const lifecycleSummaryKey = lifecycleActivitySummaryKey(item);
			const state =
				lifecycleSummaryKey === 'dispatch_queued' ||
				lifecycleSummaryKey === 'executor_running' ||
				lifecycleSummaryKey === 'reviewer_running'
					? 'running'
					: runtimeActivity?.severity === 'error'
						? 'failed'
						: activity.state || 'completed';
			const label = activityLabel(item);
			const summaryCandidate =
				runtimeActivity && runtimeActivity.summary !== label
					? runtimeActivity.summary
					: item.type === 'artifact_reference'
						? item.artifact.summary
						: activity.summary && activity.kind !== 'status'
							? activity.summary
							: undefined;
			const summary = summaryCandidate && summaryCandidate !== label ? summaryCandidate : undefined;
			const detailTitle = activityDetailLabel(item, runtimeActivity);

			const rowClass = overflow ? 'activity-overflow-row' : 'activity-row';

			return (
				'<article class="' + rowClass + ' is-' + escapeHtml(state) + ' ' +
					(item.authoritative ? '' : 'is-informational') +
				'" title="' + escapeHtml(detailTitle) + '">' +
					'<div class="activity-dot"></div>' +
					'<div>' +
						'<div class="activity-label">' + escapeHtml(label) + '</div>' +
						(summary ? '<div class="activity-summary">' + escapeHtml(summary) + '</div>' : '') +
						renderArtifactActions(item) +
						renderSourceActionForItem(item) +
						renderDetails(item) +
					'</div>' +
				'</article>'
			);
		}

			function renderMessage(item) {
				const copy = displayCopy(item);
				const governorMessage = isGovernorMessage(item);
					const structuredAssistantMessage =
						governorMessage ||
						(item.type === 'system_status' &&
							(item.title === 'Executor completed' ||
								item.title === 'Reviewer completed' ||
								item.title === 'Governor decision recorded'));
				const body = copy.body || copy.title;
				const renderedBody = structuredAssistantMessage
					? renderStructuredAssistantBody(body)
					: escapeHtml(body);
				if (
					item.type === 'system_status' &&
					(item.title === 'Executor completed' ||
						item.title === 'Reviewer completed' ||
						item.title === 'Governor decision recorded')
				) {
					return renderCompactResultMessage(item, copy, renderedBody);
				}
				if (item.type === 'error') {
					return (
						'<article class="message error">' +
						'<div class="message-label">Error</div>' +
						'<div class="message-body">' + escapeHtml(copy.title) + '</div>' +
						(copy.body ? '<div class="activity-summary">' + escapeHtml(copy.body) + '</div>' : '') +
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
						'<div class="message-body' +
						(structuredAssistantMessage ? ' is-governor-copy' : '') +
						'">' +
						renderedBody +
						'</div>' +
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
			if (
				latestPostExecutionStatus(requestKey) ||
				latestDispatchQueuedStatus(requestKey)
			) {
				return '';
			}
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
					'<div class="draft-preview-label">Draft preview</div>' +
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
			const visibility = feedItemVisibility(item);
			if (visibility === 'activity') {
				return renderActivity(item);
			}
			if (visibility !== 'transcript') {
				return '';
			}

			return renderMessage(item);
		}

		function visibleActivityIds(limit) {
			if (!model) {
				return new Set();
			}
			const activityIds = model.feed
				.filter((item) => feedItemVisibility(item) === 'activity')
				.map((item) => item.id);
			return new Set(activityIds.slice(-limit));
		}

		function renderActivityOverflow(items) {
			if (!Array.isArray(items) || items.length === 0) {
				return '';
			}
			return (
				'<details class="activity-overflow">' +
					'<summary>Older activity (' + String(items.length) + ')</summary>' +
					'<div class="activity-overflow-body">' +
						items.map((item) => renderActivity(item, true)).join('') +
					'</div>' +
				'</details>'
			);
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
			const activityLimit = 5;
			const activityItems = model.feed.filter((item) => feedItemVisibility(item) === 'activity');
			const visibleActivities = visibleActivityIds(activityLimit);
			const hiddenActivityItems = activityItems.filter((item) => !visibleActivities.has(item.id));
			let renderedActivityOverflow = false;
			const cards = model.feed.map((item, index) => {
				const visibility = feedItemVisibility(item);
				if (visibility === 'activity' && !visibleActivities.has(item.id)) {
					return '';
				}
				let markup = renderFeedItem(item);
				if (
					visibility === 'activity' &&
					hiddenActivityItems.length > 0 &&
					!renderedActivityOverflow
				) {
					markup = renderActivityOverflow(hiddenActivityItems) + markup;
					renderedActivityOverflow = true;
				}
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
			renderComposerActions();
			renderFeed();
			renderComposer();
			scheduleWebviewSnapshot('render');
			scheduleTestWindowAutoStep('render');
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
				startForegroundRequest(text, 'Waiting for reply...', requestId);
				ui.pendingPlanContextRef = model.planReadyRequest?.contextRef;
				ui.pendingPlanHiddenAt = Date.now();
				setForegroundSingleBullet(
					'Waiting for reply',
					'active',
					'Waiting for reply...'
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
			renderComposerActions();
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
					clearOptimisticActionHides();
					vscode.postMessage({ type: 'refresh_state' });
					scheduleWebviewSnapshot('refresh_state_click');
					return;
			}
			if (action === 'execute_plan') {
				const requestId = nextForegroundRequestKey();
				startForegroundRequest('', 'Preparing to write...', requestId);
				setForegroundSingleBullet(
					'Preparing to write',
					'active',
					'Preparing to write...'
				);
				scheduleActivityTrace(requestId);
				ui.planRevisionMode = false;
				ui.pendingPlanContextRef = model?.planReadyRequest?.contextRef;
				ui.pendingPlanHiddenAt = Date.now();
				renderComposerActions();
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
				renderComposerActions();
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
							? 'Starting write'
							: 'Waiting for reply',
						'active',
						scope === 'execute'
							? 'Starting write...'
							: 'Waiting for reply...'
					);
					scheduleActivityTrace(requestKey);
					renderComposerActions();
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
				renderComposerActions();
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
