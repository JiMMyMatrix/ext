#!/usr/bin/env node

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const repoRoot = path.join(__dirname, '..');
const defaultTestRoot = path.join(os.homedir(), '.corgi', 'test-window', 'extension-ext');

function parseArgs(argv) {
	const options = {
		json: false,
		watch: false,
		intervalSeconds: 5,
		timeoutSeconds: Number(process.env.CORGI_PRACTICAL_MONITOR_TIMEOUT_SECONDS || 0),
		stallSeconds: Number(process.env.CORGI_PRACTICAL_MONITOR_STALL_SECONDS || 300),
		testRoot: process.env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot,
		expectedPreset: process.env.CORGI_TEST_WINDOW_PROMPT_PRESET || 'pet-life-diary-real-project',
	};
	for (let index = 0; index < argv.length; index += 1) {
		const arg = argv[index];
		if (arg === '--json') {
			options.json = true;
		} else if (arg === '--watch') {
			options.watch = true;
		} else if (arg === '--interval-seconds') {
			options.intervalSeconds = Number(argv[++index] || options.intervalSeconds);
		} else if (arg === '--timeout-seconds') {
			options.timeoutSeconds = Number(argv[++index] || options.timeoutSeconds);
		} else if (arg === '--stall-seconds') {
			options.stallSeconds = Number(argv[++index] || options.stallSeconds);
		} else if (arg === '--test-root') {
			options.testRoot = argv[++index] || options.testRoot;
		} else if (arg === '--expected-preset') {
			options.expectedPreset = argv[++index] || options.expectedPreset;
		} else {
			throw new Error(`Unknown argument: ${arg}`);
		}
	}
	return options;
}

const PROJECT_TEXT_EXTENSIONS = new Set([
	'.css',
	'.html',
	'.js',
	'.json',
	'.jsx',
	'.md',
	'.mjs',
	'.ts',
	'.tsx',
	'.txt',
	'.vue',
]);

const PROJECT_IGNORED_DIRS = new Set([
	'.agent',
	'.git',
	'.vscode',
	'.vscode-test',
	'coverage',
	'dist',
	'node_modules',
	'out',
	'__pycache__',
]);

function readJson(filePath) {
	if (!filePath || !fs.existsSync(filePath)) {
		return undefined;
	}
	try {
		return JSON.parse(fs.readFileSync(filePath, 'utf8'));
	} catch (error) {
		return {
			__readError: error instanceof Error ? error.message : String(error),
			__path: filePath,
		};
	}
}

function runStatus(testRoot) {
	const result = spawnSync(
		process.execPath,
		[path.join(repoRoot, 'scripts', 'corgi-test-window-status.cjs'), '--json'],
		{
			env: { ...process.env, CORGI_TEST_WINDOW_ROOT: testRoot },
			encoding: 'utf8',
			maxBuffer: 4 * 1024 * 1024,
		}
	);
	if (!result.stdout.trim()) {
		return {
			ok: false,
			statusError: result.stderr.trim() || result.error?.message || 'status command produced no output',
		};
	}
	try {
		return JSON.parse(result.stdout);
	} catch (error) {
		return {
			ok: false,
			statusError: error instanceof Error ? error.message : String(error),
			rawStatus: result.stdout,
		};
	}
}

function listFilesByName(root, basename) {
	const files = [];
	if (!root || !fs.existsSync(root)) {
		return files;
	}
	const stack = [root];
	while (stack.length) {
		const current = stack.pop();
		let entries = [];
		try {
			entries = fs.readdirSync(current, { withFileTypes: true });
		} catch {
			continue;
		}
		for (const entry of entries) {
			const filePath = path.join(current, entry.name);
			if (entry.isDirectory()) {
				if (entry.name === 'node_modules' || entry.name === '.git') {
					continue;
				}
				stack.push(filePath);
			} else if (entry.isFile() && entry.name === basename) {
				files.push(filePath);
			}
		}
	}
	return files.sort();
}

function listGoalRefs(agentRoot) {
	const goalsRoot = path.join(agentRoot || '', 'goals');
	if (!fs.existsSync(goalsRoot)) {
		return [];
	}
	return fs
		.readdirSync(goalsRoot, { withFileTypes: true })
		.filter((entry) => entry.isDirectory())
		.map((entry) => entry.name)
		.sort();
}

function collectGoals(agentRoot) {
	return listGoalRefs(agentRoot).map((goalRef) => {
		const goalRoot = path.join(agentRoot, 'goals', goalRef);
		return {
			goalRef,
			goal: readJson(path.join(goalRoot, 'goal.json')),
			plan: readJson(path.join(goalRoot, 'goal_plan.json')),
			progress: readJson(path.join(goalRoot, 'goal_progress.json')),
			decision: readJson(path.join(goalRoot, 'goal_decision.json')),
		};
	});
}

function collectDispatches(agentRoot) {
	return listFilesByName(path.join(agentRoot || '', 'dispatches'), 'request.json').map((requestPath) => {
		const request = readJson(requestPath) || {};
		const dispatchDir = path.dirname(requestPath);
			return {
				dispatchRef: request.dispatch_ref || path.basename(dispatchDir),
				requestPath,
				dispatchDir,
				request,
				state: readJson(path.join(dispatchDir, 'state.json')),
				result: readJson(path.join(dispatchDir, 'result.json')),
				decision: readJson(path.join(dispatchDir, 'governor_decision.json')),
			};
		});
}

function collectReviews(agentRoot) {
	return listFilesByName(path.join(agentRoot || '', 'reviews'), 'review.json').map((reviewPath) => ({
		reviewPath,
		review: readJson(reviewPath),
	}));
}

function pathInside(childPath, parentPath) {
	if (!childPath || !parentPath) {
		return false;
	}
	const relative = path.relative(parentPath, childPath);
	return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
}

function shouldCountProjectFile(filePath) {
	const extension = path.extname(filePath).toLowerCase();
	return PROJECT_TEXT_EXTENSIONS.has(extension);
}

function countProjectLines(workspaceRoot) {
	const result = {
		totalLines: 0,
		fileCount: 0,
	};
	if (!workspaceRoot || !fs.existsSync(workspaceRoot)) {
		return result;
	}
	const stack = [workspaceRoot];
	while (stack.length) {
		const current = stack.pop();
		let entries = [];
		try {
			entries = fs.readdirSync(current, { withFileTypes: true });
		} catch {
			continue;
		}
		for (const entry of entries) {
			const filePath = path.join(current, entry.name);
			if (entry.isDirectory()) {
				if (PROJECT_IGNORED_DIRS.has(entry.name)) {
					continue;
				}
				stack.push(filePath);
				continue;
			}
			if (!entry.isFile() || !shouldCountProjectFile(filePath)) {
				continue;
			}
			try {
				const content = fs.readFileSync(filePath, 'utf8');
				result.totalLines += content.length ? content.split(/\r\n|\r|\n/).length : 0;
				result.fileCount += 1;
			} catch {
				// Ignore unreadable files; isolation/write checks report workspace problems separately.
			}
		}
	}
	return result;
}

function compact(value, limit = 180) {
	return String(value || '')
		.replace(/\s+/g, ' ')
		.trim()
		.slice(0, limit);
}

function isReadoutOnlyDispatch(dispatch) {
	const payload = dispatch.request?.execution_payload;
	const notes = Array.isArray(payload?.notes) ? payload.notes : [];
	const commands = Array.isArray(payload?.commands) ? payload.commands : [];
	return (
		notes.includes('artifact_only_executor_readout') ||
		commands.some((command) =>
			Array.isArray(command?.argv)
				? command.argv.some((part) => String(part).includes('executor_write_readout.py'))
				: false
		)
	);
}

function latestGoal(goals) {
	return goals
		.slice()
		.sort((left, right) => {
			const leftTime = Date.parse(left.progress?.updated_at || left.goal?.updated_at || left.goal?.created_at || '');
			const rightTime = Date.parse(right.progress?.updated_at || right.goal?.updated_at || right.goal?.created_at || '');
			return (Number.isNaN(rightTime) ? 0 : rightTime) - (Number.isNaN(leftTime) ? 0 : leftTime);
		})[0];
}

function summarize(options) {
	const currentRunPath = path.join(options.testRoot, 'current-run.json');
	const currentRun = readJson(currentRunPath) || {};
	const status = runStatus(options.testRoot);
	const snapshot = readJson(currentRun.snapshotPath);
	const payload = snapshot?.payload || {};
	const modelSnapshot = payload.model?.snapshot || {};
	const agentRoot = currentRun.agentRoot;
	const goals = collectGoals(agentRoot);
	const activeGoal = latestGoal(goals);
		const dispatches = collectDispatches(agentRoot);
		const reviews = collectReviews(agentRoot);
		const readoutOnlyDispatches = dispatches.filter(isReadoutOnlyDispatch);
		const activeDispatches = dispatches.filter((dispatch) =>
			['claimed', 'running'].includes(String(dispatch.state?.status || ''))
		);
		const queuedDispatches = dispatches.filter((dispatch) => String(dispatch.state?.status || '') === 'queued');
	const runStartedAt = Date.parse(currentRun.recordedAt || '');
	const runElapsedSeconds = Number.isNaN(runStartedAt)
		? 0
		: Math.max(0, Math.floor((Date.now() - runStartedAt) / 1000));
	const completedStepRefs = Array.isArray(activeGoal?.progress?.completed_steps)
		? activeGoal.progress.completed_steps
		: [];
	const linkedWorkRefs = Array.isArray(activeGoal?.progress?.linked_work_refs)
		? activeGoal.progress.linked_work_refs
		: [];
	const goalSteps = Array.isArray(activeGoal?.plan?.steps) ? activeGoal.plan.steps : [];
	const uniqueWorkRefs = new Set(
		[
			...linkedWorkRefs,
			...goalSteps.map((step) => step?.work_ref).filter(Boolean),
			...dispatches.map((dispatch) => dispatch.request?.work_ref).filter(Boolean),
		].map(String)
	);
	const sourceRoot = currentRun.sourceRoot || repoRoot;
	const workspaceRoot = currentRun.workspaceRoot;
	const projectSize = countProjectLines(workspaceRoot);
	const blockers = [];
	const warnings = [];
	if (!currentRun.workspaceRoot) {
		blockers.push('missing_current_run');
	}
	if (currentRun.promptPreset && currentRun.promptPreset !== options.expectedPreset) {
		warnings.push(`unexpected_prompt_preset:${currentRun.promptPreset}`);
	}
	if (options.expectedPreset === 'pet-life-diary-real-project') {
		if (currentRun.goalPlanSource !== 'governor') {
			blockers.push('goal_plan_source_not_governor');
		}
		if (readoutOnlyDispatches.length > 0) {
			blockers.push('readout_only_executor_fallback');
		}
	}
	if (status.isolationError) {
		blockers.push('scratch_isolation_error');
	}
	if (status.writeError) {
		blockers.push('scratch_write_error');
	}
	if (status.processError) {
		blockers.push('test_window_process_stopped');
	}
	if (status.statusError) {
		blockers.push('test_window_status_unavailable');
	}
	if (status.feedHasError || status.knownBlockingError) {
		blockers.push('ui_error_feed');
	}
	if (Array.isArray(status.logErrors) && status.logErrors.length > 0) {
		blockers.push('test_window_log_error');
	}
	if (status.snapshot === 'missing') {
		const runAgeMs = Date.now() - Date.parse(currentRun.recordedAt || '');
		if (Number.isNaN(runAgeMs) || runAgeMs > 60_000) {
			blockers.push('snapshot_missing');
		}
	}
	if (workspaceRoot && sourceRoot && (workspaceRoot === sourceRoot || pathInside(workspaceRoot, sourceRoot))) {
		blockers.push('workspace_inside_development_repo');
	}
		const stage = status.stage || modelSnapshot.currentStage || '';
		const dispatchRunState =
			activeDispatches.length > 0 ? 'running' : queuedDispatches.length > 0 ? 'queued' : '';
		const runState = dispatchRunState || status.runState || modelSnapshot.runState || '';
		const ageMs = Number(status.ageMs || 0);
		if (
			activeDispatches.length === 0 &&
			(runState === 'running' || stage === 'governor_running') &&
			ageMs > options.stallSeconds * 1000
		) {
			blockers.push('snapshot_stalled');
		}
	if (
		activeGoal?.progress?.status === 'active' &&
		activeGoal?.progress?.continuation_state !== 'pending' &&
		goalSteps.length > 0 &&
		dispatches.length === 0 &&
		stage !== 'goal_planning' &&
		stage !== 'goal_continuation_pending' &&
		ageMs > options.stallSeconds * 1000
	) {
		blockers.push('no_dispatch_after_goal_plan');
	}
	if (['executor_blocked', 'reviewer_blocked', 'goal_blocked'].includes(stage)) {
		blockers.push(stage);
	}
	if (activeGoal?.goalRef && dispatches.length > 0) {
		const goalDispatchesMissingLinkage = dispatches.filter((dispatch) => {
			const request = dispatch.request || {};
			return (
				request.work_ref &&
				(!request.goal_ref ||
					request.goal_ref !== activeGoal.goalRef ||
					!request.goal_step_ref ||
					typeof request.goal_step_index !== 'number')
			);
		});
		if (goalDispatchesMissingLinkage.length > 0) {
			blockers.push('dispatch_goal_linkage_missing');
		}
	}
	const completed =
		activeGoal?.progress?.status === 'completed' ||
		activeGoal?.goal?.status === 'completed' ||
		stage === 'goal_completed';
	const practicalExercise = {
		elapsedSeconds: runElapsedSeconds,
		projectLineCount: projectSize.totalLines,
		projectFileCount: projectSize.fileCount,
		goalStepCount: goalSteps.length,
		completedStepCount: completedStepRefs.length,
		workRefCount: uniqueWorkRefs.size,
		dispatchCount: dispatches.length,
		reviewCount: reviews.length,
			readoutOnlyDispatchCount: readoutOnlyDispatches.length,
			activeDispatchCount: activeDispatches.length,
		};
	return {
		ok: blockers.length === 0,
		completed,
		blockers,
		warnings,
		currentRunPath,
		promptPreset: currentRun.promptPreset || null,
		goalPlanSource: currentRun.goalPlanSource || null,
		executorRuntime: currentRun.executorRuntime || null,
		workspaceMode: currentRun.workspaceMode || null,
		workspaceRoot: currentRun.workspaceRoot || null,
		agentRoot: currentRun.agentRoot || null,
		snapshotPath: currentRun.snapshotPath || null,
		stage,
		actor: status.actor || modelSnapshot.currentActor || '',
		runState,
		goalStrip: status.goalStrip || payload.goalStrip || '',
		goalRef: activeGoal?.goalRef || modelSnapshot.currentGoalRef || null,
		goalStatus: activeGoal?.progress?.status || modelSnapshot.goalStatus || null,
		currentStep:
			activeGoal?.progress?.current_step_ref ||
			modelSnapshot.currentGoalStepRef ||
			null,
		currentStepIndex:
			activeGoal?.progress?.current_step_index ??
			modelSnapshot.currentGoalStepIndex ??
			null,
		goalStepCount: goalSteps.length || modelSnapshot.goalStepCount || 0,
		completedSteps: completedStepRefs,
		workRefs: Array.from(uniqueWorkRefs).sort(),
			dispatchRefs: dispatches.map((dispatch) => dispatch.dispatchRef).sort(),
			activeDispatchRefs: activeDispatches.map((dispatch) => dispatch.dispatchRef).sort(),
			readoutOnlyDispatches: readoutOnlyDispatches.map((dispatch) => dispatch.dispatchRef).sort(),
		reviewCount: reviews.length,
		latestReviewVerdict: status.latestReviewVerdict || '',
		latestGovernorDecision: status.latestGovernorDecision || '',
		practicalExercise,
		status,
	};
}

function printSummary(summary) {
	const lines = [
		`Practical Corgi exercise: ${summary.ok ? 'running cleanly' : 'attention needed'}`,
		`Preset: ${summary.promptPreset || '(none)'} · plan source: ${summary.goalPlanSource || '(unset)'}`,
		`Workspace: ${summary.workspaceMode || '(none)'} ${summary.workspaceRoot || ''}`,
		`State: ${summary.actor || '(none)'} / ${summary.stage || '(none)'} / ${summary.runState || '(none)'}`,
		`Goal: ${summary.goalRef || '(none)'} ${summary.currentStep ? `step ${summary.currentStep}` : ''} (${summary.completedSteps.length}/${summary.goalStepCount || 0} completed)`,
			`Work: ${summary.workRefs.length} workRef(s), ${summary.dispatchRefs.length} dispatch(es), ${summary.activeDispatchRefs.length} active, ${summary.reviewCount} review(s)`,
		`Elapsed: ${summary.practicalExercise.elapsedSeconds}s`,
		`Project lines observed: ${summary.practicalExercise.projectLineCount} lines across ${summary.practicalExercise.projectFileCount} file(s)`,
		`Readout-only dispatches: ${summary.readoutOnlyDispatches.length ? summary.readoutOnlyDispatches.join(', ') : 'none'}`,
		summary.blockers.length ? `Blockers: ${summary.blockers.join(', ')}` : 'Blockers: none',
		summary.warnings.length ? `Warnings: ${summary.warnings.join(', ')}` : 'Warnings: none',
		summary.goalStrip ? `Visible: ${compact(summary.goalStrip)}` : 'Visible: (none)',
	];
	process.stdout.write(`${lines.join('\n')}\n`);
}

async function main() {
	const options = parseArgs(process.argv.slice(2));
	if (!options.watch) {
		const summary = summarize(options);
		if (options.json) {
			process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
		} else {
			printSummary(summary);
		}
		process.exitCode = summary.completed && summary.ok ? 0 : summary.ok ? 0 : 2;
		return;
	}

	const startedAt = Date.now();
	let lastLine = '';
	while (!options.timeoutSeconds || Date.now() - startedAt < options.timeoutSeconds * 1000) {
		const summary = summarize(options);
		const line = [
			summary.stage || '(none)',
			summary.runState || '(none)',
			summary.goalRef || '(no-goal)',
			`${summary.completedSteps.length}/${summary.goalStepCount || 0}`,
			`dispatches=${summary.dispatchRefs.length}`,
			`elapsed=${summary.practicalExercise.elapsedSeconds}s`,
			`lines=${summary.practicalExercise.projectLineCount}`,
			summary.blockers.length ? `blockers=${summary.blockers.join(',')}` : 'clean',
		].join(' ');
		if (line !== lastLine) {
			process.stdout.write(`[${new Date().toISOString()}] ${line}\n`);
			lastLine = line;
		}
		if (summary.blockers.length) {
			if (options.json) {
				process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
			} else {
				printSummary(summary);
			}
			process.exitCode = 2;
			return;
		}
		await new Promise((resolve) => setTimeout(resolve, options.intervalSeconds * 1000));
	}
	const summary = summarize(options);
	summary.blockers.push('monitor_timeout');
	if (options.json) {
		process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
	} else {
		printSummary(summary);
	}
	process.exitCode = 1;
}

main().catch((error) => {
	console.error(error instanceof Error ? error.stack || error.message : String(error));
	process.exitCode = 1;
});
