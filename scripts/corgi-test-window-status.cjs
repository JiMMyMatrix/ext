#!/usr/bin/env node

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const root = path.join(__dirname, '..');
const defaultTestRoot = path.join(os.homedir(), '.corgi', 'test-window', 'extension-ext');
const testRoot = process.env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot;
const currentRunPath = path.join(testRoot, 'current-run.json');
const currentRun = readJson(currentRunPath) || {};
const userDataDir = currentRun.userDataDir || path.join(testRoot, 'vscode-profile', 'user-data');
const oldUserDataDir = path.join(root, '.agent', 'test-window', 'vscode-profile', 'user-data');
const legacyUserDataDir = path.join(root, '.agent', 'vscode-governor-first-test-user-data');
const snapshotPath =
	currentRun.snapshotPath ||
	path.join(
		testRoot,
		'runtime-agent',
		'orchestration',
		'corgi_webview_snapshot.json'
	);
const stderrPath = currentRun.stderrPath || path.join(testRoot, 'logs', 'vscode.stderr.log');

function readJson(filePath) {
	if (!fs.existsSync(filePath)) {
		return undefined;
	}
	return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function readText(filePath) {
	if (!fs.existsSync(filePath)) {
		return '';
	}
	return fs.readFileSync(filePath, 'utf8');
}

function commandSucceeds(command, args) {
	const result = spawnSync(command, args, { stdio: 'ignore' });
	return result.status === 0;
}

function profileProcessAlive(profileDir) {
	return commandSucceeds('pgrep', ['-f', profileDir]);
}

function processState() {
	return {
		current: profileProcessAlive(userDataDir),
		oldProfile: profileProcessAlive(oldUserDataDir),
		legacyProfile: profileProcessAlive(legacyUserDataDir),
	};
}

function compact(value, limit = 240) {
	return String(value || '')
		.replace(/\s+/g, ' ')
		.trim()
		.slice(0, limit);
}

function relevantLogErrors(stderr) {
	return stderr
		.split(/\r?\n/)
		.filter(Boolean)
		.filter((line) => /error|exception|traceback|fatal|failed/i.test(line))
		.filter((line) => !isKnownBenignVsCodeLogLine(line));
}

function isKnownBenignVsCodeLogLine(line) {
	return [
		'CrossAppIPC: Failed to get peer bundle ID.',
		'GPU process exited unexpectedly: exit_code=15',
		'Network service crashed, restarting service.',
		'Render frame was disposed before WebFrameMain could be accessed',
		'mach_port_request_notification: (os/kern) invalid capability (20)',
	].some((needle) => line.includes(needle)) ||
		/^\s+at .*\/Applications\/Visual%20Studio%20Code\.app\/.*\/out\/main\.js/.test(
			line
		);
}

function snapshotAgeMs(snapshot) {
	const timestamp = Date.parse(
		snapshot?.payload?.renderedAt || snapshot?.recordedAt || ''
	);
	if (Number.isNaN(timestamp)) {
		return undefined;
	}
	return Date.now() - timestamp;
}

function realpathIfExists(filePath) {
	if (!filePath || !fs.existsSync(filePath)) {
		return undefined;
	}
	return fs.realpathSync(filePath);
}

function pathInside(childPath, parentPath) {
	if (!childPath || !parentPath) {
		return false;
	}
	const relative = path.relative(parentPath, childPath);
	return relative !== '' && !relative.startsWith('..') && !path.isAbsolute(relative);
}

function workspaceIsolationError() {
	const workspaceRoot = realpathIfExists(currentRun.workspaceRoot);
	const sourceRoot = realpathIfExists(currentRun.sourceRoot || root);
	const agentRoot = realpathIfExists(currentRun.agentRoot);
	const testRootReal = realpathIfExists(testRoot);
	if (!currentRun.workspaceRoot) {
		return '';
	}
	if (!workspaceRoot || !sourceRoot || !testRootReal) {
		return 'Test workspace isolation metadata is incomplete.';
	}
	if (testRootReal === sourceRoot || pathInside(testRootReal, sourceRoot)) {
		return 'Test root is inside the development repo.';
	}
	if (workspaceRoot === sourceRoot) {
		return 'Test window is using the development repo as its workspace.';
	}
	if (!pathInside(workspaceRoot, testRootReal)) {
		return 'Test window workspace is outside the configured test root.';
	}
	if (agentRoot && agentRoot === path.join(sourceRoot, '.agent')) {
		return 'Test window is using the development .agent folder.';
	}
	if (agentRoot && !pathInside(agentRoot, testRootReal)) {
		return 'Test window agent root is outside the configured test root.';
	}
	if (
		currentRun.workspaceMode === 'repo' &&
		!pathInside(workspaceRoot, path.join(testRootReal, 'repo-workspaces'))
	) {
		return 'Repo-mode test window is not using repo-workspaces isolation.';
	}
	if (
		currentRun.workspaceMode === 'scratch' &&
		!pathInside(workspaceRoot, path.join(testRootReal, 'scratch-workspaces'))
	) {
		return 'Scratch-mode test window is not using scratch-workspaces isolation.';
	}
	if (
		currentRun.workspaceMode === 'empty' &&
		!pathInside(workspaceRoot, path.join(testRootReal, 'empty-workspaces'))
	) {
		return 'Empty-mode test window is not using empty-workspaces isolation.';
	}
	return '';
}

function writableDirError(dirPath, label) {
	const realDir = realpathIfExists(dirPath);
	if (!realDir) {
		return `${label} is missing.`;
	}
	const probePath = path.join(
		realDir,
		`.corgi-write-check-${process.pid}-${Date.now()}-${Math.random()
			.toString(16)
			.slice(2)}`
	);
	try {
		fs.writeFileSync(probePath, 'ok\n', { flag: 'wx' });
		fs.rmSync(probePath, { force: true });
		return '';
	} catch (error) {
		try {
			fs.rmSync(probePath, { force: true });
		} catch {
			// Best effort cleanup only; report the original writeability issue.
		}
		const message = error instanceof Error ? error.message : String(error);
		return `${label} is not writable: ${message}`;
	}
}

function workspaceWriteError() {
	if (!currentRun.workspaceRoot) {
		return '';
	}
	return (
		writableDirError(currentRun.workspaceRoot, 'Test workspace') ||
		writableDirError(currentRun.agentRoot, 'Test agent root')
	);
}

function isCompletedLastRun(state, payload) {
	const stage = String(state.currentStage || '');
	const runState = String(state.runState || '');
	const autoMode = String(payload.autoStep?.mode || '');
	if (runState !== 'idle') {
		return false;
	}
	if (stage === 'governor_decision_recorded') {
		return true;
	}
	return autoMode === 'plan' && stage === 'plan_ready';
}

function summarize() {
	const snapshot = readJson(snapshotPath);
	const payload = snapshot?.payload || {};
	const state = payload.state || {};
	const modelSnapshot = payload.model?.snapshot || {};
	const feed = Array.isArray(payload.model?.feed) ? payload.model.feed : [];
	const messages = Array.isArray(payload.messages) ? payload.messages : [];
	const progress = Array.isArray(payload.progress) ? payload.progress : [];
	const actions = Array.isArray(payload.actions) ? payload.actions : [];
	const stderr = readText(stderrPath);
	const logErrors = relevantLogErrors(stderr);
	const blockingText = [
		payload.goalStrip,
		...messages
			.filter((message) => /error|is-error|failed|attention/i.test(message.className || ''))
			.map((message) => message.text),
	]
		.map((text) => compact(text, 2000))
		.join('\n');
	const feedHasError = feed.some((item) => item?.type === 'error');
	const knownBlockingError = /session changed/i.test(blockingText);
	const ageMs = snapshotAgeMs(snapshot);
	const stale =
		typeof ageMs === 'number' &&
		ageMs > 20_000 &&
			(state.runState === 'running' || state.currentStage === 'governor_running');
	const isolationError = workspaceIsolationError();
	const writeError = workspaceWriteError();
	const processes = processState();
	const lastRunCompleted = Boolean(snapshot) && isCompletedLastRun(state, payload);
	const processError = currentRun.userDataDir && !processes.current && !lastRunCompleted
		? 'Current Corgi test window process is not running.'
		: '';

	return {
		ok:
			Boolean(snapshot) &&
			!processError &&
			logErrors.length === 0 &&
			!feedHasError &&
			!knownBlockingError &&
			!stale &&
			!isolationError &&
			!writeError,
		snapshot: snapshot ? 'present' : 'missing',
		processAlive: processes.current,
		oldProfileProcessAlive: processes.oldProfile,
		legacyProfileProcessAlive: processes.legacyProfile,
		recordedAt: snapshot?.recordedAt || null,
		ageMs: ageMs ?? null,
		goalStrip: payload.goalStrip || payload.header || '',
		stage: state.currentStage || '',
		actor: state.currentActor || '',
		runState: state.runState || '',
		permissionScope: state.permissionScope || '',
		currentAttemptNumber: state.currentAttemptNumber ?? modelSnapshot.currentAttemptNumber ?? null,
		currentPlanVersion: state.currentPlanVersion ?? modelSnapshot.currentPlanVersion ?? null,
		latestReviewVerdict: state.latestReviewVerdict || modelSnapshot.latestReviewVerdict || '',
		latestGovernorDecision:
			state.latestGovernorDecision || modelSnapshot.latestGovernorDecision || '',
		workspaceMode: currentRun.workspaceMode || 'repo',
		workspaceRoot: currentRun.workspaceRoot || null,
		workspaceFile: currentRun.workspaceFile || null,
		agentRoot: currentRun.agentRoot || null,
		autoStep: payload.autoStep || null,
		actions: actions.map((action) => action.text).filter(Boolean),
		composer: payload.composer || null,
		messages: messages.map((message) => message.text).filter(Boolean).slice(-6),
		progress: progress.map((item) => item.text).filter(Boolean).slice(-6),
		logErrors,
		feedHasError,
		knownBlockingError,
		stale,
		lastRunCompleted,
		isolationError,
		writeError,
		processError,
	};
}

const summary = summarize();
if (process.argv.includes('--json')) {
	process.stdout.write(`${JSON.stringify(summary, null, 2)}\n`);
} else {
	process.stdout.write(
		[
			`Corgi test window: ${summary.ok ? 'healthy' : 'attention needed'}`,
				`Snapshot: ${summary.snapshot}${summary.ageMs === null ? '' : ` (${Math.round(summary.ageMs / 1000)}s old)`}`,
				`Process: ${summary.processAlive ? 'live' : summary.lastRunCompleted ? 'completed' : 'not running'}`,
				summary.oldProfileProcessAlive || summary.legacyProfileProcessAlive
					? `Legacy processes: old=${summary.oldProfileProcessAlive ? 'live' : 'none'} legacy=${summary.legacyProfileProcessAlive ? 'live' : 'none'}`
					: 'Legacy processes: none',
				`Workspace: ${summary.workspaceMode}${summary.workspaceRoot ? ` (${summary.workspaceRoot})` : ''}`,
			`Workspace file: ${summary.workspaceFile || '(none)'}`,
			`Goal: ${summary.goalStrip || '(none)'}`,
			`State: actor=${summary.actor || '(none)'} stage=${summary.stage || '(none)'} run=${summary.runState || '(none)'} scope=${summary.permissionScope || '(none)'}`,
			`Lifecycle: attempt=${summary.currentAttemptNumber ?? '(none)'} plan=${summary.currentPlanVersion ?? '(none)'} review=${summary.latestReviewVerdict || '(none)'} decision=${summary.latestGovernorDecision || '(none)'}`,
			`Auto-step: ${summary.autoStep?.mode || 'off'} (${summary.autoStep?.appliedCount ?? 0} applied)`,
			`Actions: ${summary.actions.length ? summary.actions.join(', ') : '(none)'}`,
			summary.isolationError
				? `Isolation error: ${summary.isolationError}`
				: 'Isolation error: none',
			summary.writeError ? `Write error: ${summary.writeError}` : 'Write error: none',
			summary.processError ? `Process error: ${summary.processError}` : 'Process error: none',
			summary.logErrors.length
				? `Log errors:\n${summary.logErrors.join('\n')}`
				: 'Log errors: none',
		].join('\n') + '\n'
	);
}

process.exitCode = summary.ok ? 0 : 1;
