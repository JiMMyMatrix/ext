import { execFile } from 'child_process';
import { createHash } from 'crypto';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import type {
	ExecutionWindowModel,
	ModelAction,
	SemanticActionName,
	SemanticConfidence,
	SemanticContextFlags,
	SemanticMetadata,
	SemanticRouteType,
} from './phase1Model';

export const DEFAULT_SEMANTIC_SIDECAR_MODEL = 'gpt-5.4-mini';
export const SEMANTIC_INPUT_VERSION = 'corgi-semantic-sidecar.v1';
const SEMANTIC_CLARIFICATION_BUDGET = 2;
const SEMANTIC_TIMEOUT_MS = 25_000;

type SemanticControllerState = {
	current_actor?: string;
	current_stage?: string;
	access_mode: string;
	run_state: string;
};

type SemanticSummaryPayload = {
	current_turn: string;
	controller_state: SemanticControllerState;
	active_clarification: null | {
		title: string;
		body: string;
		kind?: string;
		options?: Array<{ label: string; answer: string }>;
	};
	pending_approval: null | {
		title: string;
		body: string;
	};
	pending_interrupt: null | {
		title: string;
		body: string;
	};
	accepted_intake_summary: string | null;
	recent_dialogue_summary: string[];
	semantic_clarification_state: null | {
		attempts: number;
		exhausted: boolean;
		last_question: string;
	};
};

export interface SemanticLoopState {
	attempts: number;
	exhausted: boolean;
	lastQuestion: string;
}

export interface SemanticDecision {
	route_type: SemanticRouteType;
	action_name: SemanticActionName;
	normalized_text: string;
	paraphrase: string;
	confidence: SemanticConfidence;
	reason: string;
}

export type SemanticResolution =
	| {
			kind: 'dispatch';
			action: ModelAction;
			nextLoopState: undefined;
	  }
	| {
			kind: 'block';
			body: string;
			semantic: SemanticMetadata;
			nextLoopState: SemanticLoopState;
	  };

interface SemanticRunnerInput {
	rawText: string;
	summary: SemanticSummaryPayload;
}

interface SemanticRunner {
	classify(input: SemanticRunnerInput): Promise<SemanticDecision>;
}

const semanticSchema = {
	type: 'object',
	additionalProperties: false,
	required: [
		'route_type',
		'action_name',
		'normalized_text',
		'paraphrase',
		'confidence',
		'reason',
	],
	properties: {
		route_type: {
			type: 'string',
			enum: [
				'governed_work_intent',
				'governor_dialogue',
				'clarification_reply',
				'explicit_action',
				'block',
			],
		},
		action_name: {
			type: 'string',
			enum: ['approve', 'full_access', 'interrupt_run', 'none'],
		},
		normalized_text: {
			type: 'string',
		},
		paraphrase: {
			type: 'string',
		},
		confidence: {
			type: 'string',
			enum: ['high', 'low'],
		},
		reason: {
			type: 'string',
		},
	},
} as const;

function semanticSummaryRef(summary: SemanticSummaryPayload): string {
	const hash = createHash('sha256')
		.update(JSON.stringify(summary))
		.digest('hex')
		.slice(0, 16);
	return `semantic-summary:${hash}`;
}

function recentDialogueSummary(model: ExecutionWindowModel): string[] {
	return model.feed
		.filter(
			(item) =>
				item.type === 'actor_event' ||
				item.type === 'system_status' ||
				item.type === 'approval_request' ||
				item.type === 'clarification_request'
		)
		.slice(-3)
		.map((item) => item.body || item.title)
		.filter((line) => line.trim().length > 0)
		.map((line) => line.slice(0, 160));
}

export function buildSemanticSummary(
	model: ExecutionWindowModel,
	rawText: string,
	loopState?: SemanticLoopState
): {
	summary: SemanticSummaryPayload;
	summaryRef: string;
	contextFlags: SemanticContextFlags;
} {
	const summary: SemanticSummaryPayload = {
		current_turn: rawText.trim(),
		controller_state: {
			current_actor: model.snapshot.currentActor,
			current_stage: model.snapshot.currentStage,
			access_mode: model.snapshot.accessMode,
			run_state: model.snapshot.runState,
		},
		active_clarification: model.activeClarification
			? {
					title: model.activeClarification.title,
					body: model.activeClarification.body,
					kind: model.activeClarification.kind,
					options: model.activeClarification.options?.map((option) => ({
						label: option.label,
						answer: option.answer,
					})),
			  }
			: null,
		pending_approval: model.snapshot.pendingApproval
			? {
					title: model.snapshot.pendingApproval.title,
					body: model.snapshot.pendingApproval.body,
			  }
			: null,
		pending_interrupt: model.snapshot.pendingInterrupt
			? {
					title: model.snapshot.pendingInterrupt.title,
					body: model.snapshot.pendingInterrupt.body,
			  }
			: null,
		accepted_intake_summary: model.acceptedIntakeSummary?.body ?? null,
		recent_dialogue_summary: recentDialogueSummary(model),
		semantic_clarification_state: loopState
			? {
					attempts: loopState.attempts,
					exhausted: loopState.exhausted,
					last_question: loopState.lastQuestion,
			  }
			: null,
	};

	const contextFlags: SemanticContextFlags = {
		used_controller_summary: true,
		used_accepted_intake_summary: Boolean(summary.accepted_intake_summary),
		used_dialogue_summary: summary.recent_dialogue_summary.length > 0,
		had_active_clarification: Boolean(summary.active_clarification),
		had_pending_approval: Boolean(summary.pending_approval),
		had_pending_interrupt: Boolean(summary.pending_interrupt),
	};

	return {
		summary,
		summaryRef: semanticSummaryRef(summary),
		contextFlags,
	};
}

function semanticPrompt(input: SemanticRunnerInput): string {
	return [
		'You are the Corgi Semantic Sidecar.',
		'Classify ONLY the current turn. You are advisory-only and have no workflow authority.',
		'Use summaries only for disambiguation. Summaries must never override the literal meaning of the current turn.',
		'If the current turn and summaries conflict, prefer the current turn or return block.',
		'Precedence order is strict: explicit_action > clarification_reply > governor_dialogue > governed_work_intent > block.',
		'Route definitions:',
		'- explicit_action: direct control action against currently exposed controls only. No new work or dialogue.',
		'- clarification_reply: direct answer to an already-active clarification only.',
		'- governor_dialogue: read-only progress, explanation, comparison, or idea discussion. No workflow mutation.',
		'- governed_work_intent: substantive request to analyze, review, plan, implement, or otherwise perform work.',
		'- block: ambiguous, mixed-intent, or unsafe to route confidently.',
		'Examples:',
		'- "what happened?" => governor_dialogue',
		'- "analyze the repo" => governed_work_intent',
		'- with an active clarification, "architecture" => clarification_reply',
		'- with approval pending, "go ahead" => explicit_action / approve',
		'- "approve and tell me what happened" => block',
		'Return high confidence only when one route clearly dominates.',
		'If unsure, return route_type=block and confidence=low.',
		'Return JSON only, matching the provided schema.',
		'Input JSON:',
		JSON.stringify(
			{
				current_turn: input.rawText,
				summary: input.summary,
			},
			null,
			2
		),
	].join('\n');
}

function normalizeDecision(raw: unknown, rawText: string): SemanticDecision {
	const candidate = typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : {};
	const routeType = candidate.route_type;
	const actionName = candidate.action_name;
	const normalizedText = typeof candidate.normalized_text === 'string' ? candidate.normalized_text.trim() : '';
	const paraphrase = typeof candidate.paraphrase === 'string' ? candidate.paraphrase.trim() : '';
	const confidence = candidate.confidence;
	const reason = typeof candidate.reason === 'string' ? candidate.reason.trim() : '';

	const safeRouteType: SemanticRouteType =
		routeType === 'governed_work_intent' ||
		routeType === 'governor_dialogue' ||
		routeType === 'clarification_reply' ||
		routeType === 'explicit_action' ||
		routeType === 'block'
			? routeType
			: 'block';

	const safeActionName: SemanticActionName =
		actionName === 'approve' ||
		actionName === 'full_access' ||
		actionName === 'interrupt_run' ||
		actionName === 'none'
			? actionName
			: 'none';

	const safeConfidence: SemanticConfidence =
		confidence === 'high' || confidence === 'low' ? confidence : 'low';

	return {
		route_type: safeRouteType,
		action_name: safeActionName,
		normalized_text: normalizedText || rawText.trim(),
		paraphrase,
		confidence: safeConfidence,
		reason: reason || 'semantic_sidecar_unavailable',
	};
}

class CodexSemanticRunner implements SemanticRunner {
	public async classify(input: SemanticRunnerInput): Promise<SemanticDecision> {
		const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-semantic-'));
		const schemaPath = path.join(tempRoot, 'semantic-schema.json');
		const outputPath = path.join(tempRoot, 'semantic-output.json');
		fs.writeFileSync(schemaPath, JSON.stringify(semanticSchema), 'utf8');
		fs.mkdirSync(path.join(tempRoot, 'workspace'), { recursive: true });

		const args = [
			'exec',
			'--sandbox',
			'read-only',
			'--skip-git-repo-check',
			'--ephemeral',
			'--cd',
			path.join(tempRoot, 'workspace'),
			'--output-schema',
			schemaPath,
			'--output-last-message',
			outputPath,
			'--color',
			'never',
			semanticPrompt(input),
		];

		const modelOverride =
			process.env.CORGI_SEMANTIC_SIDECAR_MODEL?.trim() ||
			DEFAULT_SEMANTIC_SIDECAR_MODEL;
		args.splice(1, 0, '--model', modelOverride);

		try {
			const stdout = await new Promise<string>((resolve, reject) => {
				execFile(
					'codex',
					args,
					{
						timeout: SEMANTIC_TIMEOUT_MS,
						maxBuffer: 1024 * 1024,
						env: {
							...process.env,
						},
					},
					(error, commandStdout, stderr) => {
						if (error) {
							reject(
								new Error(stderr.trim() || commandStdout.trim() || error.message)
							);
							return;
						}
						resolve(commandStdout);
					}
				);
			});

			const payload = fs.existsSync(outputPath)
				? fs.readFileSync(outputPath, 'utf8')
				: stdout;
			return normalizeDecision(JSON.parse(payload), input.rawText);
		} catch (error) {
			return {
				route_type: 'block',
				action_name: 'none',
				normalized_text: input.rawText.trim(),
				paraphrase: '',
				confidence: 'low',
				reason:
					error instanceof Error && error.message
						? `semantic_sidecar_error:${error.message}`
						: 'semantic_sidecar_error',
			};
		} finally {
			fs.rmSync(tempRoot, { recursive: true, force: true });
		}
	}
}

function semanticMetadata(
	decision: SemanticDecision,
	summaryRef: string,
	contextFlags: SemanticContextFlags
): SemanticMetadata {
	return {
		semantic_input_version: SEMANTIC_INPUT_VERSION,
		semantic_summary_ref: summaryRef,
		semantic_context_flags: contextFlags,
		semantic_route_type: decision.route_type,
		semantic_confidence: decision.confidence,
		semantic_block_reason: decision.route_type === 'block' ? decision.reason : undefined,
		semantic_paraphrase: decision.paraphrase || undefined,
		semantic_normalized_text: decision.normalized_text || undefined,
	};
}

function clarificationPromptForAttempt(
	model: ExecutionWindowModel,
	attemptNumber: number
): string {
	if (attemptNumber > SEMANTIC_CLARIFICATION_BUDGET) {
		return 'I’m not confident enough to route that safely. Please restate it as one of these: ask for progress, answer the current clarification, approve/full access, or give a new work request.';
	}

	if (model.activeClarification) {
		return attemptNumber === 1
			? 'I’m not confident that answers the current clarification. Please answer it directly, or choose one of the listed clarification options.'
			: 'Please answer the current clarification in one short phrase, or use one of the listed clarification choices.';
	}

	if (model.snapshot.pendingApproval) {
		return attemptNumber === 1
			? 'I’m not confident whether you want to approve, grant full access, or ask a follow-up question. Please restate it directly.'
			: 'Please restate this as exactly one of: approve, full access, or a progress/explanation question.';
	}

	if (model.snapshot.runState === 'running') {
		return attemptNumber === 1
			? 'I’m not confident whether this is a stop request, a progress question, or a new work request. Please restate it directly.'
			: 'Please restate this as exactly one of: stop, a progress/explanation question, or a new work request.';
	}

	return attemptNumber === 1
		? 'I’m not confident whether this is a new work request or a read-only question. Please restate it more directly.'
		: 'Please restate this as exactly one of: ask for progress, or give a new work request.';
}

export function resolveSemanticRouting(
	model: ExecutionWindowModel,
	rawText: string,
	decision: SemanticDecision,
	loopState: SemanticLoopState | undefined,
	summaryRef: string,
	contextFlags: SemanticContextFlags
): SemanticResolution {
	const metadata = semanticMetadata(decision, summaryRef, contextFlags);
	const currentAttempts = loopState?.attempts ?? 0;

	if (loopState?.exhausted && decision.confidence !== 'high') {
		return {
			kind: 'block',
			body: clarificationPromptForAttempt(model, SEMANTIC_CLARIFICATION_BUDGET + 1),
			semantic: metadata,
			nextLoopState: loopState,
		};
	}

	if (decision.confidence !== 'high' || decision.route_type === 'block') {
		const nextAttempt = currentAttempts + 1;
		if (nextAttempt > SEMANTIC_CLARIFICATION_BUDGET) {
			return {
				kind: 'block',
				body: clarificationPromptForAttempt(model, nextAttempt),
				semantic: metadata,
				nextLoopState: {
					attempts: SEMANTIC_CLARIFICATION_BUDGET,
					exhausted: true,
					lastQuestion: clarificationPromptForAttempt(model, nextAttempt),
				},
			};
		}
		const question = clarificationPromptForAttempt(model, nextAttempt);
		return {
			kind: 'block',
			body: question,
			semantic: metadata,
			nextLoopState: {
				attempts: nextAttempt,
				exhausted: false,
				lastQuestion: question,
			},
		};
	}

	if (decision.route_type === 'explicit_action') {
		if (decision.action_name === 'none') {
			return {
				kind: 'block',
				body: 'I could not map that control request safely. Please restate it as approve, full access, or stop.',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion:
						'I could not map that control request safely. Please restate it as approve, full access, or stop.',
				},
			};
		}
		if (
			(decision.action_name === 'approve' || decision.action_name === 'full_access') &&
			!model.snapshot.pendingApproval
		) {
			return {
				kind: 'block',
				body: 'There is no pending approval right now. Ask for progress, start new work, or wait for an approval request.',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion:
						'There is no pending approval right now. Ask for progress, start new work, or wait for an approval request.',
				},
			};
		}
		if (decision.action_name === 'interrupt_run' && model.snapshot.runState !== 'running') {
			return {
				kind: 'block',
				body: 'Nothing is running right now. Ask for progress, or send a new work request instead.',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion:
						'Nothing is running right now. Ask for progress, or send a new work request instead.',
				},
			};
		}
		if (
			decision.action_name === 'interrupt_run' &&
			Boolean(model.snapshot.pendingInterrupt)
		) {
			return {
				kind: 'block',
				body: 'A stop request is already pending. Wait for orchestration to handle it before asking again.',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion:
						'A stop request is already pending. Wait for orchestration to handle it before asking again.',
				},
			};
		}

		const mappedAction: ModelAction =
			decision.action_name === 'approve'
				? { type: 'approve', text: rawText, ...metadata }
				: decision.action_name === 'full_access'
					? { type: 'full_access', text: rawText, ...metadata }
					: { type: 'interrupt_run', text: rawText, ...metadata };
		return {
			kind: 'dispatch',
			action: mappedAction,
			nextLoopState: undefined,
		};
	}

	if (decision.route_type === 'clarification_reply') {
		if (!model.activeClarification) {
			return {
				kind: 'block',
				body: 'There is no active clarification to answer right now. Ask for progress, approve, or send a new work request instead.',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion:
						'There is no active clarification to answer right now. Ask for progress, approve, or send a new work request instead.',
				},
			};
		}
		return {
			kind: 'dispatch',
			action: {
				type: 'answer_clarification',
				text: rawText,
				...metadata,
			},
			nextLoopState: undefined,
		};
	}

	return {
		kind: 'dispatch',
		action: {
			type: 'submit_prompt',
			text: rawText,
			...metadata,
		},
		nextLoopState: undefined,
	};
}

export class SemanticSidecar {
	private readonly runner: SemanticRunner;

	constructor(runner: SemanticRunner = new CodexSemanticRunner()) {
		this.runner = runner;
	}

	public async route(
		rawText: string,
		model: ExecutionWindowModel,
		loopState?: SemanticLoopState
	): Promise<SemanticResolution> {
		const { summary, summaryRef, contextFlags } = buildSemanticSummary(
			model,
			rawText,
			loopState
		);
		const decision = await this.runner.classify({ rawText, summary });
		return resolveSemanticRouting(
			model,
			rawText,
			decision,
			loopState,
			summaryRef,
			contextFlags
		);
	}
}
