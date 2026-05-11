export type FeedItemType =
	| 'user_message'
	| 'shell_event'
	| 'system_status'
	| 'actor_event'
	| 'clarification_request'
	| 'permission_request'
	| 'interrupt_request'
	| 'artifact_reference'
	| 'error';

export type NonArtifactFeedItemType = Exclude<FeedItemType, 'artifact_reference'>;

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
	workRef?: string;
	planRef?: string;
	revisionReason?: string;
	latestReviewRef?: string;
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
	currentWorkRef?: string;
	currentParallelSetRef?: string;
	activeParallelDispatchCount?: number;
	currentGoalRef?: string;
	currentGoalTitle?: string;
	currentGoalStepRef?: string;
	currentGoalStepIndex?: number;
	goalStepCount?: number;
	goalStatus?: 'active' | 'blocked' | 'completed';
	latestGoalDecisionRef?: string;
	currentPlanVersion?: number;
	currentAttemptNumber?: number;
	latestReviewRef?: string;
	latestReviewVerdict?: 'pass' | 'request_changes' | 'inconclusive';
	latestGovernorDecisionRef?: string;
	latestGovernorDecision?: 'accept' | 'reject' | 'needs_review' | 'needs_verification';
	snapshotFreshness: SnapshotFreshness;
}

export interface FeedItemShared {
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

export interface FeedItemBase extends FeedItemShared {
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
