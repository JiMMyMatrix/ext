export const SNAPSHOT_STALE_AFTER_MS = 45_000;

type FeedItemType =
	| 'user_message'
	| 'shell_event'
	| 'system_status'
	| 'actor_event'
	| 'clarification_request'
	| 'approval_request'
	| 'interrupt_request'
	| 'artifact_reference'
	| 'error';

type NonArtifactFeedItemType = Exclude<FeedItemType, 'artifact_reference'>;

export type TransportState =
	| 'connected'
	| 'connecting'
	| 'degraded'
	| 'disconnected';

export type AccessMode = 'approval_required' | 'full_access';

export type RunState = 'idle' | 'running';

export type TurnType =
	| 'governed_work_intent'
	| 'governor_dialogue'
	| 'clarification_reply'
	| 'approval_action'
	| 'stop_action'
	| 'system';

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
	title: string;
	body: string;
	requestedAt: string;
}

export interface ClarificationOption {
	id: string;
	label: string;
	answer: string;
	description?: string;
}

export interface ClarificationRequest {
	id: string;
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
	lane?: string;
	branch?: string;
	task?: string;
	currentActor?: string;
	currentStage?: string;
	accessMode: AccessMode;
	runState: RunState;
	transportState: TransportState;
	pendingApproval?: RequestCard;
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
	acceptedIntakeSummary?: AcceptedIntakeSummary;
}

export type ModelAction =
	| { type: 'submit_prompt'; text: string; now?: string }
	| { type: 'answer_clarification'; text: string; now?: string }
	| { type: 'approve'; now?: string }
	| { type: 'full_access'; now?: string }
	| { type: 'interrupt_run'; now?: string }
	| { type: 'reconnect'; now?: string };

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
			'source_layer' | 'source_actor' | 'source_artifact_ref' | 'turn_type'
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
	};
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
			lane: 'lane/phase-1',
			branch: 'feature/execution-window',
			currentActor: 'intake_shell',
			currentStage: 'idle',
			accessMode: 'approval_required',
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
	now = new Date().toISOString()
): ExecutionWindowModel {
	return {
		...model,
		snapshot: refreshSnapshot(model.snapshot, now, {}),
		feed: [
			...model.feed,
			createFeedItem('error', title, body, true, now, details),
		],
	};
}

function supersedePendingApproval(
	model: ExecutionWindowModel,
	now: string
): FeedItem[] {
	if (!model.snapshot.pendingApproval) {
		return [];
	}

	return [
		createFeedItem(
			'system_status',
			'Pending approval superseded',
			'A new request replaced the previous approval checkpoint.',
			true,
			now
		),
	];
}

function classifyTurn(text: string): TurnType {
	const lower = text.toLowerCase();
	const dialogueTokens = [
		'progress',
		'status',
		'where are we',
		'what are you doing',
		'what is the current',
		"what's the current",
		'why',
		'explain',
		'help me understand',
		'what do you think',
		'should we',
		'which option',
		'compare',
	];

	return dialogueTokens.some((token) => lower.includes(token))
		? 'governor_dialogue'
		: 'governed_work_intent';
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
			body: 'Current progress: intake is waiting on one clarification before the request can continue. Answer it or choose one of the suggested options to move forward.',
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
			],
		};
	}

	if (snapshot.pendingApproval) {
		return {
			body: 'Current progress: orchestration is waiting for explicit acceptance before this request can move into Governor-led work. Use Approve or Full access when you want it to continue.',
			details: [
				`Prompt: ${summarizePrompt(prompt)}`,
				`Current actor: ${actor}`,
				`Current stage: ${stage}`,
				`Current task: ${task ?? 'Not yet accepted'}`,
			],
		};
	}

	if (snapshot.runState === 'running') {
		return {
			body: `Current progress: Governor-led work is running${task ? ` for ${task}` : ''}. Stop is available if you need to interrupt the current run.`,
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
		body: 'No governed work is active yet. Send a bounded request when you want to start, or keep asking progress and idea questions like this one.',
		details: [
			`Prompt: ${summarizePrompt(prompt)}`,
			`Current actor: ${actor}`,
			`Current stage: ${stage}`,
		],
	};
}

function buildAcceptedSummary(
	model: ExecutionWindowModel,
	accessMode: AccessMode
): AcceptedIntakeSummary {
	const task = model.snapshot.task ?? 'Current task';
	const suffix =
		accessMode === 'full_access'
			? ' Accepted. Full access is enabled for this session.'
			: ' Accepted for downstream governor consumption.';

	return {
		title: 'Accepted intake summary',
		body: `${task}${suffix}`,
	};
}

function acceptIntake(
	model: ExecutionWindowModel,
	now: string,
	accessMode: AccessMode,
	turnType: TurnType = 'system'
): ExecutionWindowModel {
	const artifacts = defaultArtifacts();
	const acceptedIntakeSummary = buildAcceptedSummary(model, accessMode);

	return {
		snapshot: refreshSnapshot(model.snapshot, now, {
			currentActor: accessMode === 'full_access' ? 'governor' : 'orchestration',
			currentStage: accessMode === 'full_access' ? 'running' : 'intake_accepted',
			accessMode,
			runState: accessMode === 'full_access' ? 'running' : 'idle',
			pendingApproval: undefined,
			pendingInterrupt: undefined,
			recentArtifacts: artifacts,
			transportState: 'connected',
		}),
		feed: [
			...model.feed,
			createFeedItem(
				'system_status',
				accessMode === 'full_access' ? 'Full access enabled' : 'Intake accepted',
				acceptedIntakeSummary.body,
				true,
				now,
				undefined,
				undefined,
				{ turn_type: turnType }
			),
			...artifacts.map((artifact) => createArtifactFeedItem(artifact, now)),
		],
		activeClarification: undefined,
		acceptedIntakeSummary,
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
					now
				);
			}

			const turnType = classifyTurn(prompt);
			if (turnType === 'governor_dialogue') {
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
							}
						),
					],
				};
			}

			const clarification = buildClarificationRequest(prompt, now);

			const pendingSupersededFeed = supersedePendingApproval(model, now);

			return {
				snapshot: refreshSnapshot(model.snapshot, now, {
					task: summarizePrompt(prompt),
					currentActor: 'intake_shell',
					currentStage: 'clarification_needed',
					runState: 'idle',
					pendingApproval: undefined,
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
						{ turn_type: turnType }
					),
					createFeedItem(
						'shell_event',
						'One detail needed',
						'I need a quick clarification before continuing.',
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
						{ turn_type: turnType }
					),
					createFeedItem(
						'clarification_request',
						clarification.title,
						clarification.body,
						true,
						now,
						undefined,
						undefined,
						{ turn_type: turnType }
					),
				],
				activeClarification: clarification,
			};
		}

		case 'answer_clarification': {
			if (!model.activeClarification) {
				return appendError(
					model,
					'No clarification is active',
					'There is no active clarification request to answer right now.',
					undefined,
					now
				);
			}

			const answer = trimAndNormalize(action.text);
			if (!answer) {
				return appendError(
					model,
					'Clarification answer required',
					'Enter a clarification answer before sending it.',
					undefined,
					now
				);
			}

			const approval: RequestCard = {
				id: nextId('approval'),
				title: 'Accept intake',
				body: 'Approve the intake draft or grant full access so orchestration can continue.',
				requestedAt: now,
			};

			return {
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentActor: 'orchestration',
					currentStage: 'ready_for_acceptance',
					runState: 'idle',
					pendingApproval: approval,
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
						{ turn_type: 'clarification_reply' }
					),
					createFeedItem(
						'shell_event',
						'Draft ready for acceptance',
						'The intake shell updated the draft and handed it back for orchestration acceptance.',
						false,
						now,
						undefined,
						{
							kind: 'status',
							state: 'completed',
							summary: 'Ready for acceptance',
						},
						{ turn_type: 'clarification_reply' }
					),
					createFeedItem(
						'approval_request',
						approval.title,
						approval.body,
						true,
						now,
						undefined,
						undefined,
						{ turn_type: 'clarification_reply' }
					),
				],
				activeClarification: undefined,
				acceptedIntakeSummary: undefined,
			};
		}

		case 'approve': {
			if (!model.snapshot.pendingApproval) {
				return appendError(
					model,
					'No approval is active',
					'There is no approval request to approve right now.',
					undefined,
					now
				);
			}

			return acceptIntake(model, now, model.snapshot.accessMode, 'approval_action');
		}

		case 'full_access': {
			if (!model.snapshot.pendingApproval) {
				return appendError(
					model,
					'No approval is active',
					'There is no approval request to grant full access for right now.',
					undefined,
					now
				);
			}

			return acceptIntake(model, now, 'full_access', 'approval_action');
		}

		case 'interrupt_run': {
			if (model.snapshot.runState !== 'running') {
				return appendError(
					model,
					'Nothing is running',
					'Stop is only available while governed work is actively running.',
					undefined,
					now
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
						now
					),
				],
			};
		}

			const interrupt: RequestCard = {
				id: nextId('interrupt'),
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
					createFeedItem(
						'interrupt_request',
						interrupt.title,
						interrupt.body,
						true,
						now,
						undefined,
						undefined,
						{ turn_type: 'stop_action' }
					),
				],
			};
		}

		case 'reconnect':
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
						now
					),
				],
			};
	}
}
