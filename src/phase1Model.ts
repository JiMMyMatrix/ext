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

export interface ClarificationRequest {
	id: string;
	title: string;
	body: string;
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
	| { type: 'decline_or_hold'; now?: string }
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
			id: 'artifact-extension',
			label: 'src/extension.ts',
			path: 'src/extension.ts',
			status: 'active',
			summary: 'Extension entrypoint and command registration.',
			authoritative: true,
		},
		{
			id: 'artifact-package',
			label: 'package.json',
			path: 'package.json',
			status: 'referenced',
			summary: 'Manifest contribution and command metadata.',
			authoritative: true,
		},
	];
}

function createFeedItem(
	type: NonArtifactFeedItemType,
	title: string,
	body: string | undefined,
	authoritative: boolean,
	now: string,
	details?: string[],
	activity?: ActivityMetadata
): FeedItemBase {
	return {
		id: nextId(type),
		type,
		timestamp: now,
		title,
		body,
		details,
		authoritative,
		activity,
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
					'Enter a prompt before sending it to the execution window.',
					undefined,
					now
				);
			}

			const clarification: ClarificationRequest = {
				id: nextId('clarification'),
				title: 'Clarification required',
				body: 'Name one detail the execution window must keep visible at all times.',
				placeholder: 'Example: Keep current actor and current stage visible in the header.',
				requestedAt: now,
			};

			return {
				snapshot: refreshSnapshot(model.snapshot, now, {
					task: summarizePrompt(prompt),
					currentActor: 'intake_shell',
					currentStage: 'clarification_needed',
					pendingApproval: undefined,
					pendingInterrupt: undefined,
					recentArtifacts: [],
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'user_message',
						'Prompt submitted',
						prompt,
						false,
						now
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
						}
					),
					createFeedItem(
						'clarification_request',
						clarification.title,
						clarification.body,
						true,
						now
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

			const acceptedSummary: AcceptedIntakeSummary = {
				title: 'Accepted intake summary',
				body: `${model.snapshot.task ?? 'Phase-1 execution window'} Keep visible: ${answer}.`,
			};

			const approval: RequestCard = {
				id: nextId('approval'),
				title: 'Approval requested',
				body: 'Approve the accepted intake so execution can continue.',
				requestedAt: now,
			};

			return {
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentActor: 'governor',
					currentStage: 'approval_requested',
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
						now
					),
					createFeedItem(
						'shell_event',
						'Clarification recorded',
						'The intake shell updated the draft and handed it back for acceptance.',
						false,
						now,
						undefined,
						{
							kind: 'status',
							state: 'completed',
							summary: 'Intake accepted upstream',
						}
					),
					createFeedItem(
						'system_status',
						'Accepted intake received',
						acceptedSummary.body,
						true,
						now
					),
					createFeedItem(
						'approval_request',
						approval.title,
						approval.body,
						true,
						now
					),
				],
				activeClarification: undefined,
				acceptedIntakeSummary: acceptedSummary,
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

			const artifacts = defaultArtifacts();

			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentActor: 'executor',
					currentStage: 'running',
					pendingApproval: undefined,
					recentArtifacts: artifacts,
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'system_status',
						'Approval granted',
						'Execution can continue with the accepted intake.',
						true,
						now
					),
					createFeedItem(
						'actor_event',
						'Read src/executionWindowPanel.ts',
						'Inspected the extension webview surface before continuing.',
						true,
						now,
						undefined,
						{
							kind: 'read',
							state: 'completed',
							path: 'src/executionWindowPanel.ts',
						}
					),
					createFeedItem(
						'actor_event',
						'Ran npm run check-types',
						'Verified the current TypeScript surface.',
						true,
						now,
						['Command output is collapsed by default in the execution feed.'],
						{
							kind: 'command',
							state: 'completed',
							command: 'npm run check-types',
							elapsedMs: 1200,
						}
					),
					...artifacts.map((artifact) => createArtifactFeedItem(artifact, now)),
				],
			};
		}

		case 'decline_or_hold': {
			if (!model.snapshot.pendingApproval) {
				return appendError(
					model,
					'No approval is active',
					'There is no approval request to hold right now.',
					undefined,
					now
				);
			}

			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentActor: 'governor',
					currentStage: 'on_hold',
					pendingApproval: undefined,
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'system_status',
						'Approval held',
						'The run is paused until a new prompt or approval arrives.',
						true,
						now
					),
				],
			};
		}

		case 'interrupt_run': {
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
							'Interrupt already pending',
							'Wait for the authoritative interrupt status to change before sending another request.',
							false,
							now
						),
					],
				};
			}

			const interrupt: RequestCard = {
				id: nextId('interrupt'),
				title: 'Interrupt requested',
				body: 'An interrupt request was sent downstream and is awaiting authoritative follow-up.',
				requestedAt: now,
			};

			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					currentStage: 'interrupt_requested',
					pendingInterrupt: interrupt,
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'interrupt_request',
						interrupt.title,
						interrupt.body,
						true,
						now
					),
				],
			};
		}

		case 'reconnect':
			return {
				...model,
				snapshot: refreshSnapshot(model.snapshot, now, {
					transportState: 'connected',
				}),
				feed: [
					...model.feed,
					createFeedItem(
						'system_status',
						'Connection refreshed',
						'A fresh snapshot is now available in the execution window.',
						true,
						now
					),
				],
			};
	}
}
