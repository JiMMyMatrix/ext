#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { seedBuggyPetDiaryApp, seedFilterPetDiaryApp } = require('./pet-diary-fixture.cjs');

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
		module: undefined,
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
			case '--module':
				args.module = argv[index + 1];
				index += 1;
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
			'Usage: node scripts/corgi-process-test.cjs [--prompt id | --all | --module name] [--through-executor] [--keep]',
			'',
			'Runs phase-1 command-only process tests without opening VS Code.',
			'',
			'Modules: executor, reviewer, review-replan, scratch-static-app, scratch-bugfix-existing-app, scratch-feature-existing-app, completion, all',
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

function runCommand(args, env) {
	const result = spawnSync(
		commandPython(),
		[path.join(repoRoot, 'orchestration/scripts/orchestrate.py'), ...args],
		{
			cwd: repoRoot,
			env,
			encoding: 'utf8',
			maxBuffer: 1024 * 1024 * 12,
		}
	);
	if (result.status !== 0) {
		throw new Error(
			`orchestrate.py ${args.join(' ')} failed:\n${result.stderr || result.stdout}`
		);
	}
	return result.stdout.trim();
}

function readJson(pathValue) {
	return JSON.parse(fs.readFileSync(pathValue, 'utf8'));
}

function commandSpecText(commandSpec) {
	if (typeof commandSpec === 'string') {
		return commandSpec;
	}
	if (Array.isArray(commandSpec?.argv)) {
		return commandSpec.argv.join(' ');
	}
	if (typeof commandSpec?.argv === 'string') {
		return commandSpec.argv;
	}
	return '';
}

function repoPath(relPath) {
	return path.join(repoRoot, relPath);
}

function collectFiles(root, predicate) {
	if (!fs.existsSync(root)) {
		return [];
	}
	const files = [];
	for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
		const entryPath = path.join(root, entry.name);
		if (entry.isDirectory()) {
			files.push(...collectFiles(entryPath, predicate));
		} else if (!predicate || predicate(entryPath)) {
			files.push(entryPath);
		}
	}
	return files;
}

function recentArtifactPaths(model) {
	return (model.snapshot.recentArtifacts ?? [])
		.map((artifact) => artifact.path)
		.filter((artifactPath) => typeof artifactPath === 'string' && artifactPath.length > 0);
}

function dispatchRequestPaths(agentRoot) {
	return collectFiles(
		path.join(agentRoot, 'dispatches'),
		(filePath) => filePath.endsWith(`${path.sep}request.json`)
	).sort();
}

function latestFeedItem(model, title) {
	return [...(model.feed ?? [])].reverse().find((item) => item.title === title);
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

function createTestEnv(runName, extraEnv = {}) {
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
		...extraEnv,
	};
	return {
		agentRoot,
		runDir: path.join(repoRoot, '.agent', 'command-test', runName),
		env,
	};
}

function createScratchTestEnv(runName, promptPreset = 'pet-life-diary-static') {
	const runDir = path.join(repoRoot, '.agent', 'command-test', runName);
	const scratchRoot = path.join(runDir, 'scratch-workspace');
	const agentRoot = path.join(scratchRoot, '.agent');
	fs.rmSync(runDir, { recursive: true, force: true });
	fs.mkdirSync(scratchRoot, { recursive: true });
	spawnSync('git', ['init', '-b', 'main'], {
		cwd: scratchRoot,
		stdio: 'ignore',
	});
	if (!fs.existsSync(path.join(scratchRoot, '.git'))) {
		spawnSync('git', ['init'], {
			cwd: scratchRoot,
			stdio: 'ignore',
		});
	}
	const gitExclude = path.join(scratchRoot, '.git', 'info', 'exclude');
	if (fs.existsSync(gitExclude)) {
		fs.appendFileSync(gitExclude, '\n.agent/\n');
	}
	fs.mkdirSync(agentRoot, { recursive: true });

	return {
		agentRoot,
		runDir,
		scratchRoot,
		env: {
			...process.env,
			ORCHESTRATION_REPO_ROOT: scratchRoot,
			ORCHESTRATION_SOURCE_ROOT: repoRoot,
			ORCHESTRATION_AGENT_ROOT: agentRoot,
			ORCHESTRATION_TARGET_WORKSPACE_MODE: 'scratch',
			ORCHESTRATION_TEST_PROMPT_PRESET: promptPreset,
			ORCHESTRATION_APPROVED_PYTHON: approvedPython(),
		},
	};
}

function runPrompt(prompt, options) {
	const safeName = prompt.id.replace(/[^a-z0-9-]+/gi, '-');
	const runName = options.all ? safeName : `${safeName}-${runId}`;
	const { agentRoot, runDir, env } = createTestEnv(runName);

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
		fs.rmSync(runDir, { recursive: true, force: true });
	}

	return {
		id: prompt.id,
		category: prompt.category,
		stage: model.snapshot.currentStage,
		permissionScope: model.snapshot.permissionScope,
		agentRoot,
	};
}

function assertExecutorArtifacts(moduleName, model, agentRoot, options = {}) {
	const expectFeed = options.expectFeed !== false;
	const requestPaths = dispatchRequestPaths(agentRoot);
	assertCondition(requestPaths.length > 0, `${moduleName}: dispatch request artifact missing`);
	const requestPath = requestPaths[0];
	const dispatchDir = path.dirname(requestPath);
	const request = readJson(requestPath);
	const state = readJson(path.join(dispatchDir, 'state.json'));
	const result = readJson(path.join(dispatchDir, 'result.json'));
	assertCondition(request.review_required === true, `${moduleName}: dispatch is not reviewer-gated`);
	assertCondition(request.execution_mode === 'command_chain', `${moduleName}: unexpected execution mode`);
	assertCondition(request.executor_run?.run_ref, `${moduleName}: executor run ref missing`);
	assertCondition(
		state.status === 'completed' || state.status === 'validated',
		`${moduleName}: executor state did not complete`
	);
	assertCondition(result.status === 'completed', `${moduleName}: executor result did not complete`);
	assertCondition(result.scope_respected === true, `${moduleName}: executor scope was not respected`);
	const reportPath = path.join(agentRoot, 'runs', request.executor_run.run_ref, 'report.json');
	const readoutPath = path.join(agentRoot, 'runs', request.executor_run.run_ref, 'executor_readout.md');
	assertCondition(fs.existsSync(reportPath), `${moduleName}: executor report missing`);
	assertCondition(fs.existsSync(readoutPath), `${moduleName}: executor readout missing`);
	assertCondition(
		fs.readFileSync(readoutPath, 'utf8').includes('## Architecture Boundaries'),
		`${moduleName}: executor readout missing architecture section`
	);
	if (expectFeed) {
		assertCondition(
			Boolean(latestFeedItem(model, 'Executor completed')),
			`${moduleName}: model feed missing Executor completion`
		);
		assertCondition(
			recentArtifactPaths(model).some((artifactPath) => artifactPath.endsWith('/executor_readout.md')),
			`${moduleName}: recent artifacts missing executor readout`
		);
	}
	return { request, dispatchDir, requestPath };
}

function assertReviewerArtifacts(moduleName, model, dispatchInfo, options = {}) {
	const expectFeed = options.expectFeed !== false;
	const rootForRefs = options.repoRoot ?? repoRoot;
	const reviewRef = dispatchInfo.request.review_artifact_path;
	assertCondition(typeof reviewRef === 'string' && reviewRef.length > 0, `${moduleName}: review ref missing`);
	const reviewPath = path.join(rootForRefs, reviewRef);
	assertCondition(fs.existsSync(reviewPath), `${moduleName}: reviewer artifact missing`);
	const review = readJson(reviewPath);
	assertCondition(review.dispatch_ref === dispatchInfo.request.dispatch_ref, `${moduleName}: review dispatch mismatch`);
	assertCondition(
		['pass', 'request_changes', 'inconclusive'].includes(review.verdict),
		`${moduleName}: unexpected reviewer verdict`
	);
	if (expectFeed) {
		assertCondition(
			Boolean(latestFeedItem(model, 'Reviewer completed')),
			`${moduleName}: model feed missing Reviewer completion`
		);
		assertCondition(
			recentArtifactPaths(model).includes(reviewRef),
			`${moduleName}: recent artifacts missing reviewer artifact`
		);
	}
	return review;
}

function assertGovernorDecision(moduleName, model, dispatchInfo, options = {}) {
	const expectFeed = options.expectFeed !== false;
	const decisionPath = path.join(dispatchInfo.dispatchDir, 'governor_decision.json');
	assertCondition(fs.existsSync(decisionPath), `${moduleName}: governor decision missing`);
	const decision = readJson(decisionPath);
	assertCondition(
		['accept', 'reject', 'needs_review', 'needs_verification'].includes(decision.decision),
		`${moduleName}: unexpected governor decision`
	);
	if (expectFeed) {
		assertCondition(
			Boolean(latestFeedItem(model, 'Governor decision recorded')),
			`${moduleName}: model feed missing Governor decision`
		);
	}
	return decision;
}

function preparePlanForExecution(prompt, env) {
	const model = runGovernedWorkFlow(prompt, env, false);
	assertCondition(model.planReadyRequest, 'module: plan-ready request missing');
	return model;
}

function queuePlanDispatch(prompt, env, planModel, requestSuffix) {
	const model = runJson(
		[
			'execute-plan',
			'--request-id',
			requestId(prompt, requestSuffix),
			'--session-ref',
			planModel.snapshot.sessionRef,
			'--context-ref',
			planModel.planReadyRequest.contextRef,
		],
		env
	);
	assertCondition(
		model.snapshot.currentStage === 'dispatch_queued',
		`module: expected dispatch_queued, got ${model.snapshot.currentStage}`
	);
	return model;
}

function latestDispatchInfo(agentRoot) {
	const requestPaths = dispatchRequestPaths(agentRoot);
	assertCondition(requestPaths.length > 0, 'module: dispatch request artifact missing');
	const requestPath = requestPaths[requestPaths.length - 1];
	return {
		request: readJson(requestPath),
		dispatchDir: path.dirname(requestPath),
		requestPath,
	};
}

function consumeExecutor(dispatchInfo, env, root = repoRoot) {
	runCommand(
		['dispatch', 'consume-executor', '--dispatch-dir', dispatchInfo.dispatchDir, '--root', root],
		env
	);
}

function consumeReviewer(dispatchInfo, env) {
	runCommand(['dispatch', 'consume-reviewer', '--dispatch-dir', dispatchInfo.dispatchDir], env);
}

function finalizeDispatch(dispatchInfo, env) {
	runCommand(['dispatch', 'finalize', '--dispatch-dir', dispatchInfo.dispatchDir], env);
}

function runReviewReplanHelper(agentRoot, env) {
	const result = spawnSync(
		commandPython(),
		[
			path.join(repoRoot, 'scripts/corgi-review-replan-process-test.py'),
			'--repo-root',
			repoRoot,
			'--agent-root',
			agentRoot,
		],
		{
			cwd: repoRoot,
			env,
			encoding: 'utf8',
			maxBuffer: 1024 * 1024 * 12,
		}
	);
	if (result.status !== 0) {
		throw new Error(`review-replan helper failed:\n${result.stderr || result.stdout}`);
	}
	try {
		return JSON.parse(result.stdout);
	} catch (error) {
		throw new Error(`Invalid JSON from review-replan helper:\n${result.stdout}`);
	}
}

function runExecutorModule(options) {
	const prompt = promptById('analyze-repo');
	const runName = `module-executor-${runId}`;
	const { agentRoot, runDir, env } = createTestEnv(runName);
	const planModel = preparePlanForExecution(prompt, env);
	const queued = queuePlanDispatch(prompt, env, planModel, 'executor-queue');
	let dispatchInfo = latestDispatchInfo(agentRoot);
	consumeExecutor(dispatchInfo, env);
	dispatchInfo = latestDispatchInfo(agentRoot);
	assertExecutorArtifacts('executor', queued, agentRoot, { expectFeed: false });
	assertCondition(
		!fs.existsSync(path.join(dispatchInfo.dispatchDir, 'governor_decision.json')),
		'executor: Governor decision should not exist before reviewer/finalizer run'
	);
	if (!options.keep) {
		fs.rmSync(runDir, { recursive: true, force: true });
	}
	return {
		id: 'module:executor',
		stage: 'executor_completed',
		permissionScope: queued.snapshot.permissionScope,
		dispatchRef: dispatchInfo.request.dispatch_ref,
	};
}

function runReviewerModule(options) {
	const prompt = promptById('analyze-repo');
	const runName = `module-reviewer-${runId}`;
	const { agentRoot, runDir, env } = createTestEnv(runName);
	const planModel = preparePlanForExecution(prompt, env);
	const queued = queuePlanDispatch(prompt, env, planModel, 'reviewer-queue');
	let dispatchInfo = latestDispatchInfo(agentRoot);
	consumeExecutor(dispatchInfo, env);
	dispatchInfo = latestDispatchInfo(agentRoot);
	assertExecutorArtifacts('reviewer', queued, agentRoot, { expectFeed: false });
	consumeReviewer(dispatchInfo, env);
	dispatchInfo = latestDispatchInfo(agentRoot);
	const review = assertReviewerArtifacts('reviewer', queued, dispatchInfo, { expectFeed: false });
	finalizeDispatch(dispatchInfo, env);
	const decision = assertGovernorDecision('reviewer', queued, dispatchInfo, { expectFeed: false });
	assertCondition(review.verdict === 'pass', `reviewer: expected pass verdict, got ${review.verdict}`);
	assertCondition(decision.decision === 'accept', `reviewer: expected accept decision, got ${decision.decision}`);
	if (!options.keep) {
		fs.rmSync(runDir, { recursive: true, force: true });
	}
	return {
		id: 'module:reviewer',
		stage: 'governor_decision_recorded',
		permissionScope: queued.snapshot.permissionScope,
		dispatchRef: dispatchInfo.request.dispatch_ref,
	};
}

function runReviewReplanModule(options) {
	const runName = `module-review-replan-${runId}`;
	const { agentRoot, runDir, env } = createTestEnv(runName);
	const result = runReviewReplanHelper(agentRoot, env);
	if (!options.keep) {
		fs.rmSync(runDir, { recursive: true, force: true });
	}
	return {
		id: result.id,
		stage: result.stage,
		permissionScope: result.permissionScope,
		dispatchRef: result.dispatchRef,
	};
}

function runScratchStaticAppModule(options) {
	const prompt = promptById('pet-life-diary-static');
	assertCondition(prompt, 'scratch-static-app: prompt preset missing');
	const runName = `module-scratch-static-app-${runId}`;
	const { agentRoot, runDir, scratchRoot, env } = createScratchTestEnv(runName);
	const model = runGovernedWorkFlow(prompt, env, true);
	const dispatchInfo = latestDispatchInfo(agentRoot);
	const request = readJson(dispatchInfo.requestPath);
	const state = readJson(path.join(dispatchInfo.dispatchDir, 'state.json'));
	const result = readJson(path.join(dispatchInfo.dispatchDir, 'result.json'));
	const outputSignatures = result.output_signatures;
	const expectedFiles = [
		'README.md',
		'index.html',
		'src/app.js',
		'src/styles.css',
		'data/sample-pets.json',
	];
	for (const fileRef of expectedFiles) {
		const filePath = path.join(scratchRoot, fileRef);
		assertCondition(fs.existsSync(filePath), `scratch-static-app: missing ${fileRef}`);
		assertCondition(
			request.required_outputs.includes(fileRef),
			`scratch-static-app: ${fileRef} missing from required_outputs`
		);
		assertCondition(
			result.written_or_updated.includes(fileRef),
			`scratch-static-app: ${fileRef} missing from executor result`
		);
		assertCondition(
			outputSignatures?.required_outputs?.[fileRef]?.classification === 'created' ||
				outputSignatures?.required_outputs?.[fileRef]?.classification === 'mutated',
			`scratch-static-app: ${fileRef} missing created/mutated authorship evidence`
		);
	}
	assertCondition(
		request.authorship_evidence?.required === true,
		'scratch-static-app: authorship evidence was not required'
	);
	assertCondition(
		outputSignatures?.verified === true,
		'scratch-static-app: authorship evidence was not verified'
	);
	assertCondition(
		Array.isArray(outputSignatures?.blockers) && outputSignatures.blockers.length === 0,
		'scratch-static-app: authorship evidence reported blockers'
	);
	assertCondition(
		fs.readFileSync(path.join(scratchRoot, 'index.html'), 'utf8').includes('Pet Life Diary'),
		'scratch-static-app: index.html missing app title'
	);
	const samplePets = JSON.parse(
		fs.readFileSync(path.join(scratchRoot, 'data/sample-pets.json'), 'utf8')
	);
	assertCondition(
		Array.isArray(samplePets) && samplePets.length >= 3,
		'scratch-static-app: sample data invalid'
	);
	assertCondition(
		request.execution_mode === 'command_chain',
		'scratch-static-app: unexpected execution mode'
	);
	assertCondition(
		request.execution_payload.notes.includes('scratch_static_app_creation'),
		'scratch-static-app: missing scratch execution note'
	);
	assertCondition(
		state.status === 'completed' || state.status === 'validated',
		'scratch-static-app: executor state did not complete'
	);
	assertReviewerArtifacts('scratch-static-app', model, dispatchInfo, {
		expectFeed: false,
		repoRoot: scratchRoot,
	});
	assertGovernorDecision('scratch-static-app', model, dispatchInfo, { expectFeed: false });
	for (const devRef of ['index.html', path.join('data', 'sample-pets.json')]) {
		assertCondition(
			!fs.existsSync(path.join(repoRoot, devRef)),
			`scratch-static-app: wrote ${devRef} to Corgi source repo`
		);
	}
	if (!options.keep) {
		fs.rmSync(runDir, { recursive: true, force: true });
	}
	return {
		id: 'module:scratch-static-app',
		stage: model.snapshot.currentStage,
		permissionScope: model.snapshot.permissionScope,
		dispatchRef: dispatchInfo.request.dispatch_ref,
	};
}

function runScratchBugfixExistingAppModule(options) {
	const prompt = promptById('pet-life-diary-bugfix');
	assertCondition(prompt, 'scratch-bugfix-existing-app: prompt preset missing');
	const runName = `module-scratch-bugfix-existing-app-${runId}`;
	const { agentRoot, runDir, scratchRoot, env } = createScratchTestEnv(
		runName,
		'pet-life-diary-bugfix'
	);
	seedBuggyPetDiaryApp(scratchRoot);
	const baselineApp = fs.readFileSync(path.join(scratchRoot, 'src/app.js'), 'utf8');
	assertCondition(
		!baselineApp.includes('diaryEntries.push'),
		'scratch-bugfix-existing-app: seeded app unexpectedly starts fixed'
	);
	const model = runGovernedWorkFlow(prompt, env, true);
	const dispatchInfo = latestDispatchInfo(agentRoot);
	const request = readJson(dispatchInfo.requestPath);
	const state = readJson(path.join(dispatchInfo.dispatchDir, 'state.json'));
	const result = readJson(path.join(dispatchInfo.dispatchDir, 'result.json'));
	const outputSignatures = result.output_signatures;
	const appPath = path.join(scratchRoot, 'src/app.js');
	const validationPath = path.join(
		scratchRoot,
		'.agent',
		'validations',
		dispatchInfo.request.dispatch_ref,
		'pet_diary_entry_fix.json'
	);
	const patchPath = path.join(
		scratchRoot,
		'.agent',
		'patches',
		dispatchInfo.request.dispatch_ref,
		'src-app-js.patch'
	);
	const patchSpecPath = path.join(
		scratchRoot,
		'.agent',
		'patch_specs',
		dispatchInfo.request.dispatch_ref,
		'pet_diary_entry_fix.json'
	);
	const fixedApp = fs.readFileSync(appPath, 'utf8');
	assertCondition(
		fixedApp.includes('diaryEntries.push'),
		'scratch-bugfix-existing-app: src/app.js did not append submitted diary entries'
	);
	assertCondition(
		fixedApp.includes('renderEntries();'),
		'scratch-bugfix-existing-app: src/app.js did not re-render entries'
	);
	assertCondition(
		request.required_outputs.length === 1 && request.required_outputs.includes('src/app.js'),
		'scratch-bugfix-existing-app: expected src/app.js as the only required project output'
	);
	assertCondition(
		result.written_or_updated.includes('src/app.js'),
		'scratch-bugfix-existing-app: src/app.js missing from executor result'
	);
	assertCondition(
		outputSignatures?.required_outputs?.['src/app.js']?.classification === 'mutated',
		'scratch-bugfix-existing-app: src/app.js missing mutated authorship evidence'
	);
	assertCondition(
		outputSignatures?.verified === true,
		'scratch-bugfix-existing-app: authorship evidence was not verified'
	);
	assertCondition(
		Array.isArray(outputSignatures?.blockers) && outputSignatures.blockers.length === 0,
		'scratch-bugfix-existing-app: authorship evidence reported blockers'
	);
	assertCondition(
		fs.existsSync(validationPath),
		'scratch-bugfix-existing-app: validation report was not written'
	);
	assertCondition(
		fs.existsSync(patchPath),
		'scratch-bugfix-existing-app: patch artifact was not written'
	);
	assertCondition(
		fs.existsSync(patchSpecPath),
		'scratch-bugfix-existing-app: patch spec artifact was not written'
	);
	const patchSpec = readJson(patchSpecPath);
	assertCondition(
		patchSpec.schema_version === 'corgi.patch-spec.v1' &&
			patchSpec.proposed_by === 'executor' &&
			patchSpec.operations?.[0]?.path === 'src/app.js' &&
			typeof patchSpec.operations?.[0]?.before_sha256 === 'string' &&
			Number.isInteger(patchSpec.operations?.[0]?.before_size),
		'scratch-bugfix-existing-app: patch spec does not target src/app.js'
	);
	assertCondition(
		patchSpec.operations[0].patch_artifact.endsWith('src-app-js.patch'),
		'scratch-bugfix-existing-app: patch spec missing patch artifact target'
	);
	const patchSource = fs.readFileSync(patchPath, 'utf8');
	assertCondition(
		patchSource.includes('--- a/src/app.js') && patchSource.includes('+++ b/src/app.js'),
		'scratch-bugfix-existing-app: patch artifact does not target src/app.js'
	);
	assertCondition(
		patchSource.includes('+\tdiaryEntries.push({'),
		'scratch-bugfix-existing-app: patch artifact does not show diary entry append'
	);
	assertCondition(
		request.execution_payload.evidence.some((ref) => ref.endsWith('src-app-js.patch')),
		'scratch-bugfix-existing-app: patch artifact missing from dispatch evidence'
	);
	assertCondition(
		request.execution_payload.evidence.some(
			(ref) => ref.includes('.agent/patch_specs/') && ref.endsWith('pet_diary_entry_fix.json')
		),
		'scratch-bugfix-existing-app: patch spec missing from dispatch evidence'
	);
	assertCondition(
		request.execution_payload.commands.some((command) =>
			commandSpecText(command).includes('executor_propose_patch_spec.py')
		),
		'scratch-bugfix-existing-app: dispatch did not use executor patch proposal command'
	);
	assertCondition(
		request.execution_payload.commands.some((command) =>
			commandSpecText(command).includes('executor_apply_patch_spec.py')
		),
		'scratch-bugfix-existing-app: dispatch did not use generic patch spec executor'
	);
	assertCondition(
		!request.execution_payload.commands.some((command) =>
			commandSpecText(command).includes('executor_fix_pet_diary_entry.py')
		),
		'scratch-bugfix-existing-app: dispatch still uses bug-specific executor helper'
	);
	const validation = readJson(validationPath);
	assertCondition(
		validation.status === 'pass',
		`scratch-bugfix-existing-app: validation did not pass (${validation.failures?.join(', ')})`
	);
	assertCondition(
		request.execution_mode === 'command_chain',
		'scratch-bugfix-existing-app: unexpected execution mode'
	);
	assertCondition(
		request.execution_payload.notes.includes('scratch_pet_diary_bugfix'),
		'scratch-bugfix-existing-app: missing scratch bugfix execution note'
	);
	assertCondition(
		state.status === 'completed' || state.status === 'validated',
		'scratch-bugfix-existing-app: executor state did not complete'
	);
	assertReviewerArtifacts('scratch-bugfix-existing-app', model, dispatchInfo, {
		expectFeed: false,
		repoRoot: scratchRoot,
	});
	assertGovernorDecision('scratch-bugfix-existing-app', model, dispatchInfo, {
		expectFeed: false,
	});
	for (const devRef of ['index.html', path.join('data', 'sample-pets.json'), path.join('src', 'app.js')]) {
		assertCondition(
			!fs.existsSync(path.join(repoRoot, devRef)),
			`scratch-bugfix-existing-app: wrote ${devRef} to Corgi source repo`
		);
	}
	if (!options.keep) {
		fs.rmSync(runDir, { recursive: true, force: true });
	}
	return {
		id: 'module:scratch-bugfix-existing-app',
		stage: model.snapshot.currentStage,
		permissionScope: model.snapshot.permissionScope,
		dispatchRef: dispatchInfo.request.dispatch_ref,
	};
}

function runScratchFeatureExistingAppModule(options) {
	const prompt = promptById('pet-life-diary-filter');
	assertCondition(prompt, 'scratch-feature-existing-app: prompt preset missing');
	const runName = `module-scratch-feature-existing-app-${runId}`;
	const { agentRoot, runDir, scratchRoot, env } = createScratchTestEnv(
		runName,
		'pet-life-diary-filter'
	);
	seedFilterPetDiaryApp(scratchRoot);
	const baselineIndex = fs.readFileSync(path.join(scratchRoot, 'index.html'), 'utf8');
	const baselineApp = fs.readFileSync(path.join(scratchRoot, 'src/app.js'), 'utf8');
	assertCondition(
		!baselineIndex.includes('species-filter') && !baselineApp.includes('visibleEntries'),
		'scratch-feature-existing-app: seeded app unexpectedly starts with species filter'
	);
	const model = runGovernedWorkFlow(prompt, env, true);
	const dispatchInfo = latestDispatchInfo(agentRoot);
	const request = readJson(dispatchInfo.requestPath);
	const state = readJson(path.join(dispatchInfo.dispatchDir, 'state.json'));
	const result = readJson(path.join(dispatchInfo.dispatchDir, 'result.json'));
	const outputSignatures = result.output_signatures;
	const validationPath = path.join(
		scratchRoot,
		'.agent',
		'validations',
		dispatchInfo.request.dispatch_ref,
		'pet_diary_species_filter.json'
	);
	const patchSpecPath = path.join(
		scratchRoot,
		'.agent',
		'patch_specs',
		dispatchInfo.request.dispatch_ref,
		'pet_diary_species_filter.json'
	);
	const indexPatchPath = path.join(
		scratchRoot,
		'.agent',
		'patches',
		dispatchInfo.request.dispatch_ref,
		'pet_diary_species_filter-index-html.patch'
	);
	const appPatchPath = path.join(
		scratchRoot,
		'.agent',
		'patches',
		dispatchInfo.request.dispatch_ref,
		'pet_diary_species_filter-src-app-js.patch'
	);
	const updatedIndex = fs.readFileSync(path.join(scratchRoot, 'index.html'), 'utf8');
	const updatedApp = fs.readFileSync(path.join(scratchRoot, 'src/app.js'), 'utf8');
	assertCondition(
		updatedIndex.includes('id="species-filter"'),
		'scratch-feature-existing-app: index.html did not add species filter control'
	);
	assertCondition(
		updatedApp.includes('function visibleEntries()'),
		'scratch-feature-existing-app: src/app.js did not add visibleEntries helper'
	);
	assertCondition(
		updatedApp.includes('.filter((entry) => entry.species === selectedSpecies)'),
		'scratch-feature-existing-app: src/app.js did not filter entries by species'
	);
	for (const outputRef of ['index.html', 'src/app.js']) {
		assertCondition(
			request.required_outputs.includes(outputRef),
			`scratch-feature-existing-app: ${outputRef} missing from required_outputs`
		);
		assertCondition(
			result.written_or_updated.includes(outputRef),
			`scratch-feature-existing-app: ${outputRef} missing from executor result`
		);
		assertCondition(
			outputSignatures?.required_outputs?.[outputRef]?.classification === 'mutated',
			`scratch-feature-existing-app: ${outputRef} missing mutated authorship evidence`
		);
	}
	assertCondition(
		outputSignatures?.verified === true,
		'scratch-feature-existing-app: authorship evidence was not verified'
	);
	assertCondition(
		Array.isArray(outputSignatures?.blockers) && outputSignatures.blockers.length === 0,
		'scratch-feature-existing-app: authorship evidence reported blockers'
	);
	for (const artifactPath of [validationPath, patchSpecPath, indexPatchPath, appPatchPath]) {
		assertCondition(fs.existsSync(artifactPath), `scratch-feature-existing-app: missing ${artifactPath}`);
	}
	const patchSpec = readJson(patchSpecPath);
	const operations = Array.isArray(patchSpec.operations) ? patchSpec.operations : [];
	const operationPaths = operations.map((operation) => operation.path);
	assertCondition(
		patchSpec.schema_version === 'corgi.patch-spec.v1' &&
			patchSpec.proposed_by === 'executor' &&
			operationPaths.includes('index.html') &&
			operationPaths.includes('src/app.js') &&
			operations.every(
				(operation) =>
					typeof operation.before_sha256 === 'string' &&
					Number.isInteger(operation.before_size)
			),
		'scratch-feature-existing-app: patch spec does not cover index.html and src/app.js'
	);
	const indexPatch = fs.readFileSync(indexPatchPath, 'utf8');
	const appPatch = fs.readFileSync(appPatchPath, 'utf8');
	assertCondition(
		indexPatch.includes('--- a/index.html') &&
			indexPatch.includes('+++ b/index.html') &&
			indexPatch.includes('+				<label for="species-filter">Filter entries by species</label>'),
		'scratch-feature-existing-app: index patch does not add the filter control'
	);
	assertCondition(
		appPatch.includes('--- a/src/app.js') &&
			appPatch.includes('+++ b/src/app.js') &&
			appPatch.includes('+function visibleEntries()'),
		'scratch-feature-existing-app: app patch does not add filter logic'
	);
	assertCondition(
		request.execution_payload.evidence.some((ref) => ref.endsWith('pet_diary_species_filter.json')),
		'scratch-feature-existing-app: patch spec or validation missing from dispatch evidence'
	);
	assertCondition(
		request.execution_payload.evidence.some((ref) => ref.endsWith('pet_diary_species_filter-index-html.patch')) &&
			request.execution_payload.evidence.some((ref) =>
				ref.endsWith('pet_diary_species_filter-src-app-js.patch')
			),
		'scratch-feature-existing-app: patch artifacts missing from dispatch evidence'
	);
	assertCondition(
		request.execution_payload.commands.some((command) =>
			commandSpecText(command).includes('executor_propose_patch_spec.py')
		),
		'scratch-feature-existing-app: dispatch did not use executor patch proposal command'
	);
	assertCondition(
		request.execution_payload.commands.some((command) =>
			commandSpecText(command).includes('executor_apply_patch_spec.py')
		),
		'scratch-feature-existing-app: dispatch did not use generic patch spec executor'
	);
	const validation = readJson(validationPath);
	assertCondition(
		validation.status === 'pass',
		`scratch-feature-existing-app: validation did not pass (${validation.failures?.join(', ')})`
	);
	assertCondition(
		request.execution_mode === 'command_chain',
		'scratch-feature-existing-app: unexpected execution mode'
	);
	assertCondition(
		request.execution_payload.notes.includes('scratch_pet_diary_filter_feature'),
		'scratch-feature-existing-app: missing scratch feature execution note'
	);
	assertCondition(
		state.status === 'completed' || state.status === 'validated',
		'scratch-feature-existing-app: executor state did not complete'
	);
	assertReviewerArtifacts('scratch-feature-existing-app', model, dispatchInfo, {
		expectFeed: false,
		repoRoot: scratchRoot,
	});
	assertGovernorDecision('scratch-feature-existing-app', model, dispatchInfo, {
		expectFeed: false,
	});
	for (const devRef of ['index.html', path.join('data', 'sample-pets.json'), path.join('src', 'app.js')]) {
		assertCondition(
			!fs.existsSync(path.join(repoRoot, devRef)),
			`scratch-feature-existing-app: wrote ${devRef} to Corgi source repo`
		);
	}
	if (!options.keep) {
		fs.rmSync(runDir, { recursive: true, force: true });
	}
	return {
		id: 'module:scratch-feature-existing-app',
		stage: model.snapshot.currentStage,
		permissionScope: model.snapshot.permissionScope,
		dispatchRef: dispatchInfo.request.dispatch_ref,
	};
}

function runModule(moduleName, options) {
	switch (moduleName) {
		case 'executor':
			return [runExecutorModule(options)];
		case 'reviewer':
			return [runReviewerModule(options)];
		case 'review-replan':
			return [runReviewReplanModule(options)];
		case 'scratch-static-app':
			return [runScratchStaticAppModule(options)];
		case 'scratch-bugfix-existing-app':
			return [runScratchBugfixExistingAppModule(options)];
		case 'scratch-feature-existing-app':
			return [runScratchFeatureExistingAppModule(options)];
		case 'completion':
			return [
				runScratchStaticAppModule(options),
				runScratchBugfixExistingAppModule(options),
				runScratchFeatureExistingAppModule(options),
			];
		case 'all':
			return [
				runExecutorModule(options),
				runReviewerModule(options),
				runReviewReplanModule(options),
			];
		default:
			throw new Error(`Unknown module: ${moduleName}`);
	}
}

function main() {
	const options = parseArgs(process.argv.slice(2));
	if (options.module) {
		const results = runModule(options.module, options);
		for (const result of results) {
			process.stdout.write(
				`[process-test] ${result.id}: ${result.stage} (${result.permissionScope})\n`
			);
		}
		process.stdout.write(`Validated ${results.length} command-only module flow(s).\n`);
		return;
	}
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
