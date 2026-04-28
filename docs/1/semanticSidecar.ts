import { spawn } from 'child_process';
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
const SEMANTIC_MAX_OUTPUT_BYTES = 1024 * 1024;

type SemanticControllerState = {
	current_actor?: string;
	current_stage?: string;
	permission_scope: string;
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
	pending_permission_request: null | {
		title: string;
		body: string;
		recommended_scope?: string;
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

export type SemanticBlockKind =
	| 'needs_disambiguation'
	| 'semantic_unavailable'
	| 'control_unmappable'
	| 'nothing_running'
	| 'interrupt_pending'
	| 'no_active_clarification';

export type SemanticResolution =
	| {
			kind: 'dispatch';
			action: ModelAction;
			nextLoopState: undefined;
	  }
	| {
			kind: 'block';
			blockKind: SemanticBlockKind;
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
			enum: ['interrupt_run', 'none'],
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
				item.type === 'permission_request' ||
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
			permission_scope: model.snapshot.permissionScope,
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
		pending_permission_request: model.snapshot.pendingPermissionRequest
			? {
					title: model.snapshot.pendingPermissionRequest.title,
					body: model.snapshot.pendingPermissionRequest.body,
					recommended_scope: model.snapshot.pendingPermissionRequest.recommendedScope,
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
		had_pending_permission_request: Boolean(summary.pending_permission_request),
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
		'- with a run in progress, "stop" => explicit_action / interrupt_run',
		'- "stop and tell me what happened" => block',
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
		actionName === 'interrupt_run' || actionName === 'none'
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
				const child = spawn('codex', args, {
					env: {
						...process.env,
					},
					stdio: ['pipe', 'pipe', 'pipe'],
				});
				child.stdin.end();

				let settled = false;
				let stdout = '';
				let stderr = '';
				let timedOut = false;

				const finish = (callback: () => void) => {
					if (settled) {
						return;
					}
					settled = true;
					clearTimeout(timeoutHandle);
					callback();
				};

				const appendOutput = (
					current: string,
					chunk: Buffer | string,
					label: 'stdout' | 'stderr'
				) => {
					const next = current + chunk.toString();
					if (next.length > SEMANTIC_MAX_OUTPUT_BYTES) {
						child.kill('SIGTERM');
						finish(() =>
							reject(
								new Error(
									`Corgi semantic sidecar ${label} exceeded ${SEMANTIC_MAX_OUTPUT_BYTES} bytes.`
								)
							)
						);
						return current;
					}
					return next;
				};

				const timeoutHandle = setTimeout(() => {
					timedOut = true;
					child.kill('SIGTERM');
				}, SEMANTIC_TIMEOUT_MS);

				child.on('error', (error) => {
					finish(() => reject(error));
				});

				child.stdout.on('data', (chunk) => {
					stdout = appendOutput(stdout, chunk, 'stdout');
				});
				child.stderr.on('data', (chunk) => {
					stderr = appendOutput(stderr, chunk, 'stderr');
				});

				child.on('close', (code, signal) => {
					finish(() => {
						if (timedOut) {
							reject(
								new Error(
									stderr.trim() ||
										stdout.trim() ||
										`Corgi semantic sidecar timed out after ${SEMANTIC_TIMEOUT_MS}ms.`
								)
							);
							return;
						}
						if (code !== 0) {
							reject(
								new Error(
									stderr.trim() ||
										stdout.trim() ||
										(signal
											? `Corgi semantic sidecar exited via ${signal}.`
											: `Corgi semantic sidecar exited with code ${code}.`)
								)
							);
							return;
						}
						resolve(stdout);
					});
				});
			});

			const payload = fs.existsSync(outputPath)
				? fs.readFileSync(outputPath, 'utf8')
				: stdout;
			return normalizeDecision(JSON.parse(payload), input.rawText);
		} catch (error) {
			console.error('Corgi semantic sidecar failed', error);
			return {
				route_type: 'block',
				action_name: 'none',
				normalized_text: input.rawText.trim(),
				paraphrase: '',
				confidence: 'low',
				reason: 'semantic_sidecar_unavailable',
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

function semanticBlockKindForDecision(decision: SemanticDecision): SemanticBlockKind {
	return decision.reason === 'semantic_sidecar_unavailable' ||
		decision.reason === 'semantic_sidecar_error'
		? 'semantic_unavailable'
		: 'needs_disambiguation';
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
			blockKind: semanticBlockKindForDecision(decision),
			semantic: metadata,
			nextLoopState: loopState,
		};
	}

	if (decision.confidence !== 'high' || decision.route_type === 'block') {
		const nextAttempt = currentAttempts + 1;
		if (nextAttempt > SEMANTIC_CLARIFICATION_BUDGET) {
			return {
				kind: 'block',
				blockKind: semanticBlockKindForDecision(decision),
				semantic: metadata,
				nextLoopState: {
					attempts: SEMANTIC_CLARIFICATION_BUDGET,
					exhausted: true,
					lastQuestion: decision.reason,
				},
			};
		}
		return {
			kind: 'block',
			blockKind: semanticBlockKindForDecision(decision),
			semantic: metadata,
			nextLoopState: {
				attempts: nextAttempt,
				exhausted: false,
				lastQuestion: decision.reason,
			},
		};
	}

	if (decision.route_type === 'explicit_action') {
		if (decision.action_name === 'none') {
			return {
				kind: 'block',
				blockKind: 'control_unmappable',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion: 'control_unmappable',
				},
			};
		}
		if (decision.action_name === 'interrupt_run' && model.snapshot.runState !== 'running') {
			return {
				kind: 'block',
				blockKind: 'nothing_running',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion: 'nothing_running',
				},
			};
		}
		if (
			decision.action_name === 'interrupt_run' &&
			Boolean(model.snapshot.pendingInterrupt)
		) {
			return {
				kind: 'block',
				blockKind: 'interrupt_pending',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion: 'interrupt_pending',
				},
			};
		}

		const mappedAction: ModelAction =
			{ type: 'interrupt_run', text: rawText, ...metadata };
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
				blockKind: 'no_active_clarification',
				semantic: metadata,
				nextLoopState: {
					attempts: 1,
					exhausted: false,
					lastQuestion: 'no_active_clarification',
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
		let decision: SemanticDecision;
		try {
			decision = await this.runner.classify({ rawText, summary });
		} catch (error) {
			console.error('Corgi semantic sidecar failed', error);
			decision = {
				route_type: 'block',
				action_name: 'none',
				normalized_text: rawText.trim(),
				paraphrase: '',
				confidence: 'low',
				reason: 'semantic_sidecar_unavailable',
			};
		}
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
