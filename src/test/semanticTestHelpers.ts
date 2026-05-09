import {
	createInitialModel,
	type ExecutionWindowModel,
	type SemanticActionName,
	type SemanticRouteType,
} from '../phase1Model';
import {
	type AppServerSemanticRunner,
	type SemanticDecision,
	type SemanticRunner,
} from '../semanticSidecar';

export function semanticContextFlags() {
	return {
		used_controller_summary: true,
		used_accepted_intake_summary: false,
		used_dialogue_summary: false,
		had_active_clarification: false,
		had_pending_permission_request: false,
		had_pending_interrupt: false,
	};
}

export function semanticDecision(
	overrides: Partial<SemanticDecision>
): SemanticDecision {
	return {
		route_type: 'governed_work_intent',
		action_name: 'none',
		normalized_text: 'analyze the repo',
		paraphrase: 'Ask Corgi to analyze the repo.',
		confidence: 'high',
		reason: 'clear_work_intent',
		...overrides,
	};
}

export function semanticRunnerInput(
	rawText: string
): Parameters<AppServerSemanticRunner['classify']>[0] {
	return {
		rawText,
		summary: {
			current_turn: rawText,
			controller_state: {
				permission_scope: 'unset',
				run_state: 'idle',
			},
			active_clarification: null,
			pending_permission_request: null,
			pending_interrupt: null,
			accepted_intake_summary: null,
			recent_dialogue_summary: [],
			semantic_clarification_state: null,
		},
	};
}

export function semanticFallbackRunner(decision: SemanticDecision): SemanticRunner {
	return {
		classify: async () => decision,
	};
}

export type SemanticRoutingFixture = {
	name: string;
	input: string;
	session_state: 'idle' | 'active_clarification' | 'pending_permission' | 'running';
	expected_route_type: SemanticRouteType;
	expected_action_name: SemanticActionName;
	expected_outcome:
		| 'submit_prompt'
		| 'answer_clarification'
		| 'interrupt_run'
		| 'block';
	notes: string;
};

export function semanticFixtureModel(
	state: SemanticRoutingFixture['session_state']
): ExecutionWindowModel {
	const model = createInitialModel('2026-04-10T10:00:00.000Z');
	if (state === 'active_clarification') {
		return {
			...model,
			activeClarification: {
				id: 'clarification-test',
				contextRef: 'clarification-test',
				title: 'Clarification required',
				body: 'What kind of analysis do you want?',
				requestedAt: '2026-04-10T10:00:00.000Z',
				options: [
					{
						id: 'architecture',
						label: 'Architecture',
						answer: 'Focus on architecture.',
					},
				],
				allowFreeText: true,
			},
		};
	}
	if (state === 'pending_permission') {
		return {
			...model,
			snapshot: {
				...model.snapshot,
				currentActor: 'orchestration',
				currentStage: 'permission_needed',
				pendingPermissionRequest: {
					id: 'permission-test',
					contextRef: 'permission-test',
					title: 'Permission needed',
					body: 'Choose Plan to continue this request.',
					requestedAt: '2026-04-10T10:00:00.000Z',
					recommendedScope: 'plan',
					allowedScopes: ['observe', 'plan', 'execute'],
				},
			},
		};
	}
	if (state === 'running') {
		return {
			...model,
			snapshot: {
				...model.snapshot,
				currentActor: 'governor',
				currentStage: 'running',
				runState: 'running',
			},
		};
	}
	return model;
}
