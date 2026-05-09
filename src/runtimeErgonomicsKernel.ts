import type { ExecutionWindowModel, FeedItem } from './phase1Model';

export type RuntimeActivityVisibility =
	| 'transcript'
	| 'activity'
	| 'detail'
	| 'internal';

export type RuntimeActivitySeverity = 'info' | 'success' | 'warning' | 'error';

export interface RuntimeActivityEvent {
	requestId?: string;
	workRef?: string;
	attemptNumber?: number;
	actor: string;
	phase: string;
	severity: RuntimeActivitySeverity;
	summaryKey: string;
	summaryArgs?: Record<string, unknown>;
	summary: string;
	visibility: RuntimeActivityVisibility;
	sourceRef?: string;
}

export interface RuntimeGoalDisplay {
	goal: string;
	step: string;
	status: string;
}

export interface RuntimeActionDisplay {
	id: string;
	label: string;
	primary: boolean;
}

export interface RuntimeErgonomicsState {
	goal: RuntimeGoalDisplay;
	activities: RuntimeActivityEvent[];
	primaryAction?: RuntimeActionDisplay;
	secondaryActions: RuntimeActionDisplay[];
	transcriptFeedItemIds: string[];
	activityFeedItemIds: string[];
	detailFeedItemIds: string[];
	internalFeedItemIds: string[];
}

const SUMMARY_COPY: Record<string, string> = {
	semantic_intake: 'Understanding request',
	governor_drafting_plan: 'Drafting plan',
	dispatch_queued: 'Ready to write',
	executor_running: 'Writing',
	executor_completed: 'Changes written',
	reviewer_running: 'Checking',
	reviewer_request_changes: 'Changes requested',
	reviewer_completed: 'Checked result',
	plan_revision: 'Revising plan',
	advisor_consulting: 'Consulting advisor',
	governor_decision_recorded: 'Final decision recorded',
};

function titleOf(item: FeedItem): string {
	return String(item.title || '').trim();
}

function normalizedTitle(item: FeedItem): string {
	return titleOf(item).toLowerCase();
}

function isGovernorFeedItem(item: FeedItem): boolean {
	return item.type === 'actor_event' && item.source_actor === 'governor';
}

function isAdvisorItem(item: FeedItem): boolean {
	const haystack = `${item.source_actor || ''}\n${item.source_layer || ''}\n${item.title || ''}\n${item.body || ''}`.toLowerCase();
	return haystack.includes('advisor') || haystack.includes('consult');
}

function isInternalStatusItem(item: FeedItem): boolean {
	if (item.type !== 'system_status') {
		return false;
	}
	const title = normalizedTitle(item);
	return title === 'ready when you are' || title === 'accepted and ready';
}

export function summaryForActivity(
	summaryKey: string,
	summaryArgs: Record<string, unknown> = {}
): string {
	if (summaryKey === 'parallel_running') {
		const count = Number(summaryArgs.count || 0);
		return count > 1 ? `${count} tasks running` : 'Writing';
	}
	return SUMMARY_COPY[summaryKey] ?? summaryKey.replace(/_/g, ' ');
}

export function runtimeVisibilityForFeedItem(
	item: FeedItem
): RuntimeActivityVisibility {
	if (item.type === 'artifact_reference' || item.type === 'shell_event') {
		return 'detail';
	}
	if (item.type === 'user_message' && item.turn_type === 'permission_action') {
		return 'internal';
	}
	if (isInternalStatusItem(item)) {
		return 'internal';
	}
	if (isGovernorFeedItem(item) || item.type === 'user_message') {
		return 'transcript';
	}
	if (item.activity || activityKeyForFeedItem(item) !== undefined) {
		return 'activity';
	}
	if (item.type === 'actor_event' || isAdvisorItem(item)) {
		return 'activity';
	}
	return 'transcript';
}

function runtimeVisibilityForModelFeedItem(
	model: ExecutionWindowModel,
	item: FeedItem
): RuntimeActivityVisibility {
	if (item.type === 'permission_request') {
		const itemContextRef = item.presentation_args?.contextRef;
		const activeContextRef = model.snapshot.pendingPermissionRequest?.contextRef;
		const contextMatches =
			typeof itemContextRef === 'string' && typeof activeContextRef === 'string'
				? itemContextRef === activeContextRef
				: item.body === model.snapshot.pendingPermissionRequest?.body;
		return model.snapshot.pendingPermissionRequest && contextMatches
			? 'transcript'
			: 'internal';
	}
	if (item.type === 'clarification_request') {
		const itemContextRef = item.presentation_args?.contextRef;
		const activeContextRef = model.activeClarification?.contextRef;
		const contextMatches =
			typeof itemContextRef === 'string' && typeof activeContextRef === 'string'
				? itemContextRef === activeContextRef
				: item.body === model.activeClarification?.body;
		return model.activeClarification && contextMatches
			? 'transcript'
			: 'internal';
	}
	if (isInternalStatusItem(item)) {
		return 'internal';
	}
	return runtimeVisibilityForFeedItem(item);
}

function severityForState(state: string | undefined): RuntimeActivitySeverity {
	switch (state) {
		case 'failed':
		case 'stopped':
			return 'error';
		case 'completed':
			return 'success';
		default:
			return 'info';
	}
}

function activityKeyForFeedItem(item: FeedItem): string | undefined {
	if (isGovernorFeedItem(item)) {
		return undefined;
	}
	if (isAdvisorItem(item)) {
		return 'advisor_consulting';
	}

	const title = normalizedTitle(item);
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

function actorForFeedItem(item: FeedItem, summaryKey: string): string {
	if (summaryKey.startsWith('executor') || summaryKey === 'dispatch_queued') {
		return 'executor';
	}
	if (summaryKey.startsWith('reviewer')) {
		return 'reviewer';
	}
	if (summaryKey.startsWith('governor')) {
		return 'governor';
	}
	if (summaryKey === 'advisor_consulting') {
		return 'advisor';
	}
	return item.source_actor || item.source_layer || 'orchestration';
}

function feedActivityEvent(
	model: ExecutionWindowModel,
	item: FeedItem
): RuntimeActivityEvent | undefined {
	const activityKey = activityKeyForFeedItem(item);
	if (!activityKey && !item.activity) {
		return undefined;
	}

	const summaryKey = activityKey ?? item.activity?.kind ?? 'activity';
	const summaryArgs: Record<string, unknown> = {};
	const state = item.activity?.state;
	return {
		requestId: item.in_response_to_request_id,
		workRef: model.snapshot.currentWorkRef,
		attemptNumber: model.snapshot.currentAttemptNumber,
		actor: actorForFeedItem(item, summaryKey),
		phase: summaryKey,
		severity: severityForState(state),
		summaryKey,
		summaryArgs,
		summary: item.activity?.summary || summaryForActivity(summaryKey, summaryArgs),
		visibility: 'activity',
		sourceRef: item.id,
	};
}

function liveActivityEvent(
	model: ExecutionWindowModel
): RuntimeActivityEvent | undefined {
	const snapshot = model.snapshot;
	const stage = String(snapshot.currentStage || '').toLowerCase();
	const actor = String(snapshot.currentActor || '').toLowerCase();
	const parallelCount = Number(snapshot.activeParallelDispatchCount || 0);
	let summaryKey: string | undefined;
	const summaryArgs: Record<string, unknown> = {};

	if (parallelCount > 1 && snapshot.runState === 'running') {
		summaryKey = 'parallel_running';
		summaryArgs.count = parallelCount;
	} else if (stage === 'semantic_intake') {
		summaryKey = 'semantic_intake';
	} else if (stage === 'waiting_for_governor') {
		summaryKey = 'governor_drafting_plan';
	} else if (stage === 'dispatch_queued' || snapshot.runState === 'queued') {
		summaryKey = 'dispatch_queued';
	} else if (actor === 'executor' && snapshot.runState === 'running') {
		summaryKey = 'executor_running';
	} else if (actor === 'reviewer' && snapshot.runState === 'running') {
		summaryKey = 'reviewer_running';
	} else if (snapshot.latestReviewVerdict === 'request_changes') {
		summaryKey = 'reviewer_request_changes';
	} else if (stage === 'governor_decision_recorded') {
		summaryKey = 'governor_decision_recorded';
	}

	if (!summaryKey) {
		return undefined;
	}

	return {
		requestId: model.activeForegroundRequestId,
		workRef: snapshot.currentWorkRef,
		attemptNumber: snapshot.currentAttemptNumber,
		actor: actor || 'orchestration',
		phase: summaryKey,
		severity: summaryKey === 'reviewer_request_changes' ? 'warning' : 'info',
		summaryKey,
		summaryArgs,
		summary: summaryForActivity(summaryKey, summaryArgs),
		visibility: 'activity',
		sourceRef: 'snapshot',
	};
}

function summarizeToken(value: string | undefined, fallback: string): string {
	if (!value) {
		return fallback;
	}
	return value
		.replace(/[_-]+/g, ' ')
		.replace(/\s+/g, ' ')
		.trim()
		.replace(/\b\w/g, (char) => char.toUpperCase());
}

function attemptSuffix(model: ExecutionWindowModel): string {
	const attempt = model.snapshot.currentAttemptNumber;
	return typeof attempt === 'number' && attempt > 0 ? ` · Attempt ${attempt}` : '';
}

function nextAttemptSuffix(model: ExecutionWindowModel): string {
	const attempt = model.snapshot.currentAttemptNumber;
	return typeof attempt === 'number' && attempt > 0
		? ` · Attempt ${attempt + 1}`
		: '';
}

function isPlanReady(model: ExecutionWindowModel): boolean {
	return (
		model.snapshot.currentStage === 'plan_ready' &&
		model.planReadyRequest !== undefined
	);
}

function isDispatchQueued(model: ExecutionWindowModel): boolean {
	return (
		model.snapshot.currentStage === 'dispatch_queued' ||
		model.snapshot.runState === 'queued'
	);
}

function isExecutorCompleted(model: ExecutionWindowModel): boolean {
	return model.snapshot.currentStage === 'executor_completed';
}

function isReviewerCompleted(model: ExecutionWindowModel): boolean {
	return model.snapshot.currentStage === 'reviewer_completed';
}

function isGovernorDecisionRecorded(model: ExecutionWindowModel): boolean {
	return (
		model.snapshot.currentStage === 'governor_decision_recorded' ||
		Boolean(model.snapshot.latestGovernorDecisionRef)
	);
}

function collapseActivities(
	activities: RuntimeActivityEvent[]
): RuntimeActivityEvent[] {
	const collapsed = new Map<string, RuntimeActivityEvent>();
	for (const event of activities) {
		const key = [
			event.workRef || '',
			event.attemptNumber ?? '',
			event.actor,
			event.phase,
			event.requestId || '',
		].join('|');
		collapsed.set(key, event);
	}
	return Array.from(collapsed.values());
}

function goalDisplay(model: ExecutionWindowModel): RuntimeGoalDisplay {
	const snapshot = model.snapshot;
	const goal =
		snapshot.task ||
		model.acceptedIntakeSummary?.body ||
		model.acceptedIntakeSummary?.title ||
		'Nothing active yet';
	const attempt = attemptSuffix(model);
	let step = snapshot.task ? 'Ready to continue' : 'Ready';

	const liveEvent = liveActivityEvent(model);
	if (liveEvent?.summaryKey === 'parallel_running') {
		step = liveEvent.summary;
	} else if (model.activeClarification) {
		step = 'Clarification needed';
	} else if (snapshot.pendingPermissionRequest) {
		step = 'Permission needed';
	} else if (snapshot.pendingInterrupt) {
		step = 'Stop requested';
	} else if (snapshot.currentStage === 'semantic_intake') {
		step = summaryForActivity('semantic_intake');
	} else if (isPlanReady(model)) {
		step = `Plan ready${nextAttemptSuffix(model)}`;
	} else if (snapshot.currentStage === 'plan_executing') {
		step = `Writing${attempt}`;
	} else if (isDispatchQueued(model)) {
		step = `Ready to write${attempt}`;
	} else if (isGovernorDecisionRecorded(model)) {
		step = snapshot.latestGovernorDecision
			? `Final decision ${summarizeToken(snapshot.latestGovernorDecision, '')}${attempt}`
			: `Final decision recorded${attempt}`;
	} else if (isReviewerCompleted(model)) {
		step = snapshot.latestReviewVerdict
			? `Check ${summarizeToken(snapshot.latestReviewVerdict, '')}${attempt}`
			: `Checked result${attempt}`;
	} else if (isExecutorCompleted(model)) {
		step = `Changes written${attempt}`;
	} else if (snapshot.currentActor === 'governor' && snapshot.runState === 'running') {
		step = 'Planning';
	} else if (snapshot.currentActor === 'executor') {
		step = `Writing${attempt}`;
	} else if (snapshot.currentActor === 'reviewer') {
		step = `Checking${attempt}`;
	} else if (snapshot.runState === 'running') {
		step = 'Corgi is working';
	}

	let status = 'Attention';
	if (snapshot.pendingInterrupt) {
		status = 'Stop pending';
	} else if (snapshot.pendingPermissionRequest) {
		status = 'Permission needed';
	} else if (model.activeClarification) {
		status = 'Needs input';
	} else if (snapshot.currentStage === 'plan_executing') {
		status = 'Running';
	} else if (isDispatchQueued(model)) {
		status = 'Ready to write';
	} else if (isGovernorDecisionRecorded(model)) {
		status = 'Finalized';
	} else if (isReviewerCompleted(model) || isExecutorCompleted(model)) {
		status = 'Done';
	} else if (snapshot.runState === 'running') {
		status = 'Running';
	} else if (snapshot.transportState === 'connected' && isPlanReady(model)) {
		status = 'Plan ready';
	} else if (snapshot.transportState === 'connected') {
		status = 'Ready';
	}
	return { goal, step, status };
}

function actionDisplay(model: ExecutionWindowModel): {
	primaryAction?: RuntimeActionDisplay;
	secondaryActions: RuntimeActionDisplay[];
} {
	if (!model.planReadyRequest) {
		return { secondaryActions: [] };
	}

	const actions = model.planReadyRequest.allowedActions;
	return {
		primaryAction: actions.includes('execute_plan')
			? { id: 'execute_plan', label: 'Execute plan', primary: true }
			: undefined,
		secondaryActions: actions
			.filter((action) => action !== 'execute_plan')
			.map((action) => ({
				id: action,
				label: action === 'revise_plan' ? 'Revise' : action,
				primary: false,
			})),
	};
}

export function buildRuntimeErgonomicsKernel(
	model: ExecutionWindowModel
): RuntimeErgonomicsState {
	const feedActivities = model.feed
		.map((item) => feedActivityEvent(model, item))
		.filter((event): event is RuntimeActivityEvent => event !== undefined);
	const liveEvent = liveActivityEvent(model);
	const activities = collapseActivities(
		liveEvent ? [...feedActivities, liveEvent] : feedActivities
	);
	const visibleActivitySourceRefs = new Set(
		activities
			.map((activity) => activity.sourceRef)
			.filter(
				(sourceRef): sourceRef is string =>
					typeof sourceRef === 'string' && sourceRef !== 'snapshot'
			)
	);

	const transcriptFeedItemIds: string[] = [];
	const activityFeedItemIds: string[] = [];
	const detailFeedItemIds: string[] = [];
	const internalFeedItemIds: string[] = [];
	for (const item of model.feed) {
		const visibility = runtimeVisibilityForModelFeedItem(model, item);
		if (visibility === 'transcript') {
			transcriptFeedItemIds.push(item.id);
		} else if (visibility === 'activity') {
			if (visibleActivitySourceRefs.has(item.id)) {
				activityFeedItemIds.push(item.id);
			} else {
				internalFeedItemIds.push(item.id);
			}
		} else if (visibility === 'detail') {
			detailFeedItemIds.push(item.id);
		} else if (visibility === 'internal') {
			internalFeedItemIds.push(item.id);
		}
	}

	const actions = actionDisplay(model);
	return {
		goal: goalDisplay(model),
		activities,
		primaryAction: actions.primaryAction,
		secondaryActions: actions.secondaryActions,
		transcriptFeedItemIds,
		activityFeedItemIds,
		detailFeedItemIds,
		internalFeedItemIds,
	};
}
