#!/usr/bin/env node

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const launchScript = path.join(repoRoot, 'scripts', 'launch-corgi-test-window.sh');
const closeScript = path.join(repoRoot, 'scripts', 'close-corgi-test-window.sh');
const statusScript = path.join(repoRoot, 'scripts', 'corgi-test-window-status.cjs');
const promptScript = path.join(repoRoot, 'scripts', 'corgi-test-prompt.cjs');
const defaultTestRoot = path.join(os.homedir(), '.corgi', 'test-window', 'extension-ext');

const defaultGoal = {
	id: 'app-store-pet-diary-demo',
	promptPreset: 'pet-life-diary-app-store-demo',
	workspaceMode: 'scratch',
	scratchId: 'pet-life-diary-live-demo',
	autoSteps: 'execute',
	expectedStage: 'governor_decision_recorded',
	expectedDecision: 'accept',
	description:
		'Give Corgi one product-style goal, let it plan and build a polished Pet Life Diary scratch project, and keep the test window open for inspection.',
};

function parseArgs(argv) {
	const args = {
		printPlan: false,
		timeoutSeconds: Number(process.env.CORGI_LIVE_GOAL_TIMEOUT_SECONDS || 300),
		reportDir: undefined,
		closeOnSuccess: false,
		keepOpenOnFailure: false,
	};
	for (let index = 0; index < argv.length; index += 1) {
		const value = argv[index];
		switch (value) {
			case '--print-plan':
				args.printPlan = true;
				break;
			case '--timeout':
				args.timeoutSeconds = Number(argv[index + 1]);
				index += 1;
				break;
			case '--report-dir':
				args.reportDir = argv[index + 1];
				index += 1;
				break;
			case '--close-on-success':
				args.closeOnSuccess = true;
				break;
			case '--keep-open-on-failure':
				args.keepOpenOnFailure = true;
				break;
			case '--help':
				printUsage();
				process.exit(0);
				break;
			default:
				throw new Error(`Unknown argument: ${value}`);
		}
	}
	if (!Number.isFinite(args.timeoutSeconds) || args.timeoutSeconds <= 0) {
		throw new Error('--timeout must be a positive number of seconds');
	}
	return args;
}

function printUsage() {
	process.stdout.write(
		[
			'Usage: node scripts/run-corgi-live-goal-demo.cjs [--print-plan] [--timeout seconds] [--report-dir path] [--close-on-success] [--keep-open-on-failure]',
			'',
			'Launches an isolated Corgi scratch workspace, auto-submits the live goal demo, monitors it, and keeps the VS Code test window open on success by default.',
		].join('\n') + '\n'
	);
}

function promptText(preset) {
	const result = spawnSync(process.execPath, [promptScript, 'get', preset], {
		cwd: repoRoot,
		encoding: 'utf8',
		maxBuffer: 1024 * 1024,
	});
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || `Prompt preset not found: ${preset}`);
	}
	return result.stdout.trim();
}

function readJson(filePath) {
	if (!filePath || !fs.existsSync(filePath)) {
		return undefined;
	}
	return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function runStatus(env) {
	const result = spawnSync(process.execPath, [statusScript, '--json'], {
		cwd: repoRoot,
		env,
		encoding: 'utf8',
		maxBuffer: 1024 * 1024 * 10,
	});
	if (result.stdout.trim()) {
		return JSON.parse(result.stdout);
	}
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || 'Unable to read Corgi test-window status');
	}
	throw new Error('Corgi test-window status returned no JSON');
}

function closeWindow(env) {
	spawnSync('bash', [closeScript], {
		cwd: repoRoot,
		env,
		stdio: 'ignore',
	});
}

function launchWindow(env) {
	const result = spawnSync('bash', [launchScript], {
		cwd: repoRoot,
		env,
		stdio: 'inherit',
	});
	if (result.status !== 0) {
		throw new Error(`Corgi live goal window launch failed with exit code ${result.status}`);
	}
}

function monitorGoal(env, args) {
	const deadline = Date.now() + args.timeoutSeconds * 1000;
	const snapshotGraceMs = Number(process.env.CORGI_TEST_WINDOW_SNAPSHOT_GRACE_SECONDS || 30) * 1000;
	const startedAt = Date.now();
	let lastStatus;
	while (Date.now() < deadline) {
		const status = runStatus(env);
		lastStatus = status;
		process.stdout.write(JSON.stringify(status, null, 2) + '\n');
		if (status.snapshot === 'missing' && Date.now() - startedAt < snapshotGraceMs) {
			sleep(2000);
			continue;
		}
		if (!status.ok) {
			throw new Error(
				`Corgi live goal reported an unhealthy state: ${status.processError || status.isolationError || status.writeError || 'unknown'}`
			);
		}
		if (/^(executor_blocked|reviewer_blocked)$/.test(status.stage || '')) {
			throw new Error(`Corgi live goal reached blocker stage: ${status.stage}`);
		}
		if (status.stage === defaultGoal.expectedStage) {
			if (status.latestGovernorDecision !== defaultGoal.expectedDecision) {
				throw new Error(
					`Corgi live goal ended with decision ${status.latestGovernorDecision || '(none)'}`
				);
			}
			return status;
		}
		if (!status.processAlive) {
			throw new Error('Corgi live goal window exited before final acceptance');
		}
		sleep(5000);
	}
	throw new Error(
		`Timed out waiting for Corgi live goal to finish. Last stage: ${lastStatus?.stage || '(none)'}`
	);
}

function sleep(ms) {
	const end = Date.now() + ms;
	while (Date.now() < end) {
		Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, Math.min(100, end - Date.now()));
	}
}

function inspectWorkspace(workspaceRoot) {
	const refs = ['README.md', 'index.html', 'src/app.js', 'src/styles.css', 'data/sample-pets.json'];
	return refs.map((relPath) => {
		const filePath = workspaceRoot ? path.join(workspaceRoot, relPath) : '';
		const exists = Boolean(filePath && fs.existsSync(filePath));
		const stat = exists ? fs.statSync(filePath) : undefined;
		return {
			path: relPath,
			exists,
			size: stat?.size || 0,
		};
	});
}

function qualityChecks(workspaceRoot) {
	const read = (relPath) => {
		const filePath = workspaceRoot ? path.join(workspaceRoot, relPath) : '';
		return filePath && fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : '';
	};
	const readme = read('README.md');
	const html = read('index.html');
	const app = read('src/app.js');
	const styles = read('src/styles.css');
	return [
		{
			label: 'README explains the demo',
			pass: /App Store-style|product showcase|Corgi dispatch/i.test(readme),
		},
		{
			label: 'HTML contains the app shell',
			pass: /Pet Life Diary/.test(html) && /phone-preview/.test(html),
		},
		{
			label: 'App script contains lightweight interaction',
			pass: /filterButtons/.test(app) && /renderPets/.test(app),
		},
		{
			label: 'Styles contain responsive showcase treatment',
			pass: /phone-preview/.test(styles) && /@media/.test(styles),
		},
	];
}

function assertWorkspaceFiles(files) {
	const missing = files.filter((file) => !file.exists);
	if (missing.length > 0) {
		throw new Error(
			`Corgi live goal accepted without required project files: ${missing
				.map((file) => file.path)
				.join(', ')}`
		);
	}
}

function assertQualityChecks(checks) {
	const failed = checks.filter((check) => !check.pass);
	if (failed.length > 0) {
		throw new Error(
			`Corgi live goal accepted with failed quality checks: ${failed
				.map((check) => check.label)
				.join(', ')}`
		);
	}
}

function artifactSummary(snapshot) {
	const artifacts = snapshot?.payload?.model?.snapshot?.recentArtifacts;
	if (!Array.isArray(artifacts)) {
		return [];
	}
	return artifacts
		.filter((artifact) =>
			['governor_decision.json', 'review.json', 'request.json', 'result.json'].includes(
				artifact.label
			)
		)
		.slice(0, 8)
		.map((artifact) => ({
			label: artifact.label,
			status: artifact.status,
			path: artifact.path,
		}));
}

function writeReport(env, status, args) {
	const testRoot = env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot;
	const currentRun = readJson(path.join(testRoot, 'current-run.json'));
	const snapshot = readJson(currentRun?.snapshotPath);
	const reportDir = path.resolve(args.reportDir || path.join(testRoot, 'demo-reports'));
	fs.mkdirSync(reportDir, { recursive: true });
	const report = {
		schemaVersion: 1,
		generatedAt: new Date().toISOString(),
		title: 'Corgi Live Goal Demo',
		goal: defaultGoal,
		prompt: promptText(defaultGoal.promptPreset),
		sourceRoot: repoRoot,
		workspaceRoot: currentRun?.workspaceRoot || null,
		agentRoot: currentRun?.agentRoot || null,
		status,
		workspaceFiles: inspectWorkspace(currentRun?.workspaceRoot),
		qualityChecks: qualityChecks(currentRun?.workspaceRoot),
		artifacts: artifactSummary(snapshot),
		windowLeftOpen: !args.closeOnSuccess,
	};
	const jsonPath = path.join(reportDir, 'latest-live-goal-demo.json');
	const markdownPath = path.join(reportDir, 'latest-live-goal-demo.md');
	fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2) + '\n', 'utf8');
	fs.writeFileSync(markdownPath, markdownReport(report), 'utf8');
	return { jsonPath, markdownPath, report };
}

function markdownReport(report) {
	const lines = [
		`# ${report.title}`,
		'',
		`Generated: ${report.generatedAt}`,
		`Source extension: \`${report.sourceRoot}\``,
		`Workspace: \`${report.workspaceRoot}\``,
		`Agent root: \`${report.agentRoot}\``,
		`Window left open: ${report.windowLeftOpen ? 'yes' : 'no'}`,
		'',
		'## Goal',
		'',
		report.prompt,
		'',
		'## Final State',
		'',
		`- Goal strip: ${report.status.goalStrip}`,
		`- Stage: \`${report.status.stage}\``,
		`- Review verdict: \`${report.status.latestReviewVerdict}\``,
		`- Governor decision: \`${report.status.latestGovernorDecision}\``,
		'',
		'## Project Files',
		'',
	];
	for (const file of report.workspaceFiles) {
		lines.push(`- ${file.exists ? 'present' : 'missing'} \`${file.path}\` (${file.size} bytes)`);
	}
	lines.push('', '## Quality Checks', '');
	for (const check of report.qualityChecks) {
		lines.push(`- ${check.pass ? 'pass' : 'fail'} ${check.label}`);
	}
	lines.push('', '## Key Artifacts', '');
	for (const artifact of report.artifacts) {
		lines.push(`- \`${artifact.label}\` ${artifact.status}: \`${artifact.path}\``);
	}
	return lines.join('\n') + '\n';
}

function plan(args) {
	return {
		goal: defaultGoal,
		prompt: promptText(defaultGoal.promptPreset),
		monitorTimeoutSeconds: args.timeoutSeconds,
		defaultReportDir: path.join(
			process.env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot,
			'demo-reports'
		),
		successBehavior: args.closeOnSuccess
			? 'close the test window after final acceptance'
			: 'keep the test window open after final acceptance',
	};
}

function main() {
	const args = parseArgs(process.argv.slice(2));
	if (args.printPlan) {
		process.stdout.write(JSON.stringify(plan(args), null, 2) + '\n');
		return;
	}

	const env = {
		...process.env,
		CORGI_TEST_WINDOW_WORKSPACE_MODE: defaultGoal.workspaceMode,
		CORGI_TEST_WINDOW_SCRATCH_ID: defaultGoal.scratchId,
		CORGI_TEST_WINDOW_PROMPT_PRESET: defaultGoal.promptPreset,
		CORGI_TEST_WINDOW_AUTO_STEPS: defaultGoal.autoSteps,
	};

		try {
			launchWindow(env);
			const finalStatus = monitorGoal(env, args);
			const currentRun = readJson(
				path.join(env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot, 'current-run.json')
			);
			const workspaceFiles = inspectWorkspace(currentRun?.workspaceRoot);
			const checks = qualityChecks(currentRun?.workspaceRoot);
			assertWorkspaceFiles(workspaceFiles);
			assertQualityChecks(checks);
			const { markdownPath, jsonPath } = writeReport(env, finalStatus, args);
			if (args.closeOnSuccess) {
				closeWindow(env);
		}
		process.stdout.write('Corgi live goal demo reached final acceptance.\n');
		process.stdout.write(`Report: ${markdownPath}\n`);
		process.stdout.write(`JSON:   ${jsonPath}\n`);
		process.stdout.write(
			args.closeOnSuccess
				? 'The test window was closed because --close-on-success was set.\n'
				: 'The test window is still open for inspection.\n'
		);
	} catch (error) {
		if (!args.keepOpenOnFailure) {
			closeWindow(env);
		}
		throw error;
	}
}

try {
	main();
} catch (error) {
	const message = error instanceof Error ? error.message : String(error);
	process.stderr.write(`${message}\n`);
	process.exit(1);
}
