#!/usr/bin/env node

const { spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const autoRunner = path.join(repoRoot, 'scripts', 'run-corgi-test-window-auto.sh');
const statusScript = path.join(repoRoot, 'scripts', 'corgi-test-window-status.cjs');
const defaultTestRoot = path.join(os.homedir(), '.corgi', 'test-window', 'extension-ext');

const demoStages = [
	{
		id: 'species-filter-review-retry',
		title: 'Add species filter with Reviewer-requested retry',
		promptPreset: 'pet-life-diary-filter-review-retry',
		workspaceMode: 'scratch',
		autoSteps: 'execute',
		minAttempt: 2,
		expectedDecision: 'accept',
		purpose:
			'Proves Corgi can keep one Pet Life Diary work family through an incomplete Executor attempt, Reviewer feedback, Governor replan, retry, and final acceptance.',
	},
];

function parseArgs(argv) {
	const args = {
		printPlan: false,
		stage: undefined,
		timeoutSeconds: Number(process.env.CORGI_DEMO_TIMEOUT_SECONDS || 300),
		reportDir: undefined,
	};
	for (let index = 0; index < argv.length; index += 1) {
		const value = argv[index];
		switch (value) {
			case '--print-plan':
				args.printPlan = true;
				break;
			case '--stage':
				args.stage = argv[index + 1];
				index += 1;
				break;
			case '--timeout':
				args.timeoutSeconds = Number(argv[index + 1]);
				index += 1;
				break;
			case '--report-dir':
				args.reportDir = argv[index + 1];
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
	if (!Number.isFinite(args.timeoutSeconds) || args.timeoutSeconds <= 0) {
		throw new Error('--timeout must be a positive number of seconds');
	}
	return args;
}

function printUsage() {
	process.stdout.write(
		[
			'Usage: node scripts/run-corgi-pet-diary-demo.cjs [--print-plan] [--stage id] [--timeout seconds] [--report-dir path]',
			'',
			'Runs an isolated Corgi test-window demo for the Pet Life Diary project and writes a demo report.',
		].join('\n') + '\n'
	);
}

function runJson(command, args, options = {}) {
	const result = spawnSync(command, args, {
		cwd: repoRoot,
		env: options.env || process.env,
		encoding: 'utf8',
		maxBuffer: 1024 * 1024 * 20,
	});
	if (result.status !== 0) {
		throw new Error(result.stderr || result.stdout || `${command} ${args.join(' ')} failed`);
	}
	return JSON.parse(result.stdout);
}

function readJson(filePath) {
	if (!filePath || !fs.existsSync(filePath)) {
		return undefined;
	}
	return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function compact(value, limit = 240) {
	return String(value || '')
		.replace(/\s+/g, ' ')
		.trim()
		.slice(0, limit);
}

function runStage(stage, args) {
	const env = {
		...process.env,
		CORGI_TEST_WINDOW_WORKSPACE_MODE: stage.workspaceMode,
		CORGI_TEST_WINDOW_PROMPT_PRESET: stage.promptPreset,
		CORGI_TEST_WINDOW_AUTO_STEPS: stage.autoSteps,
		CORGI_TEST_WINDOW_MONITOR_TIMEOUT_SECONDS: String(args.timeoutSeconds),
	};
	const result = spawnSync('bash', [autoRunner], {
		cwd: repoRoot,
		env,
		stdio: 'inherit',
	});
	if (result.status !== 0) {
		throw new Error(`Demo stage ${stage.id} failed with exit code ${result.status}`);
	}

	const status = runJson(process.execPath, [statusScript, '--json'], { env });
	const currentRun = readJson(
		path.join(env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot, 'current-run.json')
	);
	const snapshot = readJson(currentRun?.snapshotPath);
	validateStageResult(stage, status);
	const workspaceFiles = inspectWorkspace(currentRun?.workspaceRoot);
	assertWorkspaceFiles(stage, workspaceFiles);

	return {
		...stage,
		status,
		currentRun,
		snapshot,
		workspaceFiles,
	};
}

function validateStageResult(stage, status) {
	if (!status.ok) {
		throw new Error(`Demo stage ${stage.id} ended unhealthy`);
	}
	if (status.stage !== 'governor_decision_recorded') {
		throw new Error(`Demo stage ${stage.id} ended at ${status.stage || '(none)'}`);
	}
	if (Number(status.currentAttemptNumber || 0) < stage.minAttempt) {
		throw new Error(
			`Demo stage ${stage.id} did not prove retry attempt ${stage.minAttempt}`
		);
	}
	if (status.latestGovernorDecision !== stage.expectedDecision) {
		throw new Error(
			`Demo stage ${stage.id} decision was ${status.latestGovernorDecision || '(none)'}`
		);
	}
}

function assertWorkspaceFiles(stage, files) {
	const missing = files.filter((file) => !file.exists);
	if (missing.length > 0) {
		throw new Error(
			`Demo stage ${stage.id} accepted without required project files: ${missing
				.map((file) => file.path)
				.join(', ')}`
		);
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

function writeReports(results, args) {
	const testRoot = process.env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot;
	const reportDir = path.resolve(args.reportDir || path.join(testRoot, 'demo-reports'));
	fs.mkdirSync(reportDir, { recursive: true });
	const generatedAt = new Date().toISOString();
	const report = {
		schemaVersion: 1,
		generatedAt,
		title: 'Corgi Pet Life Diary Demo',
		sourceRoot: repoRoot,
		stages: results.map((result) => ({
			id: result.id,
			title: result.title,
			promptPreset: result.promptPreset,
			workspaceRoot: result.currentRun?.workspaceRoot || null,
			agentRoot: result.currentRun?.agentRoot || null,
			goalStrip: result.status.goalStrip,
			stage: result.status.stage,
			attempt: result.status.currentAttemptNumber,
			planVersion: result.status.currentPlanVersion,
			reviewVerdict: result.status.latestReviewVerdict,
			governorDecision: result.status.latestGovernorDecision,
			workspaceFiles: result.workspaceFiles,
			artifacts: artifactSummary(result.snapshot),
		})),
	};
	const jsonPath = path.join(reportDir, 'latest-pet-life-diary-demo.json');
	const markdownPath = path.join(reportDir, 'latest-pet-life-diary-demo.md');
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
		'',
		'## Stages',
		'',
	];
	for (const stage of report.stages) {
		lines.push(`### ${stage.title}`);
		lines.push('');
		lines.push(`- Prompt preset: \`${stage.promptPreset}\``);
		lines.push(`- Workspace: \`${stage.workspaceRoot}\``);
		lines.push(`- Agent root: \`${stage.agentRoot}\``);
		lines.push(`- Goal strip: ${stage.goalStrip}`);
		lines.push(`- Final stage: \`${stage.stage}\``);
		lines.push(`- Attempt: ${stage.attempt}`);
		lines.push(`- Plan version: ${stage.planVersion}`);
		lines.push(`- Review verdict: \`${stage.reviewVerdict}\``);
		lines.push(`- Governor decision: \`${stage.governorDecision}\``);
		lines.push('');
		lines.push('Project files:');
		for (const file of stage.workspaceFiles) {
			lines.push(`- ${file.exists ? 'present' : 'missing'} \`${file.path}\` (${file.size} bytes)`);
		}
		lines.push('');
		lines.push('Key artifacts:');
		for (const artifact of stage.artifacts) {
			lines.push(
				`- \`${artifact.label}\` ${compact(artifact.status, 80)}: \`${artifact.path}\``
			);
		}
		lines.push('');
	}
	return lines.join('\n') + '\n';
}

function main() {
	const args = parseArgs(process.argv.slice(2));
	const stages = args.stage
		? demoStages.filter((stage) => stage.id === args.stage)
		: demoStages;
	if (!stages.length) {
		throw new Error(`Unknown demo stage: ${args.stage}`);
	}
	if (args.printPlan) {
		process.stdout.write(
			JSON.stringify(
				{
					stages: demoStages,
					defaultReportDir: path.join(
						process.env.CORGI_TEST_WINDOW_ROOT || defaultTestRoot,
						'demo-reports'
					),
				},
				null,
				2
			) + '\n'
		);
		return;
	}
	const results = stages.map((stage) => runStage(stage, args));
	const { jsonPath, markdownPath } = writeReports(results, args);
	process.stdout.write(`Corgi Pet Life Diary demo complete.\n`);
	process.stdout.write(`Report: ${markdownPath}\n`);
	process.stdout.write(`JSON:   ${jsonPath}\n`);
}

try {
	main();
} catch (error) {
	const message = error instanceof Error ? error.message : String(error);
	process.stderr.write(`${message}\n`);
	process.exit(1);
}
