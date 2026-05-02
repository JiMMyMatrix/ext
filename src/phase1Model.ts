export const SNAPSHOT_STALE_AFTER_MS = 45_000;

type FeedItemType =
	| 'user_message'
	| 'shell_event'
	| 'system_status'
	| 'actor_event'
	| 'clarification_request'
	| 'permission_request'
	| 'interrupt_request'
	| 'artifact_reference'
	| 'error';

type NonArtifactFeedItemType = Exclude<FeedItemType, 'artifact_reference'>;

export type TransportState =
	| 'connected'
	| 'connecting'
	| 'degraded'
	| 'disconnected';

export type PermissionScope = 'unset' | 'observe' | 'plan' | 'execute';

export type RunState = 'idle' | 'queued' | 'running';

export type TurnType =
	| 'governed_work_intent'
	| 'governor_dialogue'
	| 'clarification_reply'
	| 'permission_action'
	| 'stop_action'
	| 'system';

export type SemanticRouteType =
	| 'governed_work_intent'
	| 'governor_dialogue'
	| 'clarification_reply'
	| 'explicit_action'
	| 'block';

export type SemanticConfidence = 'high' | 'low';

export type SemanticMode = 'sidecar-first' | 'governor-first';

export type SemanticActionName =
	| 'interrupt_run'
	| 'none';

export interface SemanticContextFlags {
	used_controller_summary: boolean;
	used_accepted_intake_summary: boolean;
	used_dialogue_summary: boolean;
	had_active_clarification: boolean;
	had_pending_permission_request: boolean;
	had_pending_interrupt: boolean;
}

export interface SemanticMetadata {
	semantic_mode?: SemanticMode;
	semantic_input_version?: string;
	semantic_summary_ref?: string;
	semantic_context_flags?: SemanticContextFlags;
	semantic_route_type?: SemanticRouteType;
	semantic_confidence?: SemanticConfidence;
	semantic_block_reason?: string;
	semantic_paraphrase?: string;
	semantic_normalized_text?: string;
}

export interface ControllerRequestMetadata {
	request_id?: string;
	context_ref?: string;
	session_ref?: string;
}

export type ActivityKind =
	| 'read'
	| 'search'
	| 'list'
	| 'command'
	| 'edit'
	| 'artifact'
	| 'status';

export type ActivityState =
	| 'running'
	| 'completed'
	| 'failed'
	| 'stopped';

export interface ActivityMetadata {
	kind: ActivityKind;
	state: ActivityState;
	path?: string;
	query?: string;
	command?: string;
	summary?: string;
	elapsedMs?: number;
}

export interface ArtifactReference {
	id: string;
	label: string;
	path: string;
	status?: string;
	summary?: string;
	authoritative: boolean;
}

export interface RequestCard {
	id: string;
	contextRef: string;
	title: string;
	body: string;
	requestedAt: string;
}

export type PlanReadyAction = 'execute_plan' | 'revise_plan';

export interface PlanReadyRequest extends RequestCard {
	foregroundRequestId?: string;
	acceptedIntakeSummary: AcceptedIntakeSummary;
	allowedActions: PlanReadyAction[];
	planVersion?: number;
	planContextRef?: string;
}

export interface PermissionRequest extends RequestCard {
	recommendedScope: PermissionScope;
	allowedScopes: PermissionScope[];
	continuationKind?: 'intake_acceptance' | 'governor_dialogue' | 'plan_execution';
	pendingPrompt?: string;
	pendingNormalizedText?: string;
	foregroundRequestId?: string;
}

export interface ClarificationOption {
	id: string;
	label: string;
	answer: string;
	description?: string;
}

export interface ClarificationRequest {
	id: string;
	contextRef: string;
	title: string;
	body: string;
	kind?: string;
	options?: ClarificationOption[];
	allowFreeText?: boolean;
	placeholder?: string;
	requestedAt: string;
}

export interface AcceptedIntakeSummary {
	title: string;
	body: string;
}

export interface SnapshotFreshness {
	receivedAt: string;
	stale?: boolean;
}

export interface ContextSnapshot {
	sessionRef?: string;
	lane?: string;
	branch?: string;
	task?: string;
	currentActor?: string;
	currentStage?: string;
	permissionScope: PermissionScope;
	runState: RunState;
	transportState: TransportState;
	pendingPermissionRequest?: PermissionRequest;
	pendingInterrupt?: RequestCard;
	recentArtifacts: ArtifactReference[];
	snapshotFreshness: SnapshotFreshness;
}

interface FeedItemShared {
	id: string;
	timestamp: string;
	title: string;
	body?: string;
	details?: string[];
	authoritative: boolean;
	activity?: ActivityMetadata;
	source_layer?: string;
	source_actor?: string;
	source_artifact_ref?: string;
	turn_type?: TurnType;
	semantic_input_version?: string;
	semantic_summary_ref?: string;
	semantic_context_flags?: SemanticContextFlags;
	semantic_route_type?: SemanticRouteType;
	semantic_confidence?: SemanticConfidence;
	semantic_block_reason?: string;
	semantic_paraphrase?: string;
	semantic_normalized_text?: string;
	in_response_to_request_id?: string;
	presentation_key?: string;
	presentation_args?: Record<string, unknown>;
}

interface FeedItemBase extends FeedItemShared {
	type: NonArtifactFeedItemType;
}

export interface ArtifactFeedItem extends FeedItemShared {
	type: 'artifact_reference';
	artifact: ArtifactReference;
}

export type FeedItem = FeedItemBase | ArtifactFeedItem;

export interface ExecutionWindowModel {
	snapshot: ContextSnapshot;
	feed: FeedItem[];
	activeClarification?: ClarificationRequest;
	activeForegroundRequestId?: string;
	acceptedIntakeSummary?: AcceptedIntakeSummary;
	planReadyRequest?: PlanReadyRequest;
}

export type ModelAction =
	| ({ type: 'submit_prompt'; text: string; now?: string } & SemanticMetadata & ControllerRequestMetadata)
	| ({ type: 'answer_clarification'; text: string; now?: string } & SemanticMetadata & ControllerRequestMetadata)
	| ({ type: 'set_permission_scope'; permission_scope: PermissionScope; text?: string; now?: string } & SemanticMetadata & ControllerRequestMetadata)
	| ({ type: 'decline_permission'; text?: string; now?: string } & SemanticMetadata & ControllerRequestMetadata)
	| ({ type: 'interrupt_run'; text?: string; now?: string } & SemanticMetadata & ControllerRequestMetadata)
	| ({ type: 'execute_plan'; text?: string; now?: string } & ControllerRequestMetadata)
	| ({ type: 'revise_plan'; text: string; now?: string } & ControllerRequestMetadata)
	| ({ type: 'reconnect'; now?: string } & ControllerRequestMetadata);

let idCounter = 0;

function nextId(prefix: string): string {
	idCounter += 1;
	return `${prefix}-${idCounter}`;
}

function defaultArtifacts(): ArtifactReference[] {
	return [
		{
			id: 'artifact-orchestration-readme',
			label: 'README.md',
			path: 'orchestration/README.md',
			status: 'accepted',
			summary: 'Canonical runtime-facing orchestration overview.',
			authoritative: true,
		},
		{
			id: 'artifact-intake-contract',
			label: 'intake.json',
			path: 'orchestration/contracts/intake.json',
			status: 'referenced',
			summary: 'Canonical intake artifact contract.',
			authoritative: true,
		},
		{
			id: 'artifact-draft',
			label: 'request_draft.json',
			path: 'orchestration/intake.md',
			status: 'draft',
			summary: 'Drafts remain informational until orchestration acceptance.',
			authoritative: false,
		},
	];
}

function defaultProvenance(
	type: NonArtifactFeedItemType
): Pick<FeedItemShared, 'source_layer' | 'source_actor' | 'turn_type'> {
	if (type === 'user_message') {
		return {
			source_layer: 'dialog_controller',
			source_actor: 'human',
			turn_type: 'system',
		};
	}

	if (type === 'shell_event' || type === 'clarification_request') {
		return {
			source_layer: 'intake',
			source_actor: 'intake_shell',
			turn_type: 'system',
		};
	}

	if (type === 'actor_event') {
		return {
			source_layer: 'governor',
			source_actor: 'governor',
			turn_type: 'governor_dialogue',
		};
	}

	return {
		source_layer: 'orchestration',
		source_actor: 'orchestration',
		turn_type: 'system',
	};
}

function createFeedItem(
	type: NonArtifactFeedItemType,
	title: string,
	body: string | undefined,
	authoritative: boolean,
	now: string,
	details?: string[],
	activity?: ActivityMetadata,
	provenance?: Partial<
		Pick<
			FeedItemShared,
			| 'source_layer'
			| 'source_actor'
			| 'source_artifact_ref'
			| 'turn_type'
			| 'semantic_input_version'
			| 'semantic_summary_ref'
			| 'semantic_context_flags'
			| 'semantic_route_type'
			| 'semantic_confidence'
			| 'semantic_block_reason'
			| 'semantic_paraphrase'
			| 'semantic_normalized_text'
			| 'in_response_to_request_id'
			| 'presentation_key'
			| 'presentation_args'
		>
	>
): FeedItemBase {
	const defaults = defaultProvenance(type);
	return {
		id: nextId(type),
		type,
		timestamp: now,
		title,
		body,
		details,
		authoritative,
		activity,
		source_layer: provenance?.source_layer ?? defaults.source_layer,
		source_actor: provenance?.source_actor ?? defaults.source_actor,
		source_artifact_ref: provenance?.source_artifact_ref,
		turn_type: provenance?.turn_type ?? defaults.turn_type,
		semantic_input_version: provenance?.semantic_input_version,
		semantic_summary_ref: provenance?.semantic_summary_ref,
		semantic_context_flags: provenance?.semantic_context_flags,
		semantic_route_type: provenance?.semantic_route_type,
		semantic_confidence: provenance?.semantic_confidence,
		semantic_block_reason: provenance?.semantic_block_reason,
		semantic_paraphrase: provenance?.semantic_paraphrase,
		semantic_normalized_text: provenance?.semantic_normalized_text,
		in_response_to_request_id: provenance?.in_response_to_request_id,
		presentation_key: provenance?.presentation_key,
		presentation_args: provenance?.presentation_args,
	};
}

function buildContextRef(prefix: string): string {
	return nextId(`${prefix}-context`);
}

function currentInterruptContextRef(model: ExecutionWindowModel): string {
	return `interrupt:${model.snapshot.snapshotFreshness.receivedAt}`;
}

function createArtifactFeedItem(
	artifact: ArtifactReference,
	now: string
): ArtifactFeedItem {
	return {
		id: nextId('artifact_reference'),
		type: 'artifact_reference',
		timestamp: now,
		title: artifact.label,
		body: artifact.summary,
		authoritative: artifact.authoritative,
		source_layer: 'orchestration',
		source_actor: 'orchestration',
		source_artifact_ref: artifact.path,
		turn_type: 'system',
		artifact,
		activity: {
			kind: 'artifact',
			state: 'completed',
			path: artifact.path,
			summary: artifact.status,
		},
	};
}

function trimAndNormalize(text: string): string {
	return text.trim().replace(/\s+/g, ' ');
}

function summarizePrompt(text: string): string {
	const normalized = trimAndNormalize(text);

	if (normalized.length <= 72) {
		return normalized;
	}

	return `${normalized.slice(0, 69)}...`;
}

function refreshSnapshot(
	snapshot: ContextSnapshot,
	now: string,
	overrides: Partial<ContextSnapshot>
): ContextSnapshot {
	return {
		...snapshot,
		...overrides,
		snapshotFreshness: {
			receivedAt: now,
		},
	};
}

export function createInitialModel(now = new Date().toISOString()): ExecutionWindowModel {
	return {
		snapshot: {
			sessionRef: nextId('session'),
			lane: 'lane/phase-1',
			branch: 'feature/execution-window',
			currentActor: 'intake_shell',
			currentStage: 'idle',
			permissionScope: 'unset',
			runState: 'idle',
			transportState: 'connected',
			recentArtifacts: [],
			snapshotFreshness: {
				receivedAt: now,
			},
		},
		feed: [
			createFeedItem(
				'system_status',
				'Ready when you are',
				'Ask for a change or follow-up.',
				true,
				now
			),
		],
	};
}

export function appendError(
	model: ExecutionWindowModel,
	title: string,
	body: string,
	details?: string[],
	now = new Date().toISOString(),
	requestId?: string,
	presentationKey = 'error.generic',
	presentationArgs?: Record<string, unknown>
): ExecutionWindowModel {
	return {
		...model,
		snapshot: refreshSnapshot(model.snapshot, now, {}),
		feed: [
			...model.feed,
			createFeedItem('error', title, body, true, now, details, undefined, {
				in_response_to_request_id: requestId,
				presentation_key: presentationKey,
				presentation_args: presentationArgs ?? { title, body },
			}),
		],
	};
}

export function appendControllerSemanticClarification(
	model: ExecutionWindowModel,
	rawText: string,
	title: string,
	body: string,
	semantic: SemanticMetadata,
	now = new Date().toISOString(),
	requestId?: string,
	presentationKey = 'semantic.needs_clearer_request',
	presentationArgs?: Record<string, unknown>
): ExecutionWindowModel {
	return {
		...model,
		snapshot: refreshSnapshot(model.snapshot, now, {
			transportState: 'connected',
		}),
		feed: [
			...model.feed,
			createFeedItem(
				'user_message',
				'Prompt submitted',
				trimAndNormalize(rawText),
				false,
				now,
				undefined,
				undefined,
				{
					source_layer: 'dialog_controller',
					source_actor: 'human',
					semantic_input_version: semantic.semantic_input_version,
					semantic_summary_ref: semantic.semantic_summary_ref,
					semantic_context_flags: semantic.semantic_context_flags,
					semantic_route_type: semantic.semantic_route_type,
					semantic_confidence: semantic.semantic_confidence,
					semantic_block_reason: semantic.semantic_block_reason,
					semantic_paraphrase: semantic.semantic_paraphrase,
					semantic_normalized_text: semantic.semantic_normalized_text,
					in_response_to_request_id: requestId,
				}
			),
			createFeedItem(
				'system_status',
				title,
				body,
				true,
				now,
				undefined,
				undefined,
				{
					source_layer: 'dialog_controller',
					source_actor: 'semantic_sidecar',
					semantic_input_version: semantic.semantic_input_version,
					semantic_summary_ref: semantic.semantic_summary_ref,
					semantic_context_flags: semantic.semantic_context_flags,
					semantic_route_type: semantic.semantic_route_type,
					semantic_confidence: semantic.semantic_confidence,
					semantic_block_reason: semantic.semantic_block_reason,
					semantic_paraphrase: semantic.semantic_paraphrase,
					semantic_normalized_text: semantic.semantic_normalized_text,
					in_response_to_request_id: requestId,
					presentation_key: presentationKey,
					presentation_args: presentationArgs,
				}
			),
		],
	};
}

function supersedePendingApproval(
	model: ExecutionWindowModel,
	now: string,
	requestId?: string
): FeedItem[] {
	if (!model.snapshot.pendingPermissionRequest) {
		return [];
	}

	return [
		createFeedItem(
			'system_status',
			'Pending permission request superseded',
			'A new request replaced the previous permission checkpoint.',
			true,
			now,
			undefined,
			undefined,
			{
				in_response_to_request_id: requestId,
				presentation_key: 'permission.superseded',
			}
		),
	];
}

function resolveTurnTypeFromSemanticRoute(
	routeType: SemanticRouteType | undefined
): TurnType | undefined {
	if (routeType === 'governor_dialogue') {
		return 'governor_dialogue';
	}
	if (routeType === 'governed_work_intent') {
		return 'governed_work_intent';
	}
	return undefined;
}

function semanticProvenanceForAction(action: ModelAction): SemanticMetadata {
	if (
		action.type === 'reconnect' ||
		action.type === 'execute_plan' ||
		action.type === 'revise_plan'
	) {
		return {};
	}
	return {
		semantic_input_version: action.semantic_input_version,
		semantic_summary_ref: action.semantic_summary_ref,
		semantic_context_flags: action.semantic_context_flags,
		semantic_route_type: action.semantic_route_type,
		semantic_confidence: action.semantic_confidence,
		semantic_block_reason: action.semantic_block_reason,
		semantic_paraphrase: action.semantic_paraphrase,
		semantic_normalized_text: action.semantic_normalized_text,
	};
}

function responseProvenanceForAction(
	action: ModelAction
): Partial<
	Pick<
		FeedItemShared,
		| 'semantic_input_version'
		| 'semantic_summary_ref'
		| 'semantic_context_flags'
		| 'semantic_route_type'
		| 'semantic_confidence'
		| 'semantic_block_reason'
		| 'semantic_paraphrase'
		| 'semantic_normalized_text'
		| 'in_response_to_request_id'
	>
> {
	return {
		...semanticProvenanceForAction(action),
		in_response_to_request_id: action.request_id,
	};
}

function staleContextError(command: string): string {
	switch (command) {
		case 'answer_clarification':
			return 'The clarification changed before this answer was applied. Refresh and answer the current clarification instead.';
		case 'set_permission_scope':
		case 'decline_permission':
			return 'The permission request changed before this action was applied. Refresh and confirm the current permission choice.';
		case 'interrupt_run':
			return 'The interruptible run state changed before this stop request was applied. Refresh and try again if stop is still available.';
		case 'execute_plan':
		case 'revise_plan':
			return 'The plan checkpoint changed before this action was applied. Refresh and use the current plan action.';
		default:
			return 'The referenced session state is no longer current. Refresh and try again.';
	}
}

function hasFreshContextRef(
	action: ModelAction,
	expectedContextRef: string | undefined
): boolean {
	if (action.type === 'reconnect' || !expectedContextRef) {
		return true;
	}
	return action.context_ref === expectedContextRef;
}

function buildClarificationRequest(
	prompt: string,
	now: string
): ClarificationRequest {
	const lower = prompt.toLowerCase();

	if (
		['analyze', 'analyse', 'review', 'inspect', 'explore'].some((token) =>
			lower.includes(token)
		) &&
		['folder', 'repo', 'repository', 'project', 'codebase', 'directory'].some(
			(token) => lower.includes(token)
		)
	) {
		return {
			id: nextId('clarification'),
			contextRef: buildContextRef('clarification'),
			title: 'Clarification required',
			body: 'What kind of analysis do you want for this folder?',
			placeholder: 'Optional: add a short detail if none of these fit exactly.',
			requestedAt: now,
			kind: 'analysis_focus',
			options: [
				{
					id: 'analysis-architecture',
					label: 'Architecture',
					answer: 'Focus on architecture, structure, and subsystem boundaries.',
					description: 'Look at structure, boundaries, and responsibilities.',
				},
				{
					id: 'analysis-risks',
					label: 'Bugs and risks',
					answer: 'Focus on bugs, regressions, and architectural risks.',
					description: 'Look for concrete risks and likely failures.',
				},
				{
					id: 'analysis-plan',
					label: 'Implementation plan',
					answer: 'Focus on implementation opportunities and the next practical plan.',
					description: 'Turn the analysis into an actionable next-step plan.',
				},
			],
			allowFreeText: true,
		};
	}

	if (
		['build', 'implement', 'change', 'refactor', 'update', 'fix'].some((token) =>
			lower.includes(token)
		)
	) {
		return {
			id: nextId('clarification'),
			contextRef: buildContextRef('clarification'),
			title: 'Clarification required',
			body: 'What should this change preserve while I work?',
			placeholder:
				'Optional: add a short detail if none of these fit exactly.',
			requestedAt: now,
			kind: 'implementation_guardrail',
			options: [
				{
					id: 'guardrail-scope',
					label: 'Keep scope minimal',
					answer: 'Keep the scope minimal and avoid broad side effects.',
					description: 'Prefer the smallest safe change.',
				},
				{
					id: 'guardrail-ui',
					label: 'Preserve visible UX',
					answer:
						'Preserve the current visible UX and control flow unless I ask for a redesign.',
					description: 'Avoid unnecessary UX drift.',
				},
				{
					id: 'guardrail-artifacts',
					label: 'Preserve artifact flow',
					answer:
						'Preserve the current artifact and orchestration flow while making the change.',
					description: 'Keep current harness behavior intact.',
				},
			],
			allowFreeText: true,
		};
	}

	return {
		id: nextId('clarification'),
		contextRef: buildContextRef('clarification'),
		title: 'Clarification required',
		body: 'Name one detail Corgi must keep visible at all times.',
		placeholder:
			'Example: Keep current actor and current stage visible in the header.',
		requestedAt: now,
		kind: 'constraint',
		allowFreeText: true,
	};
}

function buildGovernorDialogueReply(
	model: ExecutionWindowModel,
	prompt: string
): { body: string; details: string[] } {
	const { snapshot } = model;
	const task = snapshot.task;
	const actor = snapshot.currentActor ?? 'orchestration';
	const stage = snapshot.currentStage ?? 'idle';

	if (model.activeClarification) {
		return {
			body: 'Current progress: one clarification is still open. Answer it or choose one of the suggested options to keep moving.',
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
			],
		};
	}

	if (snapshot.pendingPermissionRequest) {
		return {
			body: `Current progress: this request is ready, but it is waiting for a ${snapshot.pendingPermissionRequest.recommendedScope} permission choice before Corgi can continue.`,
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
				`Current task: ${task ?? 'Not yet accepted'}`,
			],
		};
	}

	if (snapshot.currentStage === 'dispatch_queued' || snapshot.runState === 'queued') {
		return {
			body: `Current progress: dispatch truth is queued${task ? ` for ${task}` : ''}. Executor has not started yet.`,
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
			],
		};
	}

	if (snapshot.runState === 'running') {
		return {
			body: `Current progress: Corgi is actively working${task ? ` on ${task}` : ''}. Stop is available if you need it.`,
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
			],
		};
	}

	if (model.acceptedIntakeSummary && snapshot.currentStage === 'plan_ready') {
		return {
			body: `I’ll revise the current plan with that guidance: ${summarizePrompt(prompt)}. Executor remains disabled until you choose Execute plan.`,
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
			],
		};
	}

	if (model.acceptedIntakeSummary) {
		return {
			body: `The latest accepted intake is ${task ?? 'ready'}, and the session is currently idle. Send a new governed request when you want the workflow to move again.`,
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
			],
		};
	}

	return {
		body: 'Nothing is running right now. Start with a bounded request, or ask a progress question anytime.',
		details: [
			`Prompt: ${summarizePrompt(prompt)}`,
			`Current actor: ${actor}`,
			`Current stage: ${stage}`,
		],
	};
}

function humanizeAcceptedSummary(task: string): string {
	const normalizedTask = task.trim().replace(/[.!?]+$/u, '');
	if (!normalizedTask) {
		return 'Accepted and ready.';
	}

	return (
		normalizedTask.charAt(0).toUpperCase() +
		normalizedTask.slice(1) +
		'.'
	);
}

function buildAcceptedSummary(
	model: ExecutionWindowModel,
	permissionScope: PermissionScope
): AcceptedIntakeSummary {
	const task = model.snapshot.task ?? 'Current task';
	const suffix =
		permissionScope === 'execute'
			? ' Execute permission is active for this session.'
			: '';

	return {
		title: 'Accepted intake summary',
		body: `${humanizeAcceptedSummary(task)}${suffix}`,
	};
}

function buildPlanReadyRequest(
	summary: AcceptedIntakeSummary,
	now: string,
	foregroundRequestId?: string,
	planVersion = 1
): PlanReadyRequest {
	const id = nextId('plan-ready');
	const contextRef = buildContextRef('plan-ready');
	return {
		id,
		contextRef,
		planContextRef: contextRef,
		planVersion,
		title: 'Plan ready',
		body: 'Review the Governor plan, then execute it or add details for a revision.',
		requestedAt: now,
		foregroundRequestId,
		acceptedIntakeSummary: summary,
		allowedActions: ['execute_plan', 'revise_plan'],
	};
}

function buildGovernorPlanReply(summary: AcceptedIntakeSummary): {
	body: string;
	details: string[];
} {
	return {
		body: [
			`Objective: ${summary.body}`,
			'Proposed steps: inspect the relevant structure, identify the likely files or subsystems, call out risks or unknowns, and prepare the smallest safe execution path.',
			'Likely files/areas: start from accepted intake artifacts, src/executionWindowPanel.ts, src/executionTransport.ts, src/phase1Model.ts, orchestration/harness/session.py, and orchestration/contracts/ux.md before touching implementation.',
			'Risks or unknowns: verify actual authority boundaries from runtime code and contracts rather than directory names alone.',
			'Execution readiness: Plan scope is active. Executor remains disabled until you choose Execute plan.',
		].join('\n\n'),
		details: [
			'Permission scope: Plan',
			'Executor remains disabled until you choose Execute plan.',
		],
	};
}

function recommendedPermissionScope(prompt: string): PermissionScope {
	const normalized = trimAndNormalize(prompt).toLowerCase();
	if (
		[
			'implement',
			'build',
			'create',
			'refactor',
			'fix',
			'debug',
			'update',
			'change',
			'write',
		].some((token) => normalized === token || normalized.startsWith(`${token} `))
	) {
		return 'execute';
	}

	return 'plan';
}

function buildPermissionRequest(
	recommendedScope: PermissionScope,
	now: string,
	options: {
		continuationKind?: 'intake_acceptance' | 'governor_dialogue' | 'plan_execution';
		pendingPrompt?: string;
		pendingNormalizedText?: string;
		foregroundRequestId?: string;
	} = {}
): PermissionRequest {
	return {
		id: nextId('permission'),
		contextRef: buildContextRef('permission'),
		title: 'Permission needed',
		body: `Choose ${recommendedScope} if you want Corgi to continue this request.`,
		recommendedScope,
		allowedScopes: permissionScopesThatSatisfy(recommendedScope),
		requestedAt: now,
		continuationKind: options.continuationKind ?? 'intake_acceptance',
		pendingPrompt: options.pendingPrompt,
		pendingNormalizedText: options.pendingNormalizedText,
		foregroundRequestId: options.foregroundRequestId,
	};
}

function permissionAllowsTurn(
	scope: PermissionScope,
	turnType: TurnType
): boolean {
	if (turnType === 'governor_dialogue') {
		return scope === 'observe' || scope === 'plan' || scope === 'execute';
	}
	if (turnType === 'governed_work_intent') {
		return scope === 'plan' || scope === 'execute';
	}
	return true;
}

function pendingPermissionContinuation(
	request: PermissionRequest | undefined
): 'intake_acceptance' | 'governor_dialogue' {
	return request?.continuationKind === 'governor_dialogue'
		? 'governor_dialogue'
		: 'intake_acceptance';
}

function pendingPermissionForegroundRequestId(
	request: PermissionRequest | undefined,
	fallbackRequestId?: string
): string | undefined {
	return request?.foregroundRequestId || fallbackRequestId;
}

function permissionRank(scope: PermissionScope): number {
	switch (scope) {
		case 'unset':
			return 0;
		case 'observe':
			return 1;
		case 'plan':
			return 2;
		case 'execute':
			return 3;
	}
}

function shouldRequestExecuteForAcceptedContinuation(
	model: ExecutionWindowModel,
	action: SemanticMetadata
): boolean {
	return Boolean(
		model.acceptedIntakeSummary &&
			model.snapshot.permissionScope === 'plan' &&
			model.snapshot.currentStage === 'plan_ready' &&
			action.semantic_context_flags?.used_accepted_intake_summary
	);
}

function scopeSatisfies(current: PermissionScope, required: PermissionScope): boolean {
	return permissionRank(current) >= permissionRank(required);
}

function hasPlanReadyRequest(model: ExecutionWindowModel): model is ExecutionWindowModel & {
	planReadyRequest: PlanReadyRequest;
} {
	return Boolean(
		model.planReadyRequest &&
			model.acceptedIntakeSummary &&
			model.snapshot.currentStage === 'plan_ready' &&
			model.snapshot.permissionScope === 'plan' &&
			!model.snapshot.pendingPermissionRequest &&
			!model.activeClarification &&
			model.snapshot.runState !== 'running'
	);
}

function permissionScopesThatSatisfy(required: PermissionScope): PermissionScope[] {
	return (['observe', 'plan', 'execute'] as PermissionScope[]).filter((scope) =>
		scopeSatisfies(scope, required)
	);
}

function formatPermissionScope(scope: PermissionScope): string {
	return scope.charAt(0).toUpperCase() + scope.slice(1);
}

function acceptIntake(
	model: ExecutionWindowModel,
	now: string,
	permissionScope: PermissionScope,
	turnType: TurnType = 'system',
	provenance?: Partial<
		Pick<
			FeedItemShared,
			| 'semantic_input_version'
			| 'semantic_summary_ref'
			| 'semantic_context_flags'
			| 'semantic_route_type'
			| 'semantic_confidence'
			| 'semantic_block_reason'
			| 'semantic_paraphrase'
			| 'semantic_normalized_text'
			| 'in_response_to_request_id'
		>
	>
): ExecutionWindowModel {
	const artifacts = defaultArtifacts();
	const acceptedIntakeSummary = buildAcceptedSummary(model, permissionScope);
	const governorPlanReply =
		permissionScope === 'plan'
			? buildGovernorPlanReply(acceptedIntakeSummary)
			: undefined;
	const foregroundRequestId = provenance?.in_response_to_request_id;
	const planReadyRequest =
		permissionScope === 'plan'
			? buildPlanReadyRequest(acceptedIntakeSummary, now, foregroundRequestId)
			: undefined;

	return {
		snapshot: refreshSnapshot(model.snapshot, now, {
			currentActor: permissionScope === 'plan' ? 'governor' : 'orchestration',
			currentStage:
				permissionScope === 'execute'
					? 'dispatch_queued'
					: permissionScope === 'plan'
						? 'plan_ready'
						: 'intake_accepted',
			permissionScope,
			runState: permissionScope === 'execute' ? 'queued' : 'idle',
			pendingPermissionRequest: undefined,
			pendingInterrupt: undefined,
			recentArtifacts: artifacts,
			transportState: 'connected',
		}),
		feed: [
			...model.feed,
			createFeedItem(
				'system_status',
				permissionScope === 'execute' ? 'Dispatch queued' : 'Accepted and ready',
				permissionScope === 'execute'
					? 'Execute permission is active and dispatch truth was queued for the accepted plan.'
					: acceptedIntakeSummary.body,
				true,
				now,
				undefined,
				undefined,
				{
					turn_type: turnType,
					...provenance,
				}
			),
			...(governorPlanReply
				? [
						createFeedItem(
							'actor_event',
							'Governor response',
							governorPlanReply.body,
							true,
							now,
							governorPlanReply.details,
							undefined,
							{
								turn_type: turnType,
								...provenance,
							}
						),
				  ]
				: []),
		],
		activeClarification: undefined,
		activeForegroundRequestId:
			permissionScope === 'execute' ? model.activeForegroundRequestId : undefined,
		acceptedIntakeSummary,
		planReadyRequest,
	};
}

export function getArtifactById(
	model: ExecutionWindowModel,
	artifactId: string
): ArtifactReference | undefined {
	for (const artifact of model.snapshot.recentArtifacts) {
		if (artifact.id === artifactId) {
			return artifact;
		}
	}

	for (const item of model.feed) {
		if (item.type === 'artifact_reference' && item.artifact.id === artifactId) {
			return item.artifact;
		}
	}

	return undefined;
}

export function isSnapshotStale(
	freshness: SnapshotFreshness,
	nowMs = Date.now(),
	thresholdMs = SNAPSHOT_STALE_AFTER_MS
): boolean {
	if (freshness.stale) {
		return true;
	}

	return nowMs - Date.parse(freshness.receivedAt) > thresholdMs;
}

export function applyModelAction(
	model: ExecutionWindowModel,
	action: ModelAction
): ExecutionWindowModel {
	const now = action.now ?? new Date().toISOString();

	switch (action.type) {
		case 'submit_prompt': {
			const prompt = trimAndNormalize(action.text);
			if (!prompt) {
				return appendError(
					model,
					'Prompt required',
					'Enter a prompt before sending it to Corgi.',
					undefined,
					now,
					action.request_id
				);
			}

			const turnType = resolveTurnTypeFromSemanticRoute(action.semantic_route_type);
			if (!turnType) {
				return appendError(
					model,
					'Semantic route required',
					'Corgi needs a semantic sidecar route before dispatching this prompt.',
					undefined,
					now,
					action.request_id,
					'error.semantic_route_required'
				);
			}

			if (turnType === 'governor_dialogue') {
				if (!permissionAllowsTurn(model.snapshot.permissionScope, turnType)) {
					const permissionRequest = buildPermissionRequest('observe', now, {
						continuationKind: 'governor_dialogue',
						pendingPrompt: prompt,
						pendingNormalizedText: prompt,
						foregroundRequestId: action.request_id,
					});
					return {
						...model,
						snapshot: refreshSnapshot(model.snapshot, now, {
							currentActor: 'orchestration',
							currentStage: 'permission_needed',
							pendingPermissionRequest: permissionRequest,
							transportState: 'connected',
						}),
						feed: [
							...model.feed,
							createFeedItem('user_message', 'Governor question', prompt, false, now, undefined, undefined, {
								turn_type: turnType,
								...responseProvenanceForAction(action),
							}),
							createFeedItem(
								'permission_request',
								permissionRequest.title,
								permissionRequest.body,
								true,
								now,
								undefined,
								undefined,
								{
									turn_type: turnType,
									...responseProvenanceForAction(action),
									presentation_key: 'permission.needed',
									presentation_args: {
										scope: permissionRequest.recommendedScope,
									},
								}
							),
						],
						activeForegroundRequestId: model.activeForegroundRequestId ?? action.request_id,
					};
				}

				const reply = buildGovernorDialogueReply(model, prompt);
				return {
					...model,
					snapshot: refreshSnapshot(model.snapshot, now, {
						transportState: 'connected',
					}),
					feed: [
						...model.feed,
						createFeedItem('user_message', 'Governor question', prompt, false, now, undefined, undefined, {
							turn_type: turnType,
							...responseProvenanceForAction(action),
						}),
						createFeedItem(
							'actor_event',
							'Governor response',
							reply.body,
							true,
							now,
							reply.details,
							undefined,
							{
								source_layer: 'governor',
								source_actor: 'governor',
								turn_type: turnType,
								...responseProvenanceForAction(action),
							}
						),
					],
					activeForegroundRequestId: undefined,
				};
			}

			if (shouldRequestExecuteForAcceptedContinuation(model, action)) {
				const permissionRequest = buildPermissionRequest('execute', now, {
					foregroundRequestId: action.request_id,
					pendingPrompt: prompt,
					pendingNormalizedText: action.semantic_normalized_text ?? prompt,
				});

				return {
					...model,
					snapshot: refreshSnapshot(model.snapshot, now, {
						currentActor: 'orchestration',
						currentStage: 'permission_needed',
						runState: 'idle',
						pendingPermissionRequest: permissionRequest,
						pendingInterrupt: undefined,
						transportState: 'connected',
					}),
					feed: [
						...model.feed,
						createFeedItem(
							'user_message',
							'Prompt submitted',
							prompt,
							false,
							now,
							undefined,
							undefined,
							{
								turn_type: turnType,
								...responseProvenanceForAction(action),
							}
						),
						createFeedItem(
							'permission_request',
							permissionRequest.title,
							permissionRequest.body,
							true,
							now,
							undefined,
							undefined,
							{
								turn_type: turnType,
								...responseProvenanceForAction(action),
								presentation_key: 'permission.needed',
								presentation_args: {
									scope: permissionRequest.recommendedScope,
								},
							}
						),
					],
					activeClarification: undefined,
					activeForegroundRequestId: action.request_id ?? model.activeForegroundRequestId,
				};
			}

			const clarification = buildClarificationRequest(prompt, now);

			const pendingSupersededFeed = supersedePendingApproval(
				model,
				now,
				action.request_id
			);

			return {
				snapshot: refreshSnapshot(model.snapshot, now, {
					task: summarizePrompt(prompt),
					currentActor: 'intake_shell',
					currentStage: 'clarification_needed',
					runState: 'idle',
					pendingPermissionRequest: undefined,
					pendingInterrupt: undefined,
					recentArtifacts: [],
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					...pendingSupersededFeed,
					createFeedItem(
						'user_message',
						'Prompt submitted',
						prompt,
						false,
						now,
						undefined,
						undefined,
						{
							turn_type: turnType,
							...responseProvenanceForAction(action),
							presentation_key: 'clarification.requested',
						}
					),
					createFeedItem(
						'shell_event',
						'One detail needed',
						'I need one quick clarification before checking the permission scope for this request.',
						false,
						now,
						[
							'This request draft is informational only.',
							'Accepted workflow state must still come from upstream.',
						],
						{
							kind: 'status',
							state: 'running',
							summary: 'Intake clarification',
						},
						{
							turn_type: turnType,
							...responseProvenanceForAction(action),
						}
					),
					createFeedItem(
						'clarification_request',
						clarification.title,
						clarification.body,
						true,
						now,
						undefined,
						undefined,
						{
							turn_type: turnType,
							...responseProvenanceForAction(action),
						}
					),
				],
				activeClarification: clarification,
				activeForegroundRequestId: action.request_id ?? model.activeForegroundRequestId,
			};
		}

		case 'answer_clarification': {
			if (!model.activeClarification) {
				return appendError(
					model,
					'No clarification is active',
					'There is no active clarification request to answer right now.',
					undefined,
					now,
					action.request_id
				);
			}

			if (!hasFreshContextRef(action, model.activeClarification.contextRef)) {
				return appendError(
					model,
					'Clarification changed',
					staleContextError('answer_clarification'),
					undefined,
					now,
					action.request_id,
					'error.stale_context',
					{ kind: 'clarification' }
				);
			}

			const answer = trimAndNormalize(action.text);
			if (!answer) {
				return appendError(
					model,
					'Clarification answer required',
					'Enter a clarification answer before sending it.',
					undefined,
					now,
					action.request_id
				);
			}

			const requiredScope = recommendedPermissionScope(answer);
			if (scopeSatisfies(model.snapshot.permissionScope, requiredScope)) {
				return acceptIntake(
					{
						...model,
						feed: [
							...model.feed,
							createFeedItem(
								'user_message',
								'Clarification answered',
								answer,
								false,
								now,
								undefined,
								undefined,
								{
									turn_type: 'clarification_reply',
									...responseProvenanceForAction(action),
								}
							),
						],
					},
					now,
					model.snapshot.permissionScope,
					'clarification_reply',
					responseProvenanceForAction(action)
				);
			}

			const permissionRequest = buildPermissionRequest(requiredScope, now, {
				foregroundRequestId: model.activeForegroundRequestId ?? action.request_id,
			});

			return {
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentActor: 'orchestration',
					currentStage: 'permission_needed',
					runState: 'idle',
					pendingPermissionRequest: permissionRequest,
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'user_message',
						'Clarification answered',
						answer,
						false,
						now,
						undefined,
						undefined,
						{
							turn_type: 'clarification_reply',
							...responseProvenanceForAction(action),
							presentation_key: 'permission.needed',
							presentation_args: {
								scope: permissionRequest.recommendedScope,
							},
						}
					),
					createFeedItem(
						'shell_event',
						'Draft is ready for permission review',
						'The intake shell updated the draft and handed it back for permission selection.',
						false,
						now,
						undefined,
						{
							kind: 'status',
							state: 'completed',
							summary: 'Ready for permission',
						},
						{
							turn_type: 'clarification_reply',
							...responseProvenanceForAction(action),
						}
					),
					createFeedItem(
						'permission_request',
						permissionRequest.title,
						permissionRequest.body,
						true,
						now,
						undefined,
						undefined,
						{
							turn_type: 'clarification_reply',
							...responseProvenanceForAction(action),
						}
					),
				],
				activeClarification: undefined,
				acceptedIntakeSummary: undefined,
				activeForegroundRequestId: model.activeForegroundRequestId ?? action.request_id,
			};
		}

		case 'set_permission_scope': {
			if (!model.snapshot.pendingPermissionRequest) {
				return appendError(
					model,
					'No permission request is active',
					'There is no permission request to answer right now.',
					undefined,
					now,
					action.request_id
				);
			}

			if (
				!hasFreshContextRef(action, model.snapshot.pendingPermissionRequest.contextRef)
			) {
				return appendError(
					model,
					'Permission changed',
					staleContextError('set_permission_scope'),
					undefined,
					now,
					action.request_id,
					'error.stale_context',
					{ kind: 'permission' }
				);
			}

			const continuedRequestId = pendingPermissionForegroundRequestId(
				model.snapshot.pendingPermissionRequest,
				model.activeForegroundRequestId ?? action.request_id
			);
			if (
				!scopeSatisfies(
					action.permission_scope,
					model.snapshot.pendingPermissionRequest.recommendedScope
				)
			) {
				return appendError(
					model,
					'Permission scope too low',
					`Choose ${formatPermissionScope(model.snapshot.pendingPermissionRequest.recommendedScope)} or higher to continue this request.`,
					undefined,
					now,
					action.request_id,
					'error.permission_scope_too_low',
					{
						requiredScope: model.snapshot.pendingPermissionRequest.recommendedScope,
						selectedScope: action.permission_scope,
					}
				);
			}

			const withUserTurn = action.text
				? {
						...model,
						feed: [
							...model.feed,
							createFeedItem(
								'user_message',
								'Permission selected',
								trimAndNormalize(action.text),
								false,
								now,
								undefined,
								undefined,
								{
									turn_type: 'permission_action',
									...responseProvenanceForAction(action),
									in_response_to_request_id: continuedRequestId,
								}
							),
						],
				  }
				: model;

			const pendingRequest = withUserTurn.snapshot.pendingPermissionRequest;
			if (pendingPermissionContinuation(pendingRequest) === 'governor_dialogue') {
				const prompt =
					pendingRequest?.pendingNormalizedText ||
					pendingRequest?.pendingPrompt ||
					withUserTurn.feed
						.slice()
						.reverse()
						.find(
							(item) =>
								item.type === 'user_message' &&
							item.turn_type === 'governor_dialogue'
						)?.body ||
					'';
				const resumedDialogueModel = {
					...withUserTurn,
					snapshot: {
						...withUserTurn.snapshot,
						permissionScope: action.permission_scope,
						pendingPermissionRequest: undefined,
					},
				};
				const reply = buildGovernorDialogueReply(resumedDialogueModel, prompt);
				return {
					...resumedDialogueModel,
					snapshot: refreshSnapshot(resumedDialogueModel.snapshot, now, {
						permissionScope: action.permission_scope,
						pendingPermissionRequest: undefined,
						currentActor: 'governor',
						currentStage: 'dialogue_ready',
						runState: 'idle',
						transportState: 'connected',
					}),
					feed: [
						...withUserTurn.feed,
						createFeedItem(
							'actor_event',
							'Governor response',
							reply.body,
							true,
							now,
							reply.details,
							undefined,
							{
								turn_type: 'governor_dialogue',
								...responseProvenanceForAction(action),
								in_response_to_request_id: continuedRequestId,
							}
						),
					],
					activeForegroundRequestId: undefined,
				};
			}

			if (pendingRequest?.continuationKind === 'plan_execution') {
				return {
					...withUserTurn,
					snapshot: refreshSnapshot(withUserTurn.snapshot, now, {
						permissionScope: action.permission_scope,
						pendingPermissionRequest: undefined,
						pendingInterrupt: undefined,
						currentActor: 'orchestration',
						currentStage: 'dispatch_queued',
						runState: 'queued',
						transportState: 'connected',
					}),
					feed: [
						...withUserTurn.feed,
						createFeedItem(
							'system_status',
							'Dispatch queued',
							'Execute permission is active and dispatch truth was queued for the accepted plan.',
							true,
							now,
							undefined,
							undefined,
							{
								turn_type: 'permission_action',
								...responseProvenanceForAction(action),
								in_response_to_request_id: continuedRequestId,
							}
						),
					],
					activeClarification: undefined,
					activeForegroundRequestId: continuedRequestId,
					planReadyRequest: undefined,
				};
			}

			return acceptIntake(
				withUserTurn,
				now,
				action.permission_scope,
				'permission_action',
				{
					...responseProvenanceForAction(action),
					in_response_to_request_id: continuedRequestId,
				}
			);
		}

		case 'execute_plan': {
			if (!action.request_id) {
				return appendError(
					model,
					'Request id required',
					'Execute plan requires a fresh controller request id.',
					undefined,
					now,
					undefined,
					'error.stale_context',
					{ kind: 'plan' }
				);
			}

			if (!hasPlanReadyRequest(model)) {
				return appendError(
					model,
					'No plan is ready',
					'There is no current plan checkpoint to execute.',
					undefined,
					now,
					action.request_id
				);
			}

			if (!hasFreshContextRef(action, model.planReadyRequest.contextRef)) {
				return appendError(
					model,
					'Plan changed',
					staleContextError('execute_plan'),
					undefined,
					now,
					action.request_id,
					'error.stale_context',
					{ kind: 'plan' }
				);
			}

			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentActor: 'orchestration',
					currentStage: 'dispatch_queued',
					permissionScope: 'execute',
					runState: 'queued',
					pendingPermissionRequest: undefined,
					pendingInterrupt: undefined,
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'system_status',
						'Dispatch queued',
						'Execute plan was confirmed and dispatch truth was queued for the accepted plan.',
						true,
						now,
						undefined,
						undefined,
						{
							turn_type: 'permission_action',
							in_response_to_request_id: action.request_id,
						}
					),
				],
				activeForegroundRequestId: action.request_id ?? model.planReadyRequest.foregroundRequestId,
				planReadyRequest: undefined,
			};
		}

		case 'revise_plan': {
			if (!action.request_id) {
				return appendError(
					model,
					'Request id required',
					'Plan revisions require a fresh controller request id.',
					undefined,
					now,
					undefined,
					'error.stale_context',
					{ kind: 'plan' }
				);
			}

			if (!hasPlanReadyRequest(model)) {
				return appendError(
					model,
					'No plan is ready',
					'There is no current plan checkpoint to revise.',
					undefined,
					now,
					action.request_id
				);
			}

			if (model.snapshot.currentStage !== 'plan_ready') {
				return appendError(
					model,
					'Plan changed',
					'The current session is no longer at a plan-ready checkpoint.',
					undefined,
					now,
					action.request_id,
					'error.stale_context',
					{ kind: 'plan' }
				);
			}

			if (!hasFreshContextRef(action, model.planReadyRequest.contextRef)) {
				return appendError(
					model,
					'Plan changed',
					staleContextError('revise_plan'),
					undefined,
					now,
					action.request_id,
					'error.stale_context',
					{ kind: 'plan' }
				);
			}

			const prompt = trimAndNormalize(action.text);
			if (!prompt) {
				return appendError(
					model,
					'Revision details required',
					'Add the details you want the Governor to include in the plan.',
					undefined,
					now,
					action.request_id
				);
			}

			const withUserTurn = {
				...model,
				feed: [
					...model.feed,
					createFeedItem(
						'user_message',
						'Plan revision',
						prompt,
						false,
						now,
						undefined,
						undefined,
						{
							turn_type: 'governor_dialogue',
							in_response_to_request_id: action.request_id,
						}
					),
				],
			};
			const reply = buildGovernorDialogueReply(withUserTurn, prompt);
			const planReadyRequest = buildPlanReadyRequest(
				model.planReadyRequest.acceptedIntakeSummary,
				now,
				action.request_id ?? model.planReadyRequest.foregroundRequestId,
				(model.planReadyRequest.planVersion ?? 1) + 1
			);
			return {
				...withUserTurn,
				snapshot: refreshSnapshot(withUserTurn.snapshot, now, {
					permissionScope: 'plan',
					currentActor: 'governor',
					currentStage: 'plan_ready',
					runState: 'idle',
					pendingPermissionRequest: undefined,
					pendingInterrupt: undefined,
					transportState: 'connected',
				}),
				feed: [
					...withUserTurn.feed,
					createFeedItem(
						'actor_event',
						'Governor response',
						reply.body,
						true,
						now,
						reply.details,
						undefined,
						{
							source_layer: 'governor',
							source_actor: 'governor',
							turn_type: 'governor_dialogue',
							in_response_to_request_id: action.request_id,
						}
					),
				],
				activeClarification: undefined,
				activeForegroundRequestId: undefined,
				planReadyRequest,
			};
		}

		case 'decline_permission': {
			if (!model.snapshot.pendingPermissionRequest) {
				return appendError(
					model,
					'No permission request is active',
					'There is no permission request to decline right now.',
					undefined,
					now,
					action.request_id
				);
			}

			if (
				!hasFreshContextRef(action, model.snapshot.pendingPermissionRequest.contextRef)
			) {
				return appendError(
					model,
					'Permission changed',
					staleContextError('decline_permission'),
					undefined,
					now,
					action.request_id,
					'error.stale_context',
					{ kind: 'permission' }
				);
			}

			const declinedPlanExecution =
				model.snapshot.pendingPermissionRequest.continuationKind ===
					'plan_execution' && Boolean(model.planReadyRequest);
			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentActor: declinedPlanExecution ? 'governor' : 'orchestration',
					currentStage: declinedPlanExecution ? 'plan_ready' : 'permission_declined',
					runState: 'idle',
					pendingPermissionRequest: undefined,
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					...(action.text
						? [
								createFeedItem(
									'user_message',
									'Permission declined',
									trimAndNormalize(action.text),
									false,
									now,
									undefined,
									undefined,
									{
										turn_type: 'permission_action',
										...responseProvenanceForAction(action),
									}
								),
						  ]
						: []),
					createFeedItem(
						'system_status',
						'Permission request declined',
						'The session permission scope did not change, and this request will not continue.',
						true,
						now,
						undefined,
						undefined,
						{
							turn_type: 'permission_action',
							...responseProvenanceForAction(action),
							presentation_key: 'permission.declined',
						}
					),
				],
			};
		}

		case 'interrupt_run': {
			if (model.snapshot.runState !== 'running') {
				return appendError(
					model,
					'Nothing is running',
					'Stop is only available while governed work is actively running.',
					undefined,
					now,
					action.request_id
				);
			}

			if (!hasFreshContextRef(action, currentInterruptContextRef(model))) {
				return appendError(
					model,
					'Interrupt state changed',
					staleContextError('interrupt_run'),
					undefined,
					now,
					action.request_id,
					'error.stale_context',
					{ kind: 'interrupt' }
				);
			}

			if (model.snapshot.pendingInterrupt) {
				return {
					...model,
					snapshot: refreshSnapshot(model.snapshot, now, {
						transportState: 'connected',
					}),
					feed: [
						...model.feed,
						createFeedItem(
							'system_status',
							'Stop already pending',
							'Wait for the authoritative stop status to change before sending another request.',
							false,
							now,
							undefined,
							undefined,
							{
								in_response_to_request_id: action.request_id,
							}
						),
					],
				};
			}

			const interrupt: RequestCard = {
				id: nextId('interrupt'),
				contextRef: currentInterruptContextRef(model),
				title: 'Stop requested',
				body: 'Stop has been requested and is awaiting authoritative follow-up.',
				requestedAt: now,
			};

			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentStage: 'interrupt_requested',
					pendingInterrupt: interrupt,
					runState: 'running',
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					...(action.text
						? [
								createFeedItem(
									'user_message',
									'Stop requested',
									trimAndNormalize(action.text),
									false,
									now,
									undefined,
									undefined,
									{
										turn_type: 'stop_action',
										...responseProvenanceForAction(action),
									}
								),
						  ]
						: []),
					createFeedItem(
						'interrupt_request',
						interrupt.title,
						interrupt.body,
						true,
						now,
						undefined,
						undefined,
						{
							turn_type: 'stop_action',
							...responseProvenanceForAction(action),
						}
					),
				],
			};
		}

		case 'reconnect':
			if (
				model.snapshot.transportState === 'connected' &&
				!isSnapshotStale(model.snapshot.snapshotFreshness, Date.parse(now))
			) {
				return appendError(
					model,
					'Nothing to reconnect',
					'The current session is already connected and fresh.',
					undefined,
					now,
					action.request_id
				);
			}
			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					runState: model.snapshot.runState,
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'system_status',
						'Connection refreshed',
						'A fresh snapshot is now available in Corgi.',
						true,
						now,
						undefined,
						undefined,
						{
							in_response_to_request_id: action.request_id,
						}
					),
				],
			};
	}
}
