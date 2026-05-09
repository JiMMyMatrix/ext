import * as assert from 'assert';
import * as fs from 'fs';
import * as path from 'path';
import { applyModelAction, createInitialModel } from '../phase1Model';
import {
	AppServerSemanticRunner,
	createSemanticRunner,
	CodexSemanticRunner,
	DEFAULT_SEMANTIC_SIDECAR_MODEL,
	resolveSemanticRouting,
	SemanticSidecar,
	type SemanticRunner,
} from '../semanticSidecar';
import {
	EXECUTION_WINDOW_CLIENT_SCRIPT_TS_PATH,
	EXECUTION_WINDOW_PANEL_TS_PATH,
	EXECUTION_WINDOW_RENDERER_TS_PATH,
	EXECUTION_WINDOW_STYLES_TS_PATH,
	SEMANTIC_ROUTING_FIXTURE_PATH,
} from './testPaths';
import {
	semanticContextFlags,
	semanticDecision,
	semanticFallbackRunner,
	semanticFixtureModel,
	type SemanticRoutingFixture,
	semanticRunnerInput,
} from './semanticTestHelpers';

function readExecutionWindowSource(): string {
	return [
		fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8'),
		fs.readFileSync(EXECUTION_WINDOW_RENDERER_TS_PATH, 'utf8'),
		fs.readFileSync(EXECUTION_WINDOW_CLIENT_SCRIPT_TS_PATH, 'utf8'),
		fs.readFileSync(EXECUTION_WINDOW_STYLES_TS_PATH, 'utf8'),
	].join('\n');
}

suite('Corgi Semantic Sidecar', () => {
	test('semantic sidecar defaults to gpt-5.4-mini', () => {
		assert.strictEqual(DEFAULT_SEMANTIC_SIDECAR_MODEL, 'gpt-5.4-mini');
	});

	test('semantic routing maps stop intent only when a run is active', () => {
		const runningModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'What is happening?',
			semantic_route_type: 'governor_dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});
		const activeRunModel = {
			...runningModel,
			snapshot: {
				...runningModel.snapshot,
				runState: 'running' as const,
			},
		};
		const resolution = resolveSemanticRouting(
			activeRunModel,
			'stop',
			semanticDecision({
				route_type: 'explicit_action',
				action_name: 'interrupt_run',
				normalized_text: 'stop',
				paraphrase: 'Stop the current run.',
			}),
			undefined,
			'semantic-summary:test',
			{
				...semanticContextFlags(),
				had_pending_interrupt: false,
			}
		);

		assert.strictEqual(resolution.kind, 'dispatch');
		if (resolution.kind === 'dispatch') {
			assert.strictEqual(resolution.action.type, 'interrupt_run');
			assert.strictEqual(resolution.action.text, 'stop');
			assert.strictEqual(resolution.action.semantic_route_type, 'explicit_action');
		}
	});

	test('semantic routing blocks clarification replies when no clarification is active', () => {
		const resolution = resolveSemanticRouting(
			createInitialModel('2026-04-10T10:00:00.000Z'),
			'architecture',
			semanticDecision({
				route_type: 'clarification_reply',
				normalized_text: 'architecture',
				paraphrase: 'Answer the current clarification with architecture.',
			}),
			undefined,
			'semantic-summary:test',
			semanticContextFlags()
		);

		assert.strictEqual(resolution.kind, 'block');
		if (resolution.kind === 'block') {
			assert.strictEqual(resolution.blockKind, 'no_active_clarification');
		}
	});

	test('semantic routing exhausts the clarification budget conservatively', () => {
		const resolution = resolveSemanticRouting(
			createInitialModel('2026-04-10T10:00:00.000Z'),
			'do whatever is best',
			semanticDecision({
				route_type: 'block',
				action_name: 'none',
				normalized_text: 'do whatever is best',
				paraphrase: '',
				confidence: 'low',
				reason: 'mixed_or_ambiguous',
			}),
			{
				attempts: 2,
				exhausted: false,
				lastQuestion: 'Please restate this more directly.',
			},
			'semantic-summary:test',
			semanticContextFlags()
		);

		assert.strictEqual(resolution.kind, 'block');
		if (resolution.kind === 'block') {
			assert.strictEqual(resolution.nextLoopState.exhausted, true);
			assert.strictEqual(resolution.blockKind, 'needs_disambiguation');
		}
	});

	test('semantic routing fixtures resolve deterministically without live model calls', () => {
		const fixtures = JSON.parse(
			fs.readFileSync(SEMANTIC_ROUTING_FIXTURE_PATH, 'utf8')
		) as SemanticRoutingFixture[];

		assert.ok(fixtures.length >= 14);
		for (const fixture of fixtures) {
			const decision = semanticDecision({
				route_type: fixture.expected_route_type,
				action_name: fixture.expected_action_name,
				normalized_text: fixture.input,
				paraphrase: fixture.notes,
				confidence: fixture.expected_route_type === 'block' ? 'low' : 'high',
				reason:
					fixture.expected_route_type === 'block'
						? 'mixed_or_ambiguous'
						: 'fixture_expected_route',
			});
			const resolution = resolveSemanticRouting(
				semanticFixtureModel(fixture.session_state),
				fixture.input,
				decision,
				undefined,
				`semantic-summary:${fixture.name}`,
				semanticContextFlags()
			);

			if (fixture.expected_outcome === 'block') {
				assert.strictEqual(
					resolution.kind,
					'block',
					`${fixture.name} should block`
				);
				continue;
			}

			assert.strictEqual(
				resolution.kind,
				'dispatch',
				`${fixture.name} should dispatch`
			);
			if (resolution.kind === 'dispatch') {
				assert.strictEqual(
					resolution.action.type,
					fixture.expected_outcome,
					fixture.name
				);
				assert.strictEqual(
					resolution.action.semantic_route_type,
					fixture.expected_route_type,
					fixture.name
				);
			}
		}
	});

	test('semantic routing fixtures are not runtime lookup data', () => {
		const runtimeSources = [
			fs.readFileSync(path.resolve(__dirname, '../../src/phase1Model.ts'), 'utf8'),
			fs.readFileSync(path.resolve(__dirname, '../../src/semanticSidecar.ts'), 'utf8'),
			readExecutionWindowSource(),
		].join('\n');

		assert.ok(!runtimeSources.includes('semantic-routing.json'));
	});

	test('app-server semantic runner sends read-only ephemeral semantic intake turns', async () => {
		let capturedRequest: Record<string, unknown> | undefined;
		const previousModel = process.env.CORGI_SEMANTIC_SIDECAR_MODEL;
		process.env.CORGI_SEMANTIC_SIDECAR_MODEL = 'gpt-test-semantic';
		try {
			const runner = new AppServerSemanticRunner({
				client: {
					startTurn: async (request) => {
						capturedRequest = request as unknown as Record<string, unknown>;
						return {
							threadId: 'thread-semantic',
							message: JSON.stringify(
								semanticDecision({
									route_type: 'governed_work_intent',
									normalized_text: 'analyze the repo',
								})
							),
						};
					},
					health: () => 'ready',
					shutdown: () => undefined,
				},
				fallbackRunner: semanticFallbackRunner(
					semanticDecision({ reason: 'should_not_fallback' })
				),
				cwd: '/tmp/corgi-semantic-test',
			});

			const decision = await runner.classify(semanticRunnerInput('analyze the repo'));

			assert.strictEqual(decision.route_type, 'governed_work_intent');
			assert.ok(capturedRequest);
			assert.strictEqual(capturedRequest?.runtimeKind, 'semantic_intake');
			assert.strictEqual(capturedRequest?.previewEnabled, false);
			assert.strictEqual(capturedRequest?.ephemeralThread, true);
			assert.strictEqual(capturedRequest?.model, 'gpt-test-semantic');
			assert.strictEqual(capturedRequest?.reasoning, 'low');
			assert.strictEqual(capturedRequest?.cwd, '/tmp/corgi-semantic-test');
		} finally {
			if (previousModel === undefined) {
				delete process.env.CORGI_SEMANTIC_SIDECAR_MODEL;
			} else {
				process.env.CORGI_SEMANTIC_SIDECAR_MODEL = previousModel;
			}
		}
	});

	test('app-server semantic runner extracts embedded JSON and fails closed on malformed output', async () => {
		const runner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => ({
					threadId: 'thread-semantic',
					message: `Here is the classification:\n${JSON.stringify(
						semanticDecision({
							route_type: 'governor_dialogue',
							normalized_text: 'what happened?',
						})
					)}`,
				}),
				health: () => 'ready',
				shutdown: () => undefined,
			},
		});

		const decision = await runner.classify(semanticRunnerInput('what happened?'));
		assert.strictEqual(decision.route_type, 'governor_dialogue');

		const malformedRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => ({
					threadId: 'thread-semantic',
					message: 'not json',
				}),
				health: () => 'ready',
				shutdown: () => undefined,
			},
			fallbackRunner: semanticFallbackRunner(
				semanticDecision({ reason: 'should_not_fallback' })
			),
		});
		const malformedDecision = await malformedRunner.classify(
			semanticRunnerInput('do something')
		);
		assert.strictEqual(malformedDecision.route_type, 'block');
		assert.strictEqual(malformedDecision.confidence, 'low');
		assert.strictEqual(malformedDecision.reason, 'semantic_sidecar_error');
	});

	test('app-server semantic runner falls back only for startup failures, not semantic timeouts', async () => {
		let fallbackCalls = 0;
		const fallbackRunner: SemanticRunner = {
			classify: async () => {
				fallbackCalls += 1;
				return semanticDecision({
					route_type: 'governed_work_intent',
					normalized_text: 'analyze the repo',
					reason: 'exec_fallback',
				});
			},
		};

		const startupFailureRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => {
					throw new Error('app-server initialize failed');
				},
				health: () => 'exited',
				shutdown: () => undefined,
			},
			fallbackRunner,
		});
		const fallbackDecision = await startupFailureRunner.classify(
			semanticRunnerInput('analyze the repo')
		);
		assert.strictEqual(fallbackDecision.reason, 'exec_fallback');
		assert.strictEqual(fallbackCalls, 1);

		const timeoutRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => {
					throw new Error('app-server Governor turn timed out');
				},
				health: () => 'ready',
				shutdown: () => undefined,
			},
			fallbackRunner,
		});
		const timeoutDecision = await timeoutRunner.classify(
			semanticRunnerInput('analyze the repo')
		);
		assert.strictEqual(timeoutDecision.route_type, 'block');
		assert.strictEqual(timeoutDecision.reason, 'semantic_sidecar_unavailable');
		assert.strictEqual(fallbackCalls, 1);

		const busyRunner = new AppServerSemanticRunner({
			client: {
				startTurn: async () => {
					throw new Error('app-server turn already in progress');
				},
				health: () => 'ready',
				shutdown: () => undefined,
			},
			fallbackRunner,
		});
		const busyDecision = await busyRunner.classify(
			semanticRunnerInput('analyze the repo')
		);
		assert.strictEqual(busyDecision.route_type, 'block');
		assert.strictEqual(busyDecision.reason, 'semantic_sidecar_unavailable');
		assert.strictEqual(fallbackCalls, 1);
	});

	test('semantic runner factory defaults to app-server and explicit exec preserves legacy runner', () => {
		assert.ok(createSemanticRunner({ runtime: 'app-server' }) instanceof AppServerSemanticRunner);
		assert.ok(createSemanticRunner({ runtime: 'exec' }) instanceof CodexSemanticRunner);
	});

	test('semantic sidecar uses the model runner for obvious governed work requests', async () => {
		let calls = 0;
		const sidecar = new SemanticSidecar({
			classify: async () => {
				calls += 1;
				return semanticDecision({
					route_type: 'governed_work_intent',
					normalized_text: 'develop the internet connect feature',
					paraphrase: 'Ask Corgi to develop the feature.',
				});
			},
		});

		const resolution = await sidecar.route(
			'develop the internet connect feature',
			createInitialModel('2026-04-10T10:00:00.000Z')
		);

		assert.strictEqual(calls, 1);
		assert.strictEqual(resolution.kind, 'dispatch');
		if (resolution.kind === 'dispatch') {
			assert.strictEqual(resolution.action.type, 'submit_prompt');
			assert.strictEqual(
				resolution.action.semantic_route_type,
				'governed_work_intent'
			);
		}
	});

	test('semantic sidecar treats runner failures as internal unavailability', async () => {
		const sidecar = new SemanticSidecar({
			classify: async () => {
				throw new Error('network exploded');
			},
		});

		const resolution = await sidecar.route(
			'develop the internet connect feature',
			createInitialModel('2026-04-10T10:00:00.000Z')
		);

		assert.strictEqual(resolution.kind, 'block');
		if (resolution.kind === 'block') {
			assert.strictEqual(resolution.blockKind, 'semantic_unavailable');
			assert.strictEqual(
				resolution.semantic.semantic_block_reason,
				'semantic_sidecar_unavailable'
			);
		}
	});
});
