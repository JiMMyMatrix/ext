#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const repoRoot = path.resolve(__dirname, '..');
const catalog = JSON.parse(
	fs.readFileSync(path.join(__dirname, 'corgi-test-prompts.json'), 'utf8')
);
const runId = `${Date.now()}-${process.pid}`;

function parseArgs(argv) {
	const args = {
		all: false,
		throughExecutor: false,
		keep: false,
		promptId: catalog.defaultPromptId,
	};
	for (let index = 0; index < argv.length; index += 1) {
		const value = argv[index];
		switch (value) {
			case '--all':
				args.all = true;
				break;
			case '--through-executor':
				args.throughExecutor = true;
				break;
			case '--keep':
				args.keep = true;
				break;
			case '--prompt':
				args.promptId = argv[index + 1];
				index += 1;
				break;
			case '--help':
				printUsage();
				process.exit(0);
				break;
			default:
				throw new Error(`Unknown argument: ${value}`);
		}
	}
	return args;
}

function printUsage() {
	process.stdout.write(
		[
			'Usage: node scripts/corgi-process-test.cjs [--prompt id | --all] [--through-executor] [--keep]',
			'',
			'Runs phase-1 command-only process tests without opening VS Code.',
		].join('\n') + '\n'
	);
}

function promptById(id) {
	return catalog.prompts.find((prompt) => prompt.id === id);
}

function executable(command) {
	const result = spawnSync('bash', ['-lc', `command -v ${command}`], {
		encoding: 'utf8',
	});
	return result.status === 0 ? result.stdout.trim() : undefined;
}

function approvedPython() {
	if (process.env.ORCHESTRATION_APPROVED_PYTHON) {
		return process.env.ORCHESTRATION_APPROVED_PYTHON;
	}
	if (process.env.CORGI_PYTHON) {
		return process.env.CORGI_PYTHON;
	}
	if (fs.existsSync('/opt/homebrew/bin/python3')) {
		return '/opt/homebrew/bin/python3';
	}
	return executable('python3') ?? 'python3';
}

function commandPython() {
	return process.env.CORGI_PYTHON ?? approvedPython();
}

function assertCondition(condition, message) {
	if (!condition) {
		throw new Error(message);
	}
}

function runJson(args, env) {
	const result = spawnSync(
		commandPython(),
		[path.join(repoRoot, 'orchestration/scripts/orchestrate.py'), 'session', ...args],
		{
			cwd: repoRoot,
			env,
			encoding: 'utf8',
			maxBuffer: 1024 * 1024 * 12,
		}
	);
	if (result.status !== 0) {
		throw new Error(
			`orchestrate.py session ${args[0]} failed:\n${result.stderr || result.stdout}`
		);
	}
	try {
		return JSON.parse(result.stdout);
	} catch (error) {
		throw new Error(`Invalid JSON from ${args[0]}:\n${result.stdout}`);
	}
}

function hasError(model) {
	return (model.feed ?? []).some((item) => item.type === 'error');
}

function latestGovernorEvent(model) {
	return [...(model.feed ?? [])]
		.reverse()
		.find((item) => item.type === 'actor_event' && item.source_actor === 'governor');
}

function requestId(prompt, step) {
	return `process-test:${prompt.id}:${step}`;
}

function syntheticGovernorBody(prompt) {
	return [
		`Objective: ${prompt.prompt}`,
		'Proposed steps: validate the accepted intake, inspect the relevant runtime seams, and keep execution bounded.',
		'Likely areas: src/, orchestration/, contracts, runtime config, and generated workflow artifacts.',
		'Risks or unknowns: live model interpretation may differ from this command-only process test.',
		'Execution readiness: ready for the next authorized command-bound step.',
	].join('\n\n');
}

function runDialogueFlow(prompt, env) {
	let model = runJson(
		[
			'submit-prompt',
			'--text',
			prompt.prompt,
			'--request-id',
			requestId(prompt, 'submit'),
			'--semantic-mode',
			'sidecar-first',
			'--semantic-route-type',
			'governor_dialogue',
			'--semantic-confidence',
			'high',
			'--turn-type',
			'governor_dialogue',
			'--normalized-text',
			prompt.prompt,
			'--governor-runtime',
			'external',
		],
		env
	);
	assertCondition(!hasError(model), `${prompt.id}: dialogue submit produced an error`);

	const permission = model.snapshot.pendingPermissionRequest;
	if (permission) {
		const response = runJson(
			[
				'set-permission-scope',
				'--permission-scope',
				'observe',
				'--request-id',
				requestId(prompt, 'observe'),
				'--session-ref',
				model.snapshot.sessionRef,
				'--context-ref',
				permission.contextRef,
				'--governor-runtime',
				'external',
			],
			env
		);
		assertCondition(
			response.kind === 'governor_runtime_request',
			`${prompt.id}: observe permission did not request Governor runtime`
		);
		model = runJson(
			[
				'complete-governor-turn',
				'--runtime-request-id',
				response.request.runtimeRequestId,
				'--body',
				`Current progress: ${prompt.prompt}`,
				'--runtime-source',
				'process-test',
			],
			env
		);
	}

	assertCondition(
		Boolean(latestGovernorEvent(model)),
		`${prompt.id}: Governor dialogue did not produce Governor output`
	);
	assertCondition(
		!model.acceptedIntakeSummary,
		`${prompt.id}: read-only dialogue created accepted intake`
	);
	return model;
}

function answerClarificationIfNeeded(prompt, model, env) {
	if (!model.activeClarification) {
		return model;
	}
	const answer =
		model.activeClarification.options?.[0]?.answer ??
		'Focus on architecture, structure, and subsystem boundaries.';
	return runJson(
		[
			'answer-clarification',
			'--text',
			answer,
			'--request-id',
			requestId(prompt, 'clarification'),
			'--session-ref',
			model.snapshot.sessionRef,
			'--context-ref',
			model.activeClarification.contextRef,
			'--semantic-route-type',
			'clarification_reply',
			'--semantic-confidence',
			'high',
			'--turn-type',
			'clarification_reply',
			'--normalized-text',
			answer,
			'--governor-runtime',
			'external',
		],
		env
	);
}

function completePendingGovernorPlan(prompt, response, env) {
	assertCondition(
		response.kind === 'governor_runtime_request',
		`${prompt.id}: plan permission did not request Governor runtime`
	);
	return runJson(
		[
			'complete-governor-turn',
			'--runtime-request-id',
			response.request.runtimeRequestId,
			'--body',
			syntheticGovernorBody(prompt),
			'--runtime-source',
			'process-test',
		],
		env
	);
}

function runGovernedWorkFlow(prompt, env, throughExecutor) {
	let model = runJson(
		[
			'submit-prompt',
			'--text',
			prompt.prompt,
			'--request-id',
			requestId(prompt, 'submit'),
			'--semantic-mode',
			'sidecar-first',
			'--semantic-route-type',
			'governed_work_intent',
			'--semantic-confidence',
			'high',
			'--turn-type',
			'governed_work_intent',
			'--normalized-text',
			prompt.prompt,
			'--governor-runtime',
			'external',
		],
		env
	);
	assertCondition(!hasError(model), `${prompt.id}: submit produced an error`);

	model = answerClarificationIfNeeded(prompt, model, env);
	assertCondition(!hasError(model), `${prompt.id}: clarification produced an error`);

	const permission = model.snapshot.pendingPermissionRequest;
	assertCondition(permission, `${prompt.id}: governed work did not request permission`);
	const permissionResponse = runJson(
		[
			'set-permission-scope',
			'--permission-scope',
			'plan',
			'--request-id',
			requestId(prompt, 'plan-permission'),
			'--session-ref',
			model.snapshot.sessionRef,
			'--context-ref',
			permission.contextRef,
			'--governor-runtime',
			'external',
		],
		env
	);
	model = completePendingGovernorPlan(prompt, permissionResponse, env);

	assertCondition(model.planReadyRequest, `${prompt.id}: plan-ready request missing`);
	assertCondition(
		model.snapshot.currentStage === 'plan_ready',
		`${prompt.id}: expected plan_ready, got ${model.snapshot.currentStage}`
	);
	assertCondition(
		Boolean(latestGovernorEvent(model)),
		`${prompt.id}: plan did not commit Governor output`
	);

	if (!throughExecutor) {
		return model;
	}

	model = runJson(
		[
			'execute-plan',
			'--request-id',
			requestId(prompt, 'execute'),
			'--session-ref',
			model.snapshot.sessionRef,
			'--context-ref',
			model.planReadyRequest.contextRef,
			'--auto-consume-executor',
		],
		env
	);
	assertCondition(
		!['executor_blocked', 'reviewer_blocked'].includes(model.snapshot.currentStage),
		`${prompt.id}: executor/reviewer blocked at ${model.snapshot.currentStage}`
	);
	assertCondition(
		model.snapshot.currentStage === 'governor_decision_recorded',
		`${prompt.id}: expected governor_decision_recorded after auto execution, got ${model.snapshot.currentStage}`
	);
	assertCondition(
		(model.snapshot.recentArtifacts ?? []).some((artifact) =>
			String(artifact.path ?? '').endsWith('/request.json')
		),
		`${prompt.id}: dispatch request artifact missing`
	);
	return model;
}

function seedPendingPlanPermission(prompt, env) {
	let model = runJson(
		[
			'submit-prompt',
			'--text',
			'analyze the repo',
			'--request-id',
			requestId(prompt, 'seed-submit'),
			'--semantic-mode',
			'sidecar-first',
			'--semantic-route-type',
			'governed_work_intent',
			'--semantic-confidence',
			'high',
			'--turn-type',
			'governed_work_intent',
			'--normalized-text',
			'analyze the repo',
			'--governor-runtime',
			'external',
		],
		env
	);
	model = answerClarificationIfNeeded(prompt, model, env);
	assertCondition(
		model.snapshot.pendingPermissionRequest,
		`${prompt.id}: seed flow did not create pending permission`
	);
	assertCondition(
		model.snapshot.pendingPermissionRequest.recommendedScope === 'plan',
		`${prompt.id}: seed permission was not Plan`
	);
	return model;
}

function runPermissionFollowupFlow(prompt, env) {
	const seededModel = seedPendingPlanPermission(prompt, env);
	const pendingBefore = seededModel.snapshot.pendingPermissionRequest;
	const model = runJson(
		[
			'submit-prompt',
			'--text',
			prompt.prompt,
			'--request-id',
			requestId(prompt, 'followup'),
			'--session-ref',
			seededModel.snapshot.sessionRef,
			'--semantic-mode',
			'sidecar-first',
			'--semantic-route-type',
			'block',
			'--semantic-confidence',
			'high',
			'--semantic-block-reason',
			'ambiguous_permission_followup',
			'--turn-type',
			'block',
			'--normalized-text',
			prompt.prompt,
		],
		env
	);
	assertCondition(
		hasError(model),
		`${prompt.id}: ambiguous permission follow-up did not fail closed`
	);
	assertCondition(
		model.snapshot.permissionScope === 'unset',
		`${prompt.id}: ambiguous follow-up changed permission scope`
	);
	assertCondition(
		model.snapshot.pendingPermissionRequest?.contextRef === pendingBefore.contextRef,
		`${prompt.id}: ambiguous follow-up replaced the pending permission request`
	);
	assertCondition(
		!model.acceptedIntakeSummary,
		`${prompt.id}: ambiguous follow-up accepted intake`
	);
	return model;
}

function runConflictFlow(prompt, env) {
	const model = runJson(
		[
			'submit-prompt',
			'--text',
			prompt.prompt,
			'--request-id',
			requestId(prompt, 'submit'),
			'--semantic-mode',
			'sidecar-first',
			'--semantic-route-type',
			'block',
			'--semantic-confidence',
			'high',
			'--semantic-block-reason',
			'mixed_intent',
			'--turn-type',
			'block',
			'--normalized-text',
			prompt.prompt,
		],
		env
	);
	assertCondition(hasError(model), `${prompt.id}: conflict prompt did not fail closed`);
	assertCondition(
		!model.acceptedIntakeSummary,
		`${prompt.id}: conflict prompt created accepted intake`
	);
	return model;
}

function supportedPrompt(prompt) {
	return [
		'governed_work',
		'implementation_intent',
		'review_intent',
		'question_shaped_work',
		'governor_dialogue',
		'conflict',
		'stateful_followup',
	].includes(prompt.category);
}

function runPrompt(prompt, options) {
	const safeName = prompt.id.replace(/[^a-z0-9-]+/gi, '-');
	const runName = options.all ? safeName : `${safeName}-${runId}`;
	const agentRoot = path.join(
		repoRoot,
		'.agent',
		'command-test',
		runName,
		'runtime-agent'
	);
	fs.rmSync(agentRoot, { recursive: true, force: true });
	fs.mkdirSync(agentRoot, { recursive: true });

	const env = {
		...process.env,
		ORCHESTRATION_AGENT_ROOT: agentRoot,
		ORCHESTRATION_APPROVED_PYTHON: approvedPython(),
	};

	let model;
	if (prompt.category === 'governor_dialogue') {
		model = runDialogueFlow(prompt, env);
	} else if (prompt.category === 'stateful_followup') {
		model = runPermissionFollowupFlow(prompt, env);
	} else if (prompt.category === 'conflict') {
		model = runConflictFlow(prompt, env);
	} else {
		model = runGovernedWorkFlow(prompt, env, options.throughExecutor);
	}

	if (!options.keep && !options.all) {
		// Preserve all-prompt runs for postmortem comparison, but keep one-off
		// command tests tidy unless the caller asks to keep artifacts.
		fs.rmSync(path.join(repoRoot, '.agent', 'command-test', runName), {
			recursive: true,
			force: true,
		});
	}

	return {
		id: prompt.id,
		category: prompt.category,
		stage: model.snapshot.currentStage,
		permissionScope: model.snapshot.permissionScope,
		agentRoot,
	};
}

function main() {
	const options = parseArgs(process.argv.slice(2));
	const prompts = options.all
		? catalog.prompts.filter(supportedPrompt)
		: [promptById(options.promptId)];
	if (prompts.some((prompt) => !prompt)) {
		throw new Error(`Unknown prompt id: ${options.promptId}`);
	}

	const results = prompts.map((prompt) => runPrompt(prompt, options));
	for (const result of results) {
		process.stdout.write(
			`[process-test] ${result.id}: ${result.stage} (${result.permissionScope})\n`
		);
	}
	process.stdout.write(`Validated ${results.length} command-only process flow(s).\n`);
}

try {
	main();
} catch (error) {
	process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
	process.exit(1);
}
