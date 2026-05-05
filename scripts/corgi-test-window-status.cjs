#!/usr/bin/env node

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const testRoot = path.join(root, '.agent', 'test-window');
const userDataDir = path.join(testRoot, 'vscode-profile', 'user-data');
const legacyUserDataDir = path.join(root, '.agent', 'vscode-governor-first-test-user-data');
const snapshotPath = path.join(
	testRoot,
	'runtime-agent',
	'orchestration',
	'corgi_webview_snapshot.json'
);
const stderrPath = path.join(testRoot, 'logs', 'vscode.stderr.log');

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

function processAlive() {
	return (
		commandSucceeds('pgrep', ['-f', userDataDir]) ||
		commandSucceeds('pgrep', ['-f', legacyUserDataDir])
	);
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

function summarize() {
	const snapshot = readJson(snapshotPath);
	const payload = snapshot?.payload || {};
	const state = payload.state || {};
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

	return {
		ok:
			Boolean(snapshot) &&
			logErrors.length === 0 &&
			!feedHasError &&
			!knownBlockingError &&
			!stale,
		snapshot: snapshot ? 'present' : 'missing',
		processAlive: processAlive(),
		recordedAt: snapshot?.recordedAt || null,
		ageMs: ageMs ?? null,
		goalStrip: payload.goalStrip || payload.header || '',
		stage: state.currentStage || '',
		actor: state.currentActor || '',
		runState: state.runState || '',
		permissionScope: state.permissionScope || '',
		autoStep: payload.autoStep || null,
		actions: actions.map((action) => action.text).filter(Boolean),
		composer: payload.composer || null,
		messages: messages.map((message) => message.text).filter(Boolean).slice(-6),
		progress: progress.map((item) => item.text).filter(Boolean).slice(-6),
		logErrors,
		feedHasError,
		knownBlockingError,
		stale,
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
			`Process: ${summary.processAlive ? 'live' : 'not running'}`,
			`Goal: ${summary.goalStrip || '(none)'}`,
			`State: actor=${summary.actor || '(none)'} stage=${summary.stage || '(none)'} run=${summary.runState || '(none)'} scope=${summary.permissionScope || '(none)'}`,
			`Auto-step: ${summary.autoStep?.mode || 'off'} (${summary.autoStep?.appliedCount ?? 0} applied)`,
			`Actions: ${summary.actions.length ? summary.actions.join(', ') : '(none)'}`,
			summary.logErrors.length
				? `Log errors:\n${summary.logErrors.join('\n')}`
				: 'Log errors: none',
		].join('\n') + '\n'
	);
}

process.exitCode = summary.ok ? 0 : 1;
