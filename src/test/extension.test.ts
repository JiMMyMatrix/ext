import * as assert from 'assert';
import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vm from 'vm';
import * as vscode from 'vscode';
import {
	applyModelAction,
	createInitialModel,
	type ExecutionWindowModel,
	getArtifactById,
} from '../phase1Model';
import {
	EXECUTION_WINDOW_CONTAINER_ID,
	EXECUTION_WINDOW_VIEW_ID,
	getExecutionWindowHtml,
	OPEN_EXECUTION_WINDOW_COMMAND_ID,
} from '../executionWindowPanel';
import {
	buildRuntimeErgonomicsKernel,
	runtimeVisibilityForFeedItem,
	summaryForActivity,
} from '../runtimeErgonomicsKernel';
import {
	ADVISORY_CAPABILITIES_PATH,
	ADVISORY_DOC_PATH,
	ADVISORY_MCP_LAUNCHER_PATH,
	ADVISORY_MCP_REQUIREMENTS_PATH,
	ADVISORY_MCP_SERVER_PATH,
	ADVISORY_MCP_SETUP_PATH,
	CODEX_APP_SERVER_CLIENT_TS_PATH,
	DEVELOPMENT_CONSULTING_MCP_LAUNCHER_PATH,
	DEVELOPMENT_SESSION_TS_PATH,
	DEV_MCP_SERVER_ENTRYPOINT_PATH,
	EXECUTION_TRANSPORT_TS_PATH,
	EXECUTION_WINDOW_CLIENT_SCRIPT_TS_PATH,
	EXECUTION_WINDOW_PANEL_TS_PATH,
	EXECUTION_WINDOW_RENDERER_TS_PATH,
	EXECUTION_WINDOW_STYLES_TS_PATH,
	EXTENSION_TS_PATH,
	GOVERNOR_RUNTIME_CONFIG_PATH,
	GOVERNOR_RUNTIME_TS_PATH,
	LAUNCH_JSON_PATH,
	LIVE_GOAL_DEMO_DRIVER_PATH,
	MCP_SERVER_ENTRYPOINT_PATH,
	PACKAGE_JSON_PATH,
	PET_DIARY_DEMO_DRIVER_PATH,
	PROCESS_REPLAN_HELPER_PATH,
	PROCESS_SCRATCH_RETRY_HELPER_PATH,
	PROCESS_TEST_SCRIPT_PATH,
	REPO_ROOT,
	RUNTIME_ERGONOMICS_KERNEL_TS_PATH,
	TEST_WINDOW_AUTO_SCRIPT_PATH,
	TEST_WINDOW_CLOSE_SCRIPT_PATH,
	TEST_WINDOW_PROMPT_CATALOG_PATH,
	TEST_WINDOW_PROMPT_SCRIPT_PATH,
	TEST_WINDOW_SCRIPT_PATH,
	TEST_WINDOW_STATUS_SCRIPT_PATH,
	UX_CONTRACT_PATH,
} from './testPaths';
import { renderWebviewSnapshot } from './webviewHarness';

function loadPackageJson(): Record<string, unknown> {
	return JSON.parse(fs.readFileSync(PACKAGE_JSON_PATH, 'utf8')) as Record<string, unknown>;
}

function readExecutionWindowSource(): string {
	return [
		fs.readFileSync(EXECUTION_WINDOW_PANEL_TS_PATH, 'utf8'),
		fs.readFileSync(EXECUTION_WINDOW_RENDERER_TS_PATH, 'utf8'),
		fs.readFileSync(EXECUTION_WINDOW_CLIENT_SCRIPT_TS_PATH, 'utf8'),
		fs.readFileSync(EXECUTION_WINDOW_STYLES_TS_PATH, 'utf8'),
	].join('\n');
}

suite('Corgi Webview UX', () => {
	test('ships sidebar webview contributions and a focused open command without chat participants', () => {
		const manifest = loadPackageJson();
		const contributes = manifest.contributes as Record<string, unknown>;
		const activationEvents = manifest.activationEvents as string[];
		const viewsContainers = contributes.viewsContainers as Record<string, unknown>;
		const views = contributes.views as Record<string, unknown>;
		const commands = contributes.commands as Array<Record<string, unknown>>;

		assert.ok(Array.isArray(activationEvents));
		assert.ok(viewsContainers.activitybar);
		assert.ok(views[EXECUTION_WINDOW_CONTAINER_ID]);
		assert.strictEqual(contributes.chatParticipants, undefined);
		assert.ok(commands.some((command) => command.command === OPEN_EXECUTION_WINDOW_COMMAND_ID));
		assert.ok(activationEvents.includes('onStartupFinished'));
		assert.ok(activationEvents.includes(`onCommand:${OPEN_EXECUTION_WINDOW_COMMAND_ID}`));
		assert.ok(!activationEvents.some((event) => event.startsWith('onChatParticipant:')));
	});

	test('opens the Corgi sidebar view without throwing', async () => {
		await assert.doesNotReject(async () => {
			await vscode.commands.executeCommand(OPEN_EXECUTION_WINDOW_COMMAND_ID);
		});
	});

	test('webview inline script is valid JavaScript', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
		const scriptMatch = html.match(/<script nonce="[^"]+">([\s\S]*?)<\/script>/);

		assert.ok(scriptMatch, 'Expected the generated webview HTML to contain an inline script.');
		assert.doesNotThrow(() => new vm.Script(scriptMatch?.[1] ?? ''));
	});

	test('debug launch opens the current repo as the workspace', () => {
		const launchJson = fs.readFileSync(LAUNCH_JSON_PATH, 'utf8');

		assert.match(
			launchJson,
			/"args"\s*:\s*\[\s*"--extensionDevelopmentPath=\$\{workspaceFolder\}"\s*,\s*"\$\{workspaceFolder\}"/s
		);
	});

	test('test-window launcher refuses roots inside the development repo', () => {
		const forbiddenRoot = path.join(REPO_ROOT, '.agent', 'forbidden-test-window-root');
		fs.rmSync(forbiddenRoot, { recursive: true, force: true });
		const result = spawnSync('bash', [TEST_WINDOW_SCRIPT_PATH], {
			cwd: REPO_ROOT,
			encoding: 'utf8',
			env: {
				...process.env,
				CORGI_TEST_WINDOW_AUTO_PROMPT: '',
				CORGI_TEST_WINDOW_ROOT: forbiddenRoot,
				CORGI_TEST_WINDOW_WORKSPACE_MODE: 'empty',
			},
		});
		fs.rmSync(forbiddenRoot, { recursive: true, force: true });

		assert.strictEqual(result.status, 2);
		assert.match(
			result.stderr,
			/Refusing to keep Corgi test-window state inside the development repo/
		);
		assert.doesNotMatch(result.stdout + result.stderr, /Launched Corgi test window/);
	});

	test('test-window status reports development-workspace isolation failures', () => {
		const testRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-status-isolation-'));
		try {
			fs.writeFileSync(
				path.join(testRoot, 'current-run.json'),
				JSON.stringify(
					{
						workspaceMode: 'repo',
						workspaceRoot: REPO_ROOT,
						sourceRoot: REPO_ROOT,
						agentRoot: path.join(REPO_ROOT, '.agent'),
						userDataDir: path.join(testRoot, 'profile'),
						stderrPath: path.join(testRoot, 'stderr.log'),
					},
					null,
					2
				) + '\n'
			);
			const result = spawnSync('node', [TEST_WINDOW_STATUS_SCRIPT_PATH, '--json'], {
				cwd: REPO_ROOT,
				encoding: 'utf8',
				env: {
					...process.env,
					CORGI_TEST_WINDOW_ROOT: testRoot,
				},
			});

			assert.strictEqual(result.status, 1);
			const status = JSON.parse(result.stdout) as { isolationError?: string; ok?: boolean };
			assert.strictEqual(status.ok, false);
			assert.match(
				status.isolationError ?? '',
				/development repo|development \.agent|outside/
			);
		} finally {
			fs.rmSync(testRoot, { recursive: true, force: true });
		}
	});

	test('test-window status reports workspace writeability failures', () => {
		const testRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-status-write-'));
		const workspaceRoot = path.join(testRoot, 'empty-workspaces', 'write-blocked');
		const agentRoot = path.join(testRoot, 'empty-agent');
		const snapshotPath = path.join(agentRoot, 'orchestration', 'corgi_webview_snapshot.json');
		try {
			fs.mkdirSync(workspaceRoot, { recursive: true });
			fs.mkdirSync(path.dirname(snapshotPath), { recursive: true });
			fs.writeFileSync(
				snapshotPath,
				JSON.stringify({
					recordedAt: new Date().toISOString(),
					payload: {
						state: { runState: 'idle', currentStage: 'idle' },
						messages: [],
						progress: [],
						actions: [],
					},
				})
			);
			fs.writeFileSync(
				path.join(testRoot, 'current-run.json'),
				JSON.stringify(
					{
						workspaceMode: 'empty',
						workspaceRoot,
						sourceRoot: REPO_ROOT,
						agentRoot,
						snapshotPath,
						userDataDir: path.join(testRoot, 'profile'),
						stderrPath: path.join(testRoot, 'stderr.log'),
					},
					null,
					2
				) + '\n'
			);
			fs.chmodSync(workspaceRoot, 0o555);
			const result = spawnSync('node', [TEST_WINDOW_STATUS_SCRIPT_PATH, '--json'], {
				cwd: REPO_ROOT,
				encoding: 'utf8',
				env: {
					...process.env,
					CORGI_TEST_WINDOW_ROOT: testRoot,
				},
			});

			assert.strictEqual(result.status, 1);
			const status = JSON.parse(result.stdout) as { ok?: boolean; writeError?: string };
			assert.strictEqual(status.ok, false);
			assert.match(status.writeError ?? '', /Test workspace is not writable/);
		} finally {
			try {
				fs.chmodSync(workspaceRoot, 0o755);
			} catch {
				// The directory may not exist if setup failed early.
			}
			fs.rmSync(testRoot, { recursive: true, force: true });
		}
	});

	test('test-window status requires the current test profile process', () => {
		const testRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-status-dead-'));
		const workspaceRoot = path.join(testRoot, 'empty-workspaces', 'dead-window');
		const agentRoot = path.join(testRoot, 'empty-agent');
		const snapshotPath = path.join(agentRoot, 'orchestration', 'corgi_webview_snapshot.json');
		try {
			fs.mkdirSync(workspaceRoot, { recursive: true });
			fs.mkdirSync(path.dirname(snapshotPath), { recursive: true });
			fs.writeFileSync(
				snapshotPath,
				JSON.stringify({
					recordedAt: new Date().toISOString(),
					payload: {
						state: { runState: 'idle', currentStage: 'idle' },
						messages: [],
						progress: [],
						actions: [],
					},
				})
			);
			fs.writeFileSync(
				path.join(testRoot, 'current-run.json'),
				JSON.stringify(
					{
						workspaceMode: 'empty',
						workspaceRoot,
						sourceRoot: REPO_ROOT,
						agentRoot,
						snapshotPath,
						userDataDir: path.join(testRoot, 'definitely-not-running-profile'),
						stderrPath: path.join(testRoot, 'stderr.log'),
					},
					null,
					2
				) + '\n'
			);
			const result = spawnSync('node', [TEST_WINDOW_STATUS_SCRIPT_PATH, '--json'], {
				cwd: REPO_ROOT,
				encoding: 'utf8',
				env: {
					...process.env,
					CORGI_TEST_WINDOW_ROOT: testRoot,
				},
			});

			assert.strictEqual(result.status, 1);
			const status = JSON.parse(result.stdout) as {
				ok?: boolean;
				processAlive?: boolean;
				processError?: string;
			};
			assert.strictEqual(status.ok, false);
			assert.strictEqual(status.processAlive, false);
			assert.match(status.processError ?? '', /Current Corgi test window process is not running/);
		} finally {
			fs.rmSync(testRoot, { recursive: true, force: true });
		}
	});

	test('test-window status accepts a completed final snapshot after the window closes', () => {
		const testRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-status-complete-'));
		const workspaceRoot = path.join(testRoot, 'scratch-workspaces', 'finished-window');
		const agentRoot = path.join(workspaceRoot, '.agent');
		const snapshotPath = path.join(agentRoot, 'orchestration', 'corgi_webview_snapshot.json');
		try {
			fs.mkdirSync(workspaceRoot, { recursive: true });
			fs.mkdirSync(path.dirname(snapshotPath), { recursive: true });
			fs.writeFileSync(
				snapshotPath,
				JSON.stringify({
					recordedAt: new Date().toISOString(),
					payload: {
						state: {
							runState: 'idle',
							currentStage: 'governor_decision_recorded',
						},
						messages: [{ text: 'Final decision recorded' }],
						progress: [],
						actions: [],
						autoStep: { mode: 'execute', appliedCount: 3 },
					},
				})
			);
			fs.writeFileSync(
				path.join(testRoot, 'current-run.json'),
				JSON.stringify(
					{
						workspaceMode: 'scratch',
						workspaceRoot,
						sourceRoot: REPO_ROOT,
						agentRoot,
						snapshotPath,
						userDataDir: path.join(testRoot, 'definitely-not-running-profile'),
						stderrPath: path.join(testRoot, 'stderr.log'),
					},
					null,
					2
				) + '\n'
			);
			const result = spawnSync('node', [TEST_WINDOW_STATUS_SCRIPT_PATH, '--json'], {
				cwd: REPO_ROOT,
				encoding: 'utf8',
				env: {
					...process.env,
					CORGI_TEST_WINDOW_ROOT: testRoot,
				},
			});

			assert.strictEqual(result.status, 0);
			const status = JSON.parse(result.stdout) as {
				ok?: boolean;
				processAlive?: boolean;
				processError?: string;
				lastRunCompleted?: boolean;
			};
			assert.strictEqual(status.ok, true);
			assert.strictEqual(status.processAlive, false);
			assert.strictEqual(status.lastRunCompleted, true);
			assert.strictEqual(status.processError, '');
		} finally {
			fs.rmSync(testRoot, { recursive: true, force: true });
		}
	});

	test('development resets no longer depend on launch env flags', () => {
		const extensionSource = fs.readFileSync(EXTENSION_TS_PATH, 'utf8');
		const developmentSessionSource = fs.readFileSync(
			DEVELOPMENT_SESSION_TS_PATH,
			'utf8'
		);
		const webviewSource = readExecutionWindowSource();
		const launchScriptSource = fs.readFileSync(TEST_WINDOW_SCRIPT_PATH, 'utf8');
		const closeScriptSource = fs.readFileSync(TEST_WINDOW_CLOSE_SCRIPT_PATH, 'utf8');
		const autoScriptSource = fs.readFileSync(TEST_WINDOW_AUTO_SCRIPT_PATH, 'utf8');
		const petDiaryDemoDriverSource = fs.readFileSync(PET_DIARY_DEMO_DRIVER_PATH, 'utf8');
		const liveGoalDemoDriverSource = fs.readFileSync(LIVE_GOAL_DEMO_DRIVER_PATH, 'utf8');
		const promptCatalogSource = fs.readFileSync(TEST_WINDOW_PROMPT_CATALOG_PATH, 'utf8');
		const promptScriptSource = fs.readFileSync(TEST_WINDOW_PROMPT_SCRIPT_PATH, 'utf8');
		const statusScriptSource = fs.readFileSync(TEST_WINDOW_STATUS_SCRIPT_PATH, 'utf8');
		const processTestSource = fs.readFileSync(PROCESS_TEST_SCRIPT_PATH, 'utf8');
		const promptCatalog = JSON.parse(promptCatalogSource) as {
			defaultPromptId: string;
			prompts: Array<{
				id: string;
				prompt: string;
				category: string;
				requiresScenario: string;
				expectedFlow: string[];
				assertions: string[];
				tags: string[];
			}>;
		};
		const packageJson = loadPackageJson();
		const scripts = packageJson.scripts as Record<string, string>;

		assert.ok(
			developmentSessionSource.includes(
				'context.extensionMode === vscode.ExtensionMode.Development'
			)
		);
		assert.ok(developmentSessionSource.includes('CORGI_TEST_WINDOW_SCENARIO'));
		assert.ok(developmentSessionSource.includes('ui_session.json'));
		assert.ok(developmentSessionSource.includes('resolveExecutionTransportTarget'));
		assert.ok(extensionSource.includes('scheduleDevelopmentExecutionWindowOpen'));
		assert.ok(extensionSource.includes('void provider.openView().catch'));
		assert.ok(extensionSource.includes('resetDevelopmentSessionState(context);'));
		assert.ok(webviewSource.includes('didResetDevelopmentSessionState'));
		assert.ok(webviewSource.includes('resetDevelopmentSessionStateOnce'));
		assert.ok(webviewSource.includes('resetDevelopmentSessionState(this.context);'));
		assert.ok(webviewSource.includes('testWindowAutoPrompt'));
		assert.ok(webviewSource.includes('testWindowAutoStepMode'));
		assert.ok(webviewSource.includes('auto-submit test prompt'));
		assert.ok(webviewSource.includes('runTestWindowAutoStep'));
		assert.ok(webviewSource.includes('submitTestWindowClarificationAnswer'));
		assert.ok(webviewSource.includes('Keep the result polished, static, and isolated in the scratch workspace.'));
		assert.ok(webviewSource.includes('return context.extensionMode === vscode.ExtensionMode.Development;'));
		assert.ok(launchScriptSource.includes('seed_executor_test_session.py'));
		assert.ok(launchScriptSource.includes('seed_reviewer_test_session.py'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_SCENARIO'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_AUTO_PROMPT'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_AUTO_STEPS'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_PROMPT_PRESET'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_WORKSPACE_MODE'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_ROOT'));
		assert.ok(launchScriptSource.includes('.corgi/test-window/extension-ext'));
		assert.ok(launchScriptSource.includes('corgi-ui-test-workspace'));
		assert.ok(launchScriptSource.includes('THIS_IS_A_CORGI_TEST_WORKSPACE.md'));
		assert.ok(launchScriptSource.includes('Corgi Test Workspace.code-workspace'));
		assert.ok(launchScriptSource.includes("name: 'Corgi Test Workspace'"));
		assert.ok(launchScriptSource.includes('workspaceFile'));
		assert.ok(launchScriptSource.includes('assert_writable_dir "$WORKSPACE_ROOT" "workspace"'));
		assert.ok(launchScriptSource.includes('assert_writable_dir "$AGENT_ROOT" "agent root"'));
		assert.ok(launchScriptSource.includes('Refusing to keep Corgi test-window state inside the development repo'));
		assert.ok(launchScriptSource.includes('WORKSPACE_MODE="${CORGI_TEST_WINDOW_WORKSPACE_MODE:-scratch}"'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_EMPTY_ID'));
		assert.ok(launchScriptSource.includes('empty-workspaces'));
		assert.ok(launchScriptSource.includes('Empty workspace mode does not support seeded scenarios yet'));
		assert.ok(launchScriptSource.includes('Unsafe Corgi empty workspace id'));
		assert.ok(launchScriptSource.includes('WORKSPACE_MODE" != "empty"'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_REPO_ID'));
		assert.ok(launchScriptSource.includes('repo-workspaces'));
		assert.ok(launchScriptSource.includes('Unsafe Corgi repo workspace id'));
		assert.ok(launchScriptSource.includes('rsync -a --delete'));
		assert.ok(!launchScriptSource.includes('WORKSPACE_ROOT="$ROOT_DIR"'));
		assert.ok(launchScriptSource.includes('Refusing to launch Corgi test window against the development repo'));
		assert.ok(launchScriptSource.includes('Refusing to launch Corgi test window outside the configured test root'));
		assert.ok(launchScriptSource.includes('Refusing to use the development .agent folder'));
		assert.ok(launchScriptSource.includes('CORGI_TEST_WINDOW_SCRATCH_ID'));
		assert.ok(launchScriptSource.includes('Unsafe Corgi scratch workspace id'));
		assert.ok(launchScriptSource.includes('ORCHESTRATION_TARGET_WORKSPACE_MODE'));
		assert.ok(launchScriptSource.includes('ORCHESTRATION_TEST_PROMPT_PRESET'));
		assert.ok(launchScriptSource.includes('pet-diary-fixture.cjs'));
		assert.ok(launchScriptSource.includes('pet-life-diary-bugfix'));
		assert.ok(launchScriptSource.includes('pet-life-diary-filter'));
		assert.ok(launchScriptSource.includes('scratch-workspaces'));
		assert.ok(launchScriptSource.includes('current-run.json'));
		assert.ok(launchScriptSource.includes('ORCHESTRATION_SOURCE_ROOT'));
		assert.ok(launchScriptSource.includes('corgi-test-prompt.cjs'));
		assert.ok(launchScriptSource.includes('"$CLOSE_SCRIPT"'));
		assert.ok(launchScriptSource.includes('CORGI_SEMANTIC_MODE="${CORGI_SEMANTIC_MODE:-sidecar-first}"'));
		assert.ok(launchScriptSource.includes('CORGI_SEMANTIC_SIDECAR_RUNTIME="${CORGI_SEMANTIC_SIDECAR_RUNTIME:-app-server}"'));
		assert.ok(!launchScriptSource.includes('pkill -f "$USER_DATA_DIR"'));
		assert.ok(!launchScriptSource.includes('pkill -9 -f "$USER_DATA_DIR"'));
		assert.ok(closeScriptSource.includes('assert_test_profile_path'));
		assert.ok(closeScriptSource.includes('Refusing to close non-test VS Code profile'));
		assert.ok(closeScriptSource.includes('CORGI_TEST_WINDOW_ROOT'));
		assert.ok(closeScriptSource.includes('$TEST_ROOT/'));
		assert.ok(closeScriptSource.includes('$ROOT_DIR/.agent/test-window/'));
		assert.ok(closeScriptSource.includes('pkill -TERM -f "$profile_dir"'));
		assert.ok(!closeScriptSource.includes('pkill -f "$APP_NAME"'));
		assert.ok(!closeScriptSource.includes('pkill -f "Visual Studio Code"'));
		assert.ok(autoScriptSource.includes('trap cleanup EXIT'));
		assert.ok(autoScriptSource.includes('close-corgi-test-window.sh'));
		assert.ok(autoScriptSource.includes('corgi-test-window-status.cjs'));
		assert.ok(autoScriptSource.includes('CORGI_TEST_WINDOW_SNAPSHOT_GRACE_SECONDS'));
		assert.ok(autoScriptSource.includes('PROMPT_PRESET="${CORGI_TEST_WINDOW_PROMPT_PRESET:-pet-life-diary-static}"'));
		assert.ok(autoScriptSource.includes('AUTO_STEPS="${CORGI_TEST_WINDOW_AUTO_STEPS:-execute}"'));
		assert.ok(autoScriptSource.includes('WORKSPACE_MODE="${CORGI_TEST_WINDOW_WORKSPACE_MODE:-scratch}"'));
		assert.ok(autoScriptSource.includes('governor_decision_recorded'));
		assert.ok(autoScriptSource.includes('executor_completed'));
		assert.ok(autoScriptSource.includes('pet-life-diary-filter-review-retry'));
		assert.ok(autoScriptSource.includes('currentAttemptNumber'));
		assert.ok(autoScriptSource.includes('latestGovernorDecision'));
		assert.ok(autoScriptSource.includes('exited before reaching the expected checkpoint'));
		assert.ok(!autoScriptSource.includes('run_state'));
		assert.ok(fs.existsSync(PET_DIARY_DEMO_DRIVER_PATH));
		assert.ok(petDiaryDemoDriverSource.includes('pet-life-diary-filter-review-retry'));
		assert.ok(petDiaryDemoDriverSource.includes('run-corgi-test-window-auto.sh'));
		assert.ok(petDiaryDemoDriverSource.includes('latest-pet-life-diary-demo.md'));
		assert.ok(petDiaryDemoDriverSource.includes('demo-reports'));
		assert.ok(petDiaryDemoDriverSource.includes('currentAttemptNumber'));
		assert.ok(petDiaryDemoDriverSource.includes('latestGovernorDecision'));
		assert.ok(petDiaryDemoDriverSource.includes('--print-plan'));
		assert.ok(fs.existsSync(LIVE_GOAL_DEMO_DRIVER_PATH));
		assert.ok(liveGoalDemoDriverSource.includes('pet-life-diary-app-store-demo'));
		assert.ok(liveGoalDemoDriverSource.includes('launch-corgi-test-window.sh'));
		assert.ok(liveGoalDemoDriverSource.includes('close-corgi-test-window.sh'));
		assert.ok(liveGoalDemoDriverSource.includes('latest-live-goal-demo.md'));
		assert.ok(liveGoalDemoDriverSource.includes('The test window is still open for inspection.'));
		assert.ok(liveGoalDemoDriverSource.includes('--close-on-success'));
		assert.ok(liveGoalDemoDriverSource.includes('qualityChecks'));
		assert.ok(promptScriptSource.includes('validateCatalog'));
		assert.ok(statusScriptSource.includes('corgi_webview_snapshot.json'));
		assert.ok(statusScriptSource.includes('current-run.json'));
		assert.ok(statusScriptSource.includes('CORGI_TEST_WINDOW_ROOT'));
		assert.ok(statusScriptSource.includes('.corgi'));
		assert.ok(statusScriptSource.includes('workspaceMode'));
		assert.ok(statusScriptSource.includes('workspaceRoot'));
		assert.ok(statusScriptSource.includes('workspaceFile'));
		assert.ok(statusScriptSource.includes('agentRoot'));
		assert.ok(statusScriptSource.includes('workspaceIsolationError'));
		assert.ok(statusScriptSource.includes('Test root is inside the development repo'));
		assert.ok(statusScriptSource.includes('development repo as its workspace'));
		assert.ok(statusScriptSource.includes('repo-workspaces isolation'));
		assert.ok(statusScriptSource.includes('scratch-workspaces isolation'));
		assert.ok(statusScriptSource.includes('empty-workspaces isolation'));
		assert.ok(statusScriptSource.includes('workspaceWriteError'));
		assert.ok(statusScriptSource.includes('${label} is not writable'));
		assert.ok(statusScriptSource.includes('Write error: none'));
		assert.ok(statusScriptSource.includes('processState'));
		assert.ok(statusScriptSource.includes('oldProfileProcessAlive'));
		assert.ok(statusScriptSource.includes('legacyProfileProcessAlive'));
		assert.ok(statusScriptSource.includes('lastRunCompleted'));
		assert.ok(statusScriptSource.includes('governor_decision_recorded'));
		assert.ok(statusScriptSource.includes('Current Corgi test window process is not running'));
		assert.ok(statusScriptSource.includes('Process error: none'));
		assert.ok(statusScriptSource.includes('relevantLogErrors'));
		assert.ok(statusScriptSource.includes('isKnownBenignVsCodeLogLine'));
		assert.ok(statusScriptSource.includes('GPU process exited unexpectedly: exit_code=15'));
		assert.ok(statusScriptSource.includes('Render frame was disposed before WebFrameMain could be accessed'));
		assert.ok(statusScriptSource.includes('Visual%20Studio%20Code'));
		assert.ok(statusScriptSource.includes('processAlive'));
		assert.ok(statusScriptSource.includes('feedHasError'));
		assert.ok(statusScriptSource.includes('knownBlockingError'));
		assert.ok(statusScriptSource.includes('currentAttemptNumber'));
		assert.ok(statusScriptSource.includes('latestReviewVerdict'));
		assert.ok(statusScriptSource.includes('latestGovernorDecision'));
		assert.ok(!statusScriptSource.includes('visibleError'));
		assert.ok(processTestSource.includes('ORCHESTRATION_AGENT_ROOT'));
		assert.ok(processTestSource.includes('ORCHESTRATION_SOURCE_ROOT'));
		assert.ok(processTestSource.includes('ORCHESTRATION_TARGET_WORKSPACE_MODE'));
		assert.ok(processTestSource.includes('ORCHESTRATION_TEST_PROMPT_PRESET'));
		assert.ok(processTestSource.includes('createScratchTestEnv'));
		assert.ok(processTestSource.includes('scratch-static-app'));
		assert.ok(processTestSource.includes('scratch-bugfix-existing-app'));
		assert.ok(processTestSource.includes('scratch-feature-existing-app'));
		assert.ok(processTestSource.includes('scratch-review-retry-existing-app'));
		assert.ok(processTestSource.includes('pet-life-diary-static'));
		assert.ok(processTestSource.includes('pet-life-diary-bugfix'));
		assert.ok(processTestSource.includes('pet-life-diary-filter'));
		assert.ok(processTestSource.includes('pet-life-diary-filter-review-retry'));
		assert.ok(processTestSource.includes('seedFilterPetDiaryApp'));
		assert.ok(processTestSource.includes('ORCHESTRATION_APPROVED_PYTHON'));
		assert.ok(processTestSource.includes('--auto-consume-executor'));
		assert.ok(processTestSource.includes('--module'));
		assert.ok(processTestSource.includes('assertExecutorArtifacts'));
		assert.ok(processTestSource.includes('assertReviewerArtifacts'));
		assert.ok(processTestSource.includes('runReviewReplanModule'));
		assert.ok(processTestSource.includes('corgi-review-replan-process-test.py'));
		assert.ok(processTestSource.includes('corgi-scratch-review-retry-process-test.py'));
		assert.ok(fs.existsSync(PROCESS_REPLAN_HELPER_PATH));
		assert.ok(fs.existsSync(PROCESS_SCRATCH_RETRY_HELPER_PATH));
		assert.strictEqual(promptCatalog.defaultPromptId, 'analyze-repo');
		assert.ok(promptCatalog.prompts.length >= 8);
		for (const prompt of promptCatalog.prompts) {
			assert.ok(prompt.id);
			assert.ok(prompt.prompt);
			assert.ok(prompt.category);
			assert.ok(prompt.requiresScenario);
			assert.ok(prompt.expectedFlow.length > 0);
			assert.ok(prompt.assertions.length > 0);
			assert.ok(prompt.tags.length > 0);
		}
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'analyze-repo'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'architecture'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'develop-internet'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'pet-life-diary-static'));
		assert.ok(
			promptCatalog.prompts.some((prompt) => prompt.id === 'pet-life-diary-app-store-demo')
		);
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'pet-life-diary-bugfix'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'pet-life-diary-filter'));
		assert.ok(
			promptCatalog.prompts.some((prompt) => prompt.id === 'pet-life-diary-filter-review-retry')
		);
		assert.ok(
			promptCatalog.prompts.some((prompt) => prompt.id === 'pet-life-diary-goal-program')
		);
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'progress'));
		assert.ok(promptCatalog.prompts.some((prompt) => prompt.id === 'mixed-stop-work'));
		assert.strictEqual(
			scripts['test:process'],
			'node scripts/corgi-process-test.cjs --through-executor'
		);
		assert.strictEqual(
			scripts['test:process:all'],
			'node scripts/corgi-process-test.cjs --all'
		);
		assert.strictEqual(
			scripts['test:process:executor'],
			'node scripts/corgi-process-test.cjs --module executor'
		);
		assert.strictEqual(
			scripts['test:process:modules'],
			'node scripts/corgi-process-test.cjs --module all'
		);
		assert.strictEqual(
			scripts['test:process:review-replan'],
			'node scripts/corgi-process-test.cjs --module review-replan'
		);
		assert.strictEqual(
			scripts['test:process:reviewer'],
			'node scripts/corgi-process-test.cjs --module reviewer'
		);
		assert.strictEqual(
			scripts['test:process:scratch'],
			'node scripts/corgi-process-test.cjs --module scratch-static-app'
		);
		assert.strictEqual(
			scripts['test:process:project'],
			'node scripts/corgi-process-test.cjs --module scratch-bugfix-existing-app'
		);
		assert.strictEqual(
			scripts['test:process:feature'],
			'node scripts/corgi-process-test.cjs --module scratch-feature-existing-app'
		);
		assert.strictEqual(
			scripts['test:process:project-retry'],
			'node scripts/corgi-process-test.cjs --module scratch-review-retry-existing-app'
		);
		assert.strictEqual(
			scripts['test:process:goal'],
			'node scripts/corgi-process-test.cjs --module scratch-goal-program'
		);
		assert.strictEqual(
			scripts['test:process:completion'],
			'node scripts/corgi-process-test.cjs --module completion'
		);
		assert.strictEqual(scripts['test:prompts'], 'node scripts/corgi-test-prompt.cjs validate');
		assert.strictEqual(scripts['test:prompts:list'], 'node scripts/corgi-test-prompt.cjs list');
		assert.strictEqual(
			scripts['test:window'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:empty'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=empty CORGI_TEST_WINDOW_AUTO_PROMPT= bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:architecture'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=architecture bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:architecture:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=architecture CORGI_TEST_WINDOW_AUTO_STEPS=plan bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:architecture:e2e'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=architecture CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:feature'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=develop-internet bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:greeting'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=greeting bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:mixed'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=mixed-stop-work bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:progress'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=progress bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:question-work'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_PROMPT_PRESET=question-work bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:executor'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=execute-permission bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:plan-ready'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=plan-ready bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:reviewer'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=reviewer-completed bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:reviewer-ready'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=repo CORGI_TEST_WINDOW_SCENARIO=reviewer-ready bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:scratch'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static bash scripts/launch-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:scratch:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/run-corgi-test-window-auto.sh'
		);
		assert.strictEqual(
			scripts['test:window:project:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-bugfix CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/run-corgi-test-window-auto.sh'
		);
		assert.strictEqual(
			scripts['test:window:feature-app:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-filter CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/run-corgi-test-window-auto.sh'
		);
		assert.strictEqual(
			scripts['test:window:project-retry:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-filter-review-retry CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/run-corgi-test-window-auto.sh'
		);
		assert.strictEqual(
			scripts['test:window:close'],
			'bash scripts/close-corgi-test-window.sh'
		);
		assert.strictEqual(
			scripts['test:window:auto'],
			'CORGI_TEST_WINDOW_WORKSPACE_MODE=scratch CORGI_TEST_WINDOW_PROMPT_PRESET=pet-life-diary-static CORGI_TEST_WINDOW_AUTO_STEPS=execute bash scripts/run-corgi-test-window-auto.sh'
		);
		assert.strictEqual(
			scripts['test:window:status'],
			'node scripts/corgi-test-window-status.cjs'
		);
		assert.strictEqual(
			scripts['demo:pet-diary'],
			'node scripts/run-corgi-pet-diary-demo.cjs'
		);
		assert.strictEqual(
			scripts['demo:pet-diary:plan'],
			'node scripts/run-corgi-pet-diary-demo.cjs --print-plan'
		);
		assert.strictEqual(
			scripts['demo:live-goal'],
			'node scripts/run-corgi-live-goal-demo.cjs'
		);
		assert.strictEqual(
			scripts['demo:live-goal:plan'],
			'node scripts/run-corgi-live-goal-demo.cjs --print-plan'
		);
		assert.ok(!extensionSource.includes('CORGI_RESET_DEV_SESSION'));
		assert.ok(!developmentSessionSource.includes('CORGI_RESET_DEV_SESSION'));
		assert.ok(!extensionSource.includes('CORGI_RESET_WEBVIEW_STATE'));
		assert.ok(!developmentSessionSource.includes('CORGI_RESET_WEBVIEW_STATE'));
		assert.ok(!webviewSource.includes('CORGI_RESET_WEBVIEW_STATE'));
	});

	test('declares app-server Governor runtime as default while keeping exec selectable', () => {
		const manifest = loadPackageJson();
		const contributes = manifest.contributes as Record<string, unknown>;
		const configuration = contributes.configuration as Record<string, unknown>;
		const properties = configuration.properties as Record<string, unknown>;
		const runtimeSetting = properties['corgi.governorRuntime'] as Record<string, unknown>;
		const semanticRuntimeSetting = properties[
			'corgi.semanticSidecarRuntime'
		] as Record<string, unknown>;

		assert.strictEqual(runtimeSetting.default, 'app-server');
		assert.deepStrictEqual(runtimeSetting.enum, ['exec', 'app-server']);
		assert.strictEqual(semanticRuntimeSetting.default, 'app-server');
		assert.deepStrictEqual(semanticRuntimeSetting.enum, ['exec', 'app-server']);
	});

	test('semantic sidecar runtime defaults to app-server while keeping exec selectable', () => {
		const webviewSource = readExecutionWindowSource();
		const semanticSource = fs.readFileSync(
			path.resolve(__dirname, '../../src/semanticSidecar.ts'),
			'utf8'
		);

		assert.ok(webviewSource.includes('CORGI_SEMANTIC_SIDECAR_RUNTIME'));
		assert.ok(webviewSource.includes("get<string>('semanticSidecarRuntime')"));
		assert.ok(webviewSource.includes('runtime: semanticSidecarRuntime()'));
		assert.ok(webviewSource.includes('this.semanticSidecar.shutdown()'));
		assert.ok(semanticSource.includes("runtimeKind: 'semantic_intake'"));
		assert.ok(semanticSource.includes('ephemeralThread: true'));
		assert.ok(semanticSource.includes('previewEnabled: false'));
		assert.ok(semanticSource.includes("reasoning: 'low'"));
		assert.ok(semanticSource.includes('new CodexAppServerClient()'));
		assert.ok(semanticSource.includes('new CodexSemanticRunner()'));
		assert.ok(semanticSource.includes('corgi-semantic-appserver-'));
		assert.ok(semanticSource.includes('runtime=app-server'));
		assert.ok(semanticSource.includes('elapsedMs='));
	});

	test('app-server client keeps protocol details internal and handles fallback-relevant failures', () => {
		const clientSource = fs.readFileSync(CODEX_APP_SERVER_CLIENT_TS_PATH, 'utf8');
		const runtimeSource = fs.readFileSync(GOVERNOR_RUNTIME_TS_PATH, 'utf8');

		assert.ok(clientSource.includes("'codex'"));
		assert.ok(clientSource.includes("'app-server'"));
		assert.ok(clientSource.includes('analytics.enabled=false'));
		assert.ok(clientSource.includes('pendingRequests'));
		assert.ok(clientSource.includes('item/agentMessage/delta'));
		assert.ok(clientSource.includes('item/completed'));
		assert.ok(clientSource.includes('turn/completed'));
		assert.ok(clientSource.includes('turn/interrupt'));
		assert.ok(clientSource.includes('turn_request_sent'));
		assert.ok(clientSource.includes('draft_preview'));
		assert.ok(clientSource.includes('compactPreviewText'));
		assert.ok(clientSource.includes('text.length <= 5000'));
		assert.ok(clientSource.includes('app-server emitted malformed JSON'));
		assert.ok(runtimeSource.includes("account.kind === 'apiKey'"));
		assert.ok(runtimeSource.includes('expects ChatGPT auth'));
		assert.ok(runtimeSource.includes("previewEnabled: request.runtimeKind !== 'semantic_intake'"));
		assert.ok(runtimeSource.includes('CORGI_SEMANTIC_INTAKE_TIMEOUT_MS'));
		assert.ok(runtimeSource.includes('DEFAULT_SEMANTIC_INTAKE_TIMEOUT_MS = 60_000'));
		assert.ok(!runtimeSource.includes("? 25_000"));
	});

	test('semantic-intake runtime progress is presented as interpretation, not user-visible drafting', () => {
		const webviewSource = readExecutionWindowSource();
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');
		const clientSource = fs.readFileSync(CODEX_APP_SERVER_CLIENT_TS_PATH, 'utf8');

		assert.ok(clientSource.includes("runtimeKind?: 'dialogue' | 'plan' | 'semantic_intake' | 'goal_plan'"));
		assert.ok(clientSource.includes('firstDeltaMessage'));
		assert.ok(clientSource.includes('Breaking goal into steps'));
		assert.ok(clientSource.includes('Drafting plan'));
		assert.ok(clientSource.includes('Plan draft preview'));
		assert.ok(transportSource.includes('runtimeKind: event.runtimeKind'));
		assert.ok(webviewSource.includes("event.runtimeKind === 'semantic_intake'"));
		assert.ok(webviewSource.includes("event.runtimeKind === 'plan'"));
		assert.ok(webviewSource.includes('if (event.model)'));
		assert.ok(webviewSource.includes('this.model = event.model'));
		assert.ok(webviewSource.includes('Understanding request'));
		assert.ok(webviewSource.includes('Drafting plan'));
		assert.ok(webviewSource.includes('Still drafting plan'));
		assert.ok(webviewSource.includes('runtimeTimings'));
		assert.ok(webviewSource.includes('lastRuntimeTimings'));
		assert.ok(webviewSource.includes('uiLagMs'));
		assert.ok(webviewSource.includes('Preparing request'));
		assert.ok(webviewSource.includes('Request sent'));
		assert.match(
			webviewSource,
			/snapshot\.currentActor === 'governor'[\s\S]*?snapshot\.currentStage === 'semantic_intake'[\s\S]*?snapshot\.runState === 'running'/
		);
	});

	test('prompt submits omit sessionRef while state-bound actions still gate it on authoritative transport state', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(webviewSource.includes('CORGI_SEMANTIC_MODE'));
		assert.ok(webviewSource.includes("semantic_mode: 'governor-first'"));
		assert.ok(webviewSource.includes('private hasAuthoritativeTransportState = false;'));
		assert.ok(webviewSource.includes('this.hasAuthoritativeTransportState = true;'));
		assert.ok(
			webviewSource.includes(
				'includeSessionRef = this.hasAuthoritativeTransportState'
			)
		);
		assert.match(
			webviewSource,
			/await this\.routeFreeText\(\s*message\.text \?\? '',\s*message\.requestId,\s*this\.hasAuthoritativeTransportState\s*\)/
		);
		assert.match(
			webviewSource,
			/session_ref:\s*action\.session_ref\s*\?\?\s*\(\s*action\.type !== 'submit_prompt' && includeSessionRef\s*\?\s*this\.model\.snapshot\.sessionRef\s*:\s*undefined\s*\)/
		);
	});

	test('permission clicks keep the foreground request key while sending a fresh command request id', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(webviewSource.includes('function foregroundRequestKeyForAction(action) {'));
		assert.ok(webviewSource.includes('pendingPermissionRequest?.foregroundRequestId'));
		assert.match(
			webviewSource,
			/const requestId = nextForegroundRequestKey\(\);\s*const requestKey = foregroundRequestKeyForAction\(action\);\s*ensureForegroundRequest\('', '', requestKey\);/
		);
	});

	test('governor replies do not render debug details in the transcript', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(
			webviewSource.includes(
				"if (item.type === 'actor_event' && item.source_actor === 'governor') {"
			)
		);
		assert.ok(webviewSource.includes("return '';"));
	});

	test('transient progress stack hides after a governor reply and only keeps three visible rows', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(webviewSource.includes('function latestGovernorReplyForRequest(requestKey) {'));
		assert.ok(webviewSource.includes('if (latestGovernorReplyForRequest(requestKey)) {'));
		assert.ok(webviewSource.includes("return '';"));
		assert.ok(webviewSource.includes('const visibleBullets = bullets.slice(-3);'));
		assert.ok(webviewSource.includes('function trimForegroundBullets()'));
		assert.ok(webviewSource.includes('function foregroundRequestCanReceiveTrace(requestKey)'));
		assert.ok(webviewSource.includes('function applyRuntimeProgress(event)'));
		assert.ok(webviewSource.includes('function reconcileLocalUiWithModel()'));
		assert.ok(webviewSource.includes('function foregroundRequestHasAuthoritativeSurface(requestKey)'));
		assert.ok(webviewSource.includes('function clearForegroundRequest()'));
		assert.ok(webviewSource.includes('reconcileLocalUiWithModel();'));
		assert.ok(webviewSource.includes('function setDraftPreviewTarget(value)'));
		assert.ok(webviewSource.includes('function scheduleDraftPreviewTyping()'));
		assert.ok(webviewSource.includes('function scheduleGovernorWaitHeartbeat(event)'));
		assert.ok(webviewSource.includes('visibleBullets.length === 0'));
		assert.ok(webviewSource.includes('Still waiting for reply'));
		assert.ok(webviewSource.includes('Taking a deeper pass'));
		assert.ok(webviewSource.includes('nextDraftPreviewSlice(current, target)'));
		assert.ok(webviewSource.includes("scheduleWebviewSnapshot('draft_preview_type')"));
		assert.ok(webviewSource.includes("scheduleWebviewSnapshot('governor_wait_heartbeat')"));
		assert.ok(webviewSource.includes('draft-preview'));
		assert.ok(webviewSource.includes('Draft preview'));
		assert.ok(
			!/function ensureForegroundRequest[\s\S]*?\(state \|\| ''\)[\s\S]*?\n\t\tfunction latestForegroundUserTextFromModel/.test(
				webviewSource
			)
		);
		assert.ok(webviewSource.includes('snapshot.pendingPermissionRequest'));
		assert.ok(webviewSource.includes('model.activeClarification'));
		assert.ok(webviewSource.includes('activity-trace'));
		assert.ok(webviewSource.includes('Still working behind the scenes'));
		assert.ok(webviewSource.includes('background: transparent;'));
	});

	test('governor runtime config uses gpt-5.5 with xhigh reasoning', () => {
		const configSource = fs.readFileSync(GOVERNOR_RUNTIME_CONFIG_PATH, 'utf8');
		const governorRuntimeSource = fs.readFileSync(
			path.resolve(__dirname, '../../orchestration/harness/governor_runtime.py'),
			'utf8'
		);

		assert.ok(configSource.includes('model = "gpt-5.5"'));
		assert.ok(configSource.includes('model_reasoning_effort = "xhigh"'));
		assert.ok(governorRuntimeSource.includes('model = "gpt-5.5"'));
		assert.ok(governorRuntimeSource.includes('reasoning = "xhigh"'));
	});

	test('registers advisory MCP server through repo entrypoint with Python env handling', () => {
		const configSource = fs.readFileSync(GOVERNOR_RUNTIME_CONFIG_PATH, 'utf8');
		const entrypointSource = fs.readFileSync(MCP_SERVER_ENTRYPOINT_PATH, 'utf8');
		const devEntrypointSource = fs.readFileSync(DEV_MCP_SERVER_ENTRYPOINT_PATH, 'utf8');
		const launcherSource = fs.readFileSync(ADVISORY_MCP_LAUNCHER_PATH, 'utf8');
		const devLauncherSource = fs.readFileSync(DEVELOPMENT_CONSULTING_MCP_LAUNCHER_PATH, 'utf8');
		const setupSource = fs.readFileSync(ADVISORY_MCP_SETUP_PATH, 'utf8');
		const requirementsSource = fs.readFileSync(ADVISORY_MCP_REQUIREMENTS_PATH, 'utf8');

		assert.ok(configSource.includes('[mcp_servers.orchestration_advisory]'));
		assert.ok(configSource.includes('command = "python3"'));
		assert.ok(configSource.includes('args = ["mcp_server.py"]'));
		assert.ok(!configSource.includes('args = ["orchestration/runtime/advisory/mcp_server.py"]'));
		assert.ok(!configSource.includes('dev_mcp_server.py'));
		assert.ok(entrypointSource.includes('serve_advisory_mcp.py'));
		assert.ok(entrypointSource.includes('os.environ["CORGI_ADVISORY_CONTEXT"] = "corgi-governor-runtime"'));
		assert.ok(devEntrypointSource.includes('serve_development_consulting_mcp.py'));
		assert.ok(devLauncherSource.includes('CORGI_ADVISORY_LAUNCH_PROFILE'));
		assert.ok(devLauncherSource.includes('corgi-development-consulting'));
		assert.ok(devLauncherSource.includes('CORGI_ADVISORY_CALLER_ROLE'));
		assert.ok(devLauncherSource.includes('.agent" / "development" / "advisory'));
		assert.ok(devLauncherSource.includes('CORGI_DEVELOPMENT_MINIMAX_API_KEY_FILE'));
		assert.ok(devLauncherSource.includes('env["MINIMAX_API_KEY_FILE"]'));
		assert.ok(launcherSource.includes('ORCHESTRATION_APPROVED_PYTHON'));
		assert.ok(launcherSource.includes('CORGI_ADVISORY_MCP_PYTHON'));
		assert.ok(launcherSource.includes('CORGI_PYTHON'));
		assert.ok(
			launcherSource.indexOf('if ADVISORY_VENV_PYTHON.exists()') <
				launcherSource.indexOf('for env_name in BASE_PYTHON_CANDIDATES')
		);
		assert.ok(launcherSource.includes('return ADVISORY_VENV_PYTHON'));
		assert.ok(!launcherSource.includes('return ADVISORY_VENV_PYTHON.resolve()'));
		assert.ok(launcherSource.includes('CORGI_ADVISORY_MCP_ACTIVE_PYTHON'));
		assert.ok(launcherSource.includes('CORGI_RUNTIME_MINIMAX_API_KEY_FILE'));
		assert.ok(launcherSource.includes('CORGI_DEVELOPMENT_MINIMAX_API_KEY_FILE'));
		assert.ok(launcherSource.includes('env["MINIMAX_API_KEY_FILE"]'));
		assert.ok(launcherSource.includes('/opt/homebrew/bin/python3'));
		assert.ok(launcherSource.includes('ORCHESTRATION_REPO_ROOT'));
		assert.ok(launcherSource.includes('ORCHESTRATION_SOURCE_ROOT'));
		assert.ok(launcherSource.includes('CORGI_ADVISORY_CONTEXT'));
		assert.ok(launcherSource.includes('corgi-governor-runtime'));
		assert.ok(launcherSource.includes('CORGI_ADVISORY_STATE_DIR'));
		assert.ok(launcherSource.includes('PYTHONPATH'));
		assert.ok(launcherSource.includes('requirements.txt'));
		assert.ok(launcherSource.includes('"runtime" / "advisory" / "mcp_server.py"'));
		assert.ok(setupSource.includes('/opt/homebrew/bin/python3'));
		assert.ok(setupSource.includes('.venv'));
		assert.ok(setupSource.includes('requirements.txt'));
		assert.ok(requirementsSource.includes('anthropic'));
		assert.ok(requirementsSource.includes('mcp'));
	});

	test('separates runtime Governor advisory from development consulting', () => {
		const serverSource = fs.readFileSync(ADVISORY_MCP_SERVER_PATH, 'utf8');
		const advisoryDoc = fs.readFileSync(ADVISORY_DOC_PATH, 'utf8');

		assert.ok(serverSource.includes('CORGI_RUNTIME_CONTEXT'));
		assert.ok(serverSource.includes('corgi-governor-runtime'));
		assert.ok(serverSource.includes('corgi-development-consulting'));
		assert.ok(serverSource.includes('Corgi_Governor_Advisor'));
		assert.ok(serverSource.includes('Corgi_Development_Consulting'));
		assert.ok(serverSource.includes('_authorize_tool_call'));
		assert.ok(serverSource.includes('ADVISORY_CALLER_ROLE != "governor"'));
		assert.ok(serverSource.includes('_runtime_prompt_boundary_error'));
		assert.ok(serverSource.includes('_resolve_context_path'));
		assert.ok(advisoryDoc.includes('Runtime advisor file access is target-workspace scoped'));
		assert.ok(advisoryDoc.includes('for building Corgi itself'));
	});

	test('documents runtime ergonomics as presentation-only and advisor capabilities as descriptive', () => {
		const uxContract = fs.readFileSync(UX_CONTRACT_PATH, 'utf8');
		const advisoryDoc = fs.readFileSync(ADVISORY_DOC_PATH, 'utf8');
		const kernelSource = fs.readFileSync(RUNTIME_ERGONOMICS_KERNEL_TS_PATH, 'utf8');
		const capabilities = JSON.parse(
			fs.readFileSync(ADVISORY_CAPABILITIES_PATH, 'utf8')
		) as { capabilities: Array<{ provider: string; roleAccess: string[] }> };

		assert.ok(uxContract.includes('## Runtime Ergonomics Kernel'));
		assert.ok(uxContract.includes('presentation-only'));
		assert.ok(uxContract.includes('must not create workflow truth'));
		assert.ok(uxContract.includes('`activity` is for short operational rows'));
		assert.ok(uxContract.includes('`internal` is for request ids, session refs, context refs'));
		assert.ok(advisoryDoc.includes('## Runtime Capability Registry'));
		assert.ok(advisoryDoc.includes('orchestration/runtime/advisory/capabilities.json'));
		assert.ok(advisoryDoc.includes('| MiniMax | `consult_minimax` | Governor only | none |'));
		assert.ok(advisoryDoc.includes('| Claude Headless | `consult_claude_headless` | Governor only | read-only target workspace |'));
		assert.ok(advisoryDoc.includes('descriptive only'));
		assert.ok(kernelSource.includes('RuntimeActivityVisibility'));
		assert.ok(kernelSource.includes('activityFeedItemIds'));
		assert.ok(kernelSource.includes('governor_decision_recorded'));
		assert.deepStrictEqual(
			capabilities.capabilities.map((capability) => capability.provider),
			['consult_minimax', 'consult_claude_headless', 'consult_architect']
		);
		assert.ok(
			capabilities.capabilities.every((capability) =>
				capability.roleAccess.includes('governor')
			)
		);
	});

	test('permission continuation collapses progress into a specific wait state', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(webviewSource.includes('function setForegroundSingleBullet(label, state, hint) {'));
		assert.ok(webviewSource.includes('Waiting for reply'));
		assert.ok(webviewSource.includes("scope === 'execute'"));
		assert.ok(webviewSource.includes('Starting write'));
		assert.ok(!webviewSource.includes('Applying your permission choice...'));
		assert.ok(
			!webviewSource.includes(
				"appendForegroundBullet('Continuing request', 'active', 'Applying your permission choice...')"
			)
		);
	});

	test('permission action surface stays hidden until authoritative state changes', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(webviewSource.includes('ui.pendingPermissionContextRef ='));
		assert.ok(webviewSource.includes('pendingPermissionHiddenAt'));
		assert.ok(webviewSource.includes('function retainOptimisticHidesUntilAuthoritativeChange()'));
		assert.ok(!webviewSource.includes('const maxHideMs'));
		assert.ok(webviewSource.includes('const composerActions = document.getElementById'));
		assert.ok(webviewSource.includes("actions: collectTextRows(composerActions, 'button')"));
		assert.ok(
			webviewSource.includes(
				'buttons.push(\'<button type="button" class="secondary" data-action="refresh_state">Refresh state</button>\');'
			)
		);
		assert.ok(!webviewSource.includes('Permission choice sent. Waiting for a reply from the Governor...'));
		assert.ok(webviewSource.includes('data-action="refresh_state"'));
		assert.ok(webviewSource.includes('authoritativePermissionContextRef() !== ui.pendingPermissionContextRef'));
		assert.ok(webviewSource.includes('authoritativePlanContextRef() !== ui.pendingPlanContextRef'));
		assert.ok(webviewSource.includes('function clearOptimisticActionHides()'));
		assert.ok(webviewSource.includes('if (latestRequestError(requestKey))'));
		assert.ok(webviewSource.includes('clearOptimisticActionHides();'));
		assert.ok(!webviewSource.includes('pendingPermissionRequest?.contextRef !=='));
	});

	test('plan-ready checkpoint exposes execute and revision actions', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(webviewSource.includes('function isPlanReady(snapshot) {'));
		assert.ok(webviewSource.includes('Plan ready'));
		assert.ok(webviewSource.includes('data-action="execute_plan"'));
		assert.ok(webviewSource.includes('data-action="revise_plan"'));
		assert.ok(webviewSource.includes('pendingPermissionContextRef'));
		assert.ok(webviewSource.includes('planRevisionMode'));
		assert.ok(webviewSource.includes("type: 'execute_plan'"));
		assert.ok(webviewSource.includes("type: 'revise_plan'"));
		assert.ok(webviewSource.includes("runtimeActionLabel('execute_plan', 'Execute plan')"));
		assert.ok(webviewSource.includes("runtimeActionLabel('revise_plan', 'Revise')"));
		assert.ok(webviewSource.includes('Send revision'));
	});

	test('presentation mapping keeps non-governor copy controller-owned', () => {
		const webviewSource = readExecutionWindowSource();

		assert.ok(webviewSource.includes('function displayCopy(item) {'));
		assert.ok(webviewSource.includes("case 'permission.needed':"));
		assert.ok(webviewSource.includes("case 'error.semantic_route_required':"));
		assert.ok(webviewSource.includes("case 'error.stale_context':"));
		assert.ok(webviewSource.includes("case 'executor.completed':"));
		assert.ok(webviewSource.includes("case 'reviewer.completed':"));
		assert.ok(webviewSource.includes("case 'governor.final_decision':"));
		assert.ok(
			webviewSource.includes(
				"if (item.type === 'actor_event' && item.source_actor === 'governor') {"
			)
		);
		assert.ok(webviewSource.includes('const copy = displayCopy(item);'));
		assert.ok(webviewSource.includes('renderStructuredAssistantBody(body)'));
		assert.ok(webviewSource.includes('function renderCompactResultMessage(item, copy, renderedBody)'));
		assert.ok(webviewSource.includes('message assistant result-summary'));
		assert.ok(webviewSource.includes('Checked result'));
		assert.ok(webviewSource.includes('escapeHtml(body)'));

		const permissionModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'what happened?',
			semantic_route_type: 'governor_dialogue',
			request_id: 'req-dialogue',
			now: '2026-04-10T10:00:05.000Z',
		});
		const permissionItem = permissionModel.feed.find(
			(item) => item.type === 'permission_request'
		);
		assert.strictEqual(permissionItem?.presentation_key, 'permission.needed');
		assert.strictEqual(permissionItem?.presentation_args?.scope, 'observe');

		const clarificationModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'analyze the repo',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const failedClarificationModel = applyModelAction(clarificationModel, {
			type: 'answer_clarification',
			text: 'architecture',
			context_ref: 'stale-context',
			request_id: 'req-stale',
			now: '2026-04-10T10:00:10.000Z',
		});
		const errorItem = failedClarificationModel.feed[failedClarificationModel.feed.length - 1];
		assert.strictEqual(errorItem.type, 'error');
		assert.strictEqual(errorItem.presentation_key, 'error.stale_context');
		assert.strictEqual(errorItem.presentation_args?.kind, 'clarification');
	});

	test('webview snapshot renders the goal strip and compact post-execution summaries', () => {
		const reviewArtifact = {
			id: 'review-report',
			label: 'Reviewer report',
			path: '.agent/reviews/review.md',
			status: 'ready',
			summary: 'Reviewer report artifact',
			authoritative: true,
		};
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			activeForegroundRequestId: 'corgi-request:test:execute',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'reviewer',
				currentStage: 'reviewer_completed',
				permissionScope: 'execute',
				runState: 'idle',
				recentArtifacts: [reviewArtifact],
			},
			feed: [
				{
					id: 'user-message',
					type: 'user_message',
					title: 'Prompt submitted',
					body: 'analyze the repo',
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: false,
				},
				{
					id: 'governor-plan',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: analyze the repository architecture.\n\nReadiness: plan-ready.',
					timestamp: '2026-04-10T10:00:05.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
				{
					id: 'accepted-ready',
					type: 'system_status',
					title: 'Accepted and ready',
					body: 'Accepted intake summary should not appear in transcript.',
					timestamp: '2026-04-10T10:00:06.000Z',
					authoritative: true,
					source_actor: 'orchestration',
					source_layer: 'orchestration',
				},
				{
					id: 'execute-plan-action',
					type: 'user_message',
					title: 'Permission selected',
					body: 'Execute plan',
					timestamp: '2026-04-10T10:00:10.000Z',
					authoritative: false,
					turn_type: 'permission_action',
					in_response_to_request_id: 'corgi-request:test:execute',
				},
				{
					id: 'executor-completed',
					type: 'system_status',
					title: 'Executor completed',
					body: 'Executor wrote details at .agent/executor/result.md.',
					timestamp: '2026-04-10T10:00:20.000Z',
					authoritative: true,
					source_actor: 'executor',
					source_artifact_ref: reviewArtifact.path,
					activity: {
						kind: 'status',
						state: 'completed',
						summary: '1 output · authorship verified',
					},
					presentation_key: 'executor.completed',
					presentation_args: {
						summary: '1 output · authorship verified',
						outputs: 1,
					},
					in_response_to_request_id: 'corgi-request:test:execute',
				},
				{
					id: 'reviewer-completed',
					type: 'system_status',
					title: 'Reviewer completed',
					body: 'Reviewer completed the read-only check at .agent/reviews/review.md.',
					timestamp: '2026-04-10T10:00:30.000Z',
					authoritative: true,
					source_actor: 'reviewer',
					source_artifact_ref: reviewArtifact.path,
					activity: {
						kind: 'status',
						state: 'completed',
						summary: 'Verdict pass · 2 validation checks',
					},
					presentation_key: 'reviewer.completed',
					presentation_args: {
						summary: 'Verdict pass · 2 validation checks',
						verdict: 'pass',
					},
					in_response_to_request_id: 'corgi-request:test:execute',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const messageText = snapshot.messages.map((message) => message.text).join('\n');
		const activityText = snapshot.activity.map((message) => message.text).join('\n');
		const transcriptText = snapshot.transcript.map((message) => message.text).join('\n');

		assert.match(snapshot.goalStrip, /Goal: Analyze the repository architecture\./);
		assert.match(snapshot.goalStrip, /Step: Checked result/);
		assert.match(snapshot.goalStrip, /Done/);
		assert.strictEqual(snapshot.composer.context, 'Scope: Execute');
		assert.match(activityText, /Changes written/);
		assert.match(activityText, /1 output · authorship verified/);
		assert.match(messageText, /Checked result/);
		assert.match(messageText, /Verdict pass · 2 validation checks/);
		assert.match(transcriptText, /Objective: analyze the repository architecture/);
		assert.ok(!transcriptText.includes('Executor wrote details'));
		assert.ok(!transcriptText.includes('Reviewer completed the read-only check'));
		assert.match(messageText, /View source/);
		assert.ok(!messageText.includes('Execute plan'));
		assert.ok(!transcriptText.includes('Accepted intake summary should not appear in transcript.'));
		assert.ok(!messageText.includes('reviewer_completed'));
		assert.ok(!snapshot.composer.context.includes('Reviewer'));
		assert.deepStrictEqual(snapshot.progress, []);
	});

	test('goal strip hides redundant status while preserving meaningful status', () => {
		const idleSnapshot = renderWebviewSnapshot(
			createInitialModel('2026-04-10T10:00:00.000Z')
		);

		assert.match(idleSnapshot.goalStrip, /Goal: Nothing active yet/);
		assert.match(idleSnapshot.goalStrip, /Step: Ready/);
		assert.ok(!idleSnapshot.goalStrip.includes('Ready Ready'));
		assert.ok(!idleSnapshot.goalStrip.includes('Ready · Ready'));

		const finalModel: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Build pet diary app.',
				currentStage: 'governor_decision_recorded',
				currentActor: 'governor',
				currentAttemptNumber: 1,
				latestGovernorDecision: 'accept',
				runState: 'idle',
			},
		};

		const finalSnapshot = renderWebviewSnapshot(finalModel);
		assert.match(finalSnapshot.goalStrip, /Final decision Accept/);
		assert.match(finalSnapshot.goalStrip, /Finalized/);
	});

	test('goal strip uses authoritative parent goal and step progress', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Add species filtering',
				currentGoalRef: 'goal-123',
				currentGoalTitle: 'Build a polished Pet Life Diary web app demo.',
				currentGoalStepRef: 'step-02',
				currentGoalStepIndex: 2,
				goalStepCount: 3,
				goalStatus: 'active',
				currentStage: 'plan_ready',
				currentActor: 'governor',
				permissionScope: 'plan',
				runState: 'idle',
			},
			planReadyRequest: {
				id: 'plan-ready',
				contextRef: 'plan-ready-context',
				title: 'Plan ready',
				body: 'Ready for the next step.',
				requestedAt: '2026-04-10T10:00:00.000Z',
				acceptedIntakeSummary: {
					title: 'Add species filtering',
					body: 'Add a species filter.',
				},
				allowedActions: ['execute_plan', 'revise_plan'],
			},
		};

		const snapshot = renderWebviewSnapshot(model);
		assert.match(snapshot.goalStrip, /Goal: Build a polished Pet Life Diary web app demo\./);
		assert.match(snapshot.goalStrip, /Step: Step 2\/3 · Plan ready/);
		assert.match(snapshot.goalStrip, /Plan ready/);
		assert.ok(!snapshot.goalStrip.includes('goal-123'));
		assert.ok(snapshot.actions.some((action) => action.text === 'Execute plan'));

		const planningModel: ExecutionWindowModel = {
			...model,
			planReadyRequest: undefined,
			snapshot: {
				...model.snapshot,
				currentStage: 'goal_planning',
				currentActor: 'governor',
				runState: 'running',
			},
		};

		const planningSnapshot = renderWebviewSnapshot(planningModel);
		assert.match(planningSnapshot.goalStrip, /Step: Step 2\/3 · Breaking goal into steps/);
	});

	test('runtime ergonomics kernel separates transcript, activity, detail, and internal surfaces', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeForegroundRequestId: 'req-kernel',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'reviewer',
				currentStage: 'reviewer_completed',
				currentWorkRef: 'lane/main/work-123',
				currentAttemptNumber: 2,
			},
			feed: [
				{
					id: 'governor',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: analyze the repo.',
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
				{
					id: 'executor',
					type: 'system_status',
					title: 'Executor completed',
					body: 'Executor wrote .agent/dispatches/lane/main/dispatch-1/result.json.',
					timestamp: '2026-04-10T10:00:10.000Z',
					authoritative: true,
					source_actor: 'executor',
					source_artifact_ref: '.agent/dispatches/lane/main/dispatch-1/result.json',
					activity: {
						kind: 'status',
						state: 'completed',
						summary: '1 mutated output · authorship verified',
					},
					presentation_key: 'executor.completed',
					presentation_args: {
						summary: '1 mutated output · authorship verified',
					},
				},
				{
					id: 'artifact',
					type: 'artifact_reference',
					title: 'Result artifact',
					timestamp: '2026-04-10T10:00:11.000Z',
					authoritative: true,
					artifact: {
						id: 'artifact',
						label: 'result.json',
						path: '.agent/dispatches/lane/main/dispatch-1/result.json',
						authoritative: true,
					},
				},
				{
					id: 'permission-action',
					type: 'user_message',
					title: 'Permission selected',
					body: 'Execute plan',
					timestamp: '2026-04-10T10:00:12.000Z',
					authoritative: false,
					turn_type: 'permission_action',
				},
				{
					id: 'accepted-ready',
					type: 'system_status',
					title: 'Accepted and ready',
					body: 'Accepted intake summary should stay out of the transcript.',
					timestamp: '2026-04-10T10:00:13.000Z',
					authoritative: true,
					source_actor: 'orchestration',
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);
		const activityText = kernel.activities
			.map((activity) => [activity.summary, activity.detail].filter(Boolean).join('\n'))
			.join('\n');

		assert.deepStrictEqual(kernel.transcriptFeedItemIds, ['governor']);
		assert.deepStrictEqual(kernel.activityFeedItemIds, ['executor']);
		assert.deepStrictEqual(kernel.detailFeedItemIds, ['artifact']);
		assert.deepStrictEqual(kernel.internalFeedItemIds, ['permission-action', 'accepted-ready']);
		assert.match(activityText, /Changes written/);
		assert.match(activityText, /1 mutated output · authorship verified/);
		assert.ok(!activityText.includes('dispatch-1'));
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[0]), 'transcript');
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[1]), 'activity');
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[2]), 'detail');
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[3]), 'internal');
		assert.strictEqual(runtimeVisibilityForFeedItem(model.feed[4]), 'internal');
		assert.strictEqual(buildRuntimeErgonomicsKernel(model).internalFeedItemIds.includes('accepted-ready'), true);
	});

	test('webview snapshot caps routine activity rows behind an overflow control', () => {
		const base = createInitialModel('2026-04-10T10:00:00.000Z');
		const activityKinds = [
			'read',
			'search',
			'list',
			'command',
			'edit',
			'artifact',
			'status',
		] as const;
		const model: ExecutionWindowModel = {
			...base,
			snapshot: {
				...base.snapshot,
				task: 'Build the static pet diary app.',
				currentActor: 'executor',
				currentStage: 'plan_executing',
				runState: 'running',
			},
			feed: activityKinds.map((kind, index) => ({
				id: `activity-${index}`,
				type: 'system_status',
				title: `Activity ${index}`,
				body: `Activity ${index}`,
				timestamp: `2026-04-10T10:00:${String(index).padStart(2, '0')}.000Z`,
				authoritative: true,
				source_actor: 'executor',
				activity: {
					kind,
					state: index === activityKinds.length - 1 ? 'running' : 'completed',
					path: kind === 'read' || kind === 'edit' || kind === 'artifact' ? `src/file-${index}.ts` : undefined,
					query: kind === 'search' ? 'pet diary' : undefined,
					command: kind === 'command' ? 'npm test' : undefined,
					summary: `Activity summary ${index}`,
				},
			})),
		};

		const snapshot = renderWebviewSnapshot(model);
		const overflowText = snapshot.activityOverflow.map((row) => row.text).join('\n');

		assert.strictEqual(snapshot.activity.length, 5);
		assert.match(overflowText, /Older activity \(2\)/);
		assert.match(overflowText, /Activity summary 0/);
		assert.match(overflowText, /Activity summary 1/);
		assert.ok(snapshot.activity.every((row) => !row.text.includes('activity-')));
	});

	test('runtime ergonomics kernel hides stale blocking surfaces from transcript indexes', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeClarification: undefined,
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				pendingPermissionRequest: undefined,
			},
			feed: [
				{
					id: 'stale-permission',
					type: 'permission_request',
					title: 'Permission needed',
					body: 'Choose plan if you want Corgi to continue.',
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: true,
				},
				{
					id: 'stale-clarification',
					type: 'clarification_request',
					title: 'Clarification required',
					body: 'What should Corgi focus on?',
					timestamp: '2026-04-10T10:00:01.000Z',
					authoritative: true,
				},
				{
					id: 'ready',
					type: 'system_status',
					title: 'Ready when you are',
					body: 'Ask Corgi to work on this repo.',
					timestamp: '2026-04-10T10:00:02.000Z',
					authoritative: true,
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);

		assert.deepStrictEqual(kernel.transcriptFeedItemIds, []);
		assert.deepStrictEqual(kernel.internalFeedItemIds, [
			'stale-permission',
			'stale-clarification',
			'ready',
		]);
	});

	test('runtime ergonomics kernel matches active blocking surfaces by context ref', () => {
		const body = 'Choose plan if you want Corgi to continue this request.';
		const clarificationBody = 'What should Corgi focus on?';
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeClarification: {
				id: 'clarification-new',
				contextRef: 'clarification-new',
				title: 'Clarification required',
				body: clarificationBody,
				allowFreeText: true,
				requestedAt: '2026-04-10T10:00:04.000Z',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				pendingPermissionRequest: {
					id: 'permission-new',
					contextRef: 'permission-new',
					title: 'Permission needed',
					body,
					requestedAt: '2026-04-10T10:00:03.000Z',
					recommendedScope: 'plan',
					allowedScopes: ['plan', 'execute'],
				},
			},
			feed: [
				{
					id: 'permission-old',
					type: 'permission_request',
					title: 'Permission needed',
					body,
					timestamp: '2026-04-10T10:00:00.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'permission-old', scope: 'plan' },
				},
				{
					id: 'permission-new',
					type: 'permission_request',
					title: 'Permission needed',
					body,
					timestamp: '2026-04-10T10:00:03.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'permission-new', scope: 'plan' },
				},
				{
					id: 'clarification-old',
					type: 'clarification_request',
					title: 'Clarification required',
					body: clarificationBody,
					timestamp: '2026-04-10T10:00:01.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'clarification-old' },
				},
				{
					id: 'clarification-new',
					type: 'clarification_request',
					title: 'Clarification required',
					body: clarificationBody,
					timestamp: '2026-04-10T10:00:04.000Z',
					authoritative: true,
					presentation_args: { contextRef: 'clarification-new' },
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);

		assert.deepStrictEqual(kernel.transcriptFeedItemIds, [
			'permission-new',
			'clarification-new',
		]);
		assert.deepStrictEqual(kernel.internalFeedItemIds, [
			'permission-old',
			'clarification-old',
		]);
	});

	test('runtime ergonomics kernel collapses repeated activity and names safe parallel work', () => {
		const base = createInitialModel('2026-04-10T10:00:00.000Z');
		const model: ExecutionWindowModel = {
			...base,
			activeForegroundRequestId: 'req-parallel',
			snapshot: {
				...base.snapshot,
				task: 'Build the static pet diary app.',
				currentActor: 'executor',
				currentStage: 'plan_executing',
				runState: 'running',
				currentWorkRef: 'work-pet-diary',
				currentAttemptNumber: 1,
				activeParallelDispatchCount: 2,
			},
			feed: [
				{
					id: 'executor-starting-1',
					type: 'system_status',
					title: 'Executor starting',
					body: 'Executor is starting.',
					timestamp: '2026-04-10T10:00:10.000Z',
					authoritative: true,
					in_response_to_request_id: 'req-parallel',
				},
				{
					id: 'executor-starting-2',
					type: 'system_status',
					title: 'Executor starting',
					body: 'Executor is still starting.',
					timestamp: '2026-04-10T10:00:11.000Z',
					authoritative: true,
					in_response_to_request_id: 'req-parallel',
				},
			],
		};

		const kernel = buildRuntimeErgonomicsKernel(model);
		const executorRunningEvents = kernel.activities.filter(
			(activity) => activity.summaryKey === 'executor_running'
		);

		assert.strictEqual(executorRunningEvents.length, 1);
		assert.deepStrictEqual(kernel.activityFeedItemIds, ['executor-starting-2']);
		assert.ok(kernel.internalFeedItemIds.includes('executor-starting-1'));
		assert.strictEqual(
			summaryForActivity('parallel_running', { count: 2 }),
			'2 tasks running'
		);
		assert.match(
			kernel.activities.map((activity) => activity.summary).join('\n'),
			/2 tasks running/
		);
	});

	test('webview snapshot keeps plan-ready actions compact and action-bound', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			planReadyRequest: {
				id: 'plan-ready',
				contextRef: 'plan-context-1',
				title: 'Plan ready',
				body: 'The plan is ready.',
				requestedAt: '2026-04-10T10:00:20.000Z',
				foregroundRequestId: 'req-plan',
				acceptedIntakeSummary: {
					title: 'Analyze repo',
					body: 'Analyze the repository architecture.',
				},
				allowedActions: ['execute_plan', 'revise_plan'],
				planVersion: 1,
				planContextRef: 'plan-context-1',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'governor',
				currentStage: 'plan_ready',
				permissionScope: 'plan',
				runState: 'idle',
			},
			feed: [
				{
					id: 'governor-plan',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: analyze the repository architecture.\n\nExecution readiness: plan-ready only.',
					timestamp: '2026-04-10T10:00:20.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const kernel = buildRuntimeErgonomicsKernel(model);
		const actionText = snapshot.actions.map((action) => action.text);
		const executeAction = snapshot.actions.find((action) => action.text === 'Execute plan');
		const reviseAction = snapshot.actions.find((action) => action.text === 'Revise');

		assert.match(snapshot.goalStrip, /Step: Plan ready/);
		assert.deepStrictEqual(actionText, ['Execute plan', 'Revise']);
		assert.strictEqual(kernel.primaryAction?.label, 'Execute plan');
		assert.deepStrictEqual(
			kernel.secondaryActions.map((action) => action.label),
			['Revise']
		);
		assert.ok(executeAction);
		assert.ok(!executeAction.className.includes('secondary'));
		assert.ok(reviseAction?.className.includes('secondary'));
		assert.strictEqual(snapshot.composer.context, 'Scope: Plan');
		assert.ok(!snapshot.composer.context.includes('Plan ready'));
	});

	test('webview snapshot keeps retry plan-ready state on the same goal and attempt', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			planReadyRequest: {
				id: 'plan-ready-retry',
				contextRef: 'plan-context-2',
				title: 'Plan ready',
				body: 'The revised plan is ready.',
				requestedAt: '2026-04-10T10:01:00.000Z',
				foregroundRequestId: 'req-retry',
				acceptedIntakeSummary: {
					title: 'Analyze repo',
					body: 'Analyze the repository architecture.',
				},
				allowedActions: ['execute_plan', 'revise_plan'],
				planVersion: 2,
				planContextRef: 'plan-context-2',
				workRef: 'lane/main/work-123',
				planRef: '.agent/work/lane/main/work-123/plans/plan-v2.md',
				revisionReason: 'review_requested_changes',
				latestReviewRef: '.agent/reviews/lane/main/dispatch-1/review.json',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'governor',
				currentStage: 'plan_ready',
				permissionScope: 'plan',
				runState: 'idle',
				currentWorkRef: 'lane/main/work-123',
				currentPlanVersion: 2,
				currentAttemptNumber: 1,
				latestReviewRef: '.agent/reviews/lane/main/dispatch-1/review.json',
				latestReviewVerdict: 'request_changes',
			},
			feed: [
				{
					id: 'governor-revised-plan',
					type: 'actor_event',
					title: 'Governor responded',
					body: 'Objective: revise the same repository analysis plan.\n\nExecution readiness: retry plan-ready.',
					timestamp: '2026-04-10T10:01:00.000Z',
					authoritative: true,
					source_actor: 'governor',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const actionText = snapshot.actions.map((action) => action.text);
		const visibleText = [
			snapshot.goalStrip,
			snapshot.composer.context,
			...snapshot.messages.map((message) => message.text),
			...actionText,
		].join('\n');

		assert.match(snapshot.goalStrip, /Goal: Analyze the repository architecture\./);
		assert.match(snapshot.goalStrip, /Step: Plan ready · Attempt 2/);
		assert.deepStrictEqual(actionText, ['Execute plan', 'Revise']);
		assert.strictEqual(snapshot.composer.context, 'Scope: Plan');
		assert.ok(!visibleText.includes('lane/main/work-123'));
		assert.ok(!visibleText.includes('plan-context-2'));
		assert.ok(!visibleText.includes('review_requested_changes'));
		assert.ok(!visibleText.includes('dispatch-1/review.json'));
	});

	test('webview snapshot shows compact parallel goal status without exposing refs', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Build app',
				body: 'Build the static pet diary app.',
			},
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Build the static pet diary app.',
				currentActor: 'executor',
				currentStage: 'plan_executing',
				permissionScope: 'execute',
				runState: 'running',
				activeParallelDispatchCount: 2,
				currentParallelSetRef: 'lane/work/parallel-set-1',
			},
			feed: [],
		};

		const snapshot = renderWebviewSnapshot(model);

		assert.match(snapshot.goalStrip, /Step: 2 tasks running/);
		assert.ok(!snapshot.goalStrip.includes('parallel-set-1'));
	});

	test('webview snapshot condenses dispatch queued into the goal strip instead of transcript noise', () => {
		const requestArtifact = {
			id: 'dispatch-request',
			label: 'Dispatch request',
			path: '.agent/dispatches/lane/main/dispatch-123/request.json',
			status: 'ready',
			summary: 'Dispatch request artifact',
			authoritative: true,
		};
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			activeForegroundRequestId: 'corgi-request:test:execute',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'orchestration',
				currentStage: 'dispatch_queued',
				permissionScope: 'execute',
				runState: 'queued',
				recentArtifacts: [requestArtifact],
			},
			feed: [
				{
					id: 'execute-plan-action',
					type: 'user_message',
					title: 'Permission selected',
					body: 'Execute plan',
					timestamp: '2026-04-10T10:00:25.000Z',
					authoritative: false,
					turn_type: 'permission_action',
					in_response_to_request_id: 'corgi-request:test:execute',
				},
				{
					id: 'dispatch-queued',
					type: 'system_status',
					title: 'Dispatch queued',
					body: 'Dispatch truth was created.',
					timestamp: '2026-04-10T10:00:30.000Z',
					authoritative: true,
					source_artifact_ref: requestArtifact.path,
					in_response_to_request_id: 'corgi-request:test:execute',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const messageText = snapshot.messages.map((message) => message.text).join('\n');

		assert.match(snapshot.goalStrip, /Step: Ready to write/);
		assert.match(snapshot.goalStrip, /Ready to write/);
		assert.ok(!messageText.includes('Dispatch queued'));
		assert.ok(!messageText.includes('Dispatch truth was created'));
		assert.ok(!messageText.includes('Execute plan'));
		assert.deepStrictEqual(snapshot.actions.map((action) => action.text), ['View source']);
		assert.deepStrictEqual(snapshot.progress, []);
		assert.strictEqual(snapshot.composer.context, 'Scope: Execute');
	});

	test('webview snapshot shows plan execution as active goal state', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			acceptedIntakeSummary: {
				title: 'Analyze repo',
				body: 'Analyze the repository architecture.',
			},
			activeForegroundRequestId: 'corgi-request:test:execute',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				task: 'Analyze the repository architecture.',
				currentActor: 'orchestration',
				currentStage: 'plan_executing',
				permissionScope: 'execute',
				runState: 'running',
				recentArtifacts: [],
			},
			feed: [
				{
					id: 'executor-starting',
					type: 'system_status',
					title: 'Executor starting',
					body: 'Executor is starting from the accepted plan.',
					timestamp: '2026-04-10T10:00:30.000Z',
					authoritative: true,
					in_response_to_request_id: 'corgi-request:test:execute',
				},
			],
		};

		const snapshot = renderWebviewSnapshot(model);
		const messageText = snapshot.messages.map((message) => message.text).join('\n');

		assert.match(snapshot.goalStrip, /Step: Writing/);
		assert.match(snapshot.goalStrip, /Running/);
		assert.ok(!messageText.includes('Executor starting'));
		assert.strictEqual(snapshot.composer.context, 'Scope: Execute');
	});

	test('webview transcript treats requests as assistant replies and separates new turns', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
		const webviewSource = readExecutionWindowSource();

		assert.ok(html.includes('feed-divider'));
		assert.ok(html.includes('Current turn'));
		assert.ok(html.includes('initialFeedCount'));
		assert.ok(html.includes('composerContext'));
		assert.ok(html.includes('composerActions'));
		assert.ok(html.includes('goal-strip'));
		assert.ok(html.includes('runtimeGoalDisplay'));
		assert.ok(html.includes('runtimeActionLabel'));
		assert.ok(html.includes('goalStrip: compactText'));
		assert.ok(html.includes('View source'));
		assert.ok(html.includes('foregroundRequest'));
		assert.ok(html.includes('Interpreting request'));
		assert.ok(html.includes('Checking workflow state'));
		assert.ok(html.includes('normalizeUiText'));
		assert.ok(html.includes('[hidden]'));
		assert.ok(html.includes('display: none !important;'));
		assert.ok(html.includes('latestRenderedAssistantItem'));
		assert.ok(html.includes('requestId'));
		assert.ok(html.includes("type: 'submit_prompt', text, requestId"));
		assert.ok(html.includes("type: 'set_permission_scope'"));
		assert.ok(html.includes('permissionScope: scope'));
		assert.ok(html.includes('progress-bullet-text'));
		assert.ok(html.includes('@keyframes progressShimmer'));
		assert.ok(!html.includes('@keyframes progressDotPulse'));
		assert.ok(html.includes("ui.foregroundRequest.bullets = ui.foregroundRequest.bullets.map"));
		assert.ok(html.includes('function latestRequestActorEvent(requestKey)'));
		assert.ok(html.includes("if (item.type === 'permission_request')"));
		assert.ok(html.includes("if (item.type === 'clarification_request')"));
		assert.ok(html.includes('Scope: '));
		assert.ok(html.includes('Waiting for clarification'));
		assert.ok(html.includes('Waiting for permission: '));
		assert.ok(html.includes('Ready to write'));
		assert.ok(html.includes('latestDispatchQueuedStatus'));
		assert.ok(html.includes('latestPostExecutionStatus'));
		assert.ok(
			webviewSource.indexOf('const latestTerminalStatus = latestPostExecutionStatus(requestKey);') <
				webviewSource.indexOf('if (isDispatchQueued(snapshot) || latestDispatchQueuedStatus(requestKey))')
		);
		assert.ok(html.includes("snapshot.runState === 'queued'"));
		assert.ok(webviewSource.includes('Risks?\\\\s+or\\\\s+unknowns'));
		assert.ok(webviewSource.includes("replace(/(^|[.!?])\\\\s+(Unknowns[:]?)/gi"));
		assert.ok(html.includes('Permission needed'));
		assert.ok(html.includes('set_permission_scope'));
		assert.ok(html.includes('data-permission-scope'));
		assert.ok(html.includes('promptHistory: []'));
		assert.ok(html.includes("event.key === 'ArrowUp'"));
		assert.ok(html.includes('const hasActionSurface = Boolean('));
		assert.ok(html.includes("composerSubmitButton.textContent = busy ? 'Sending...' : mode.buttonLabel;"));
		assert.ok(!html.includes('request-marker'));
		assert.ok(!html.includes('renderRequestMarker'));
		assert.ok(!html.includes("return renderRequestMarker(item);"));
		assert.ok(!html.includes('Open</button>'));
		assert.ok(!html.includes('Reveal</button>'));
		assert.ok(!html.includes('Copy path</button>'));
		assert.ok(!html.includes('const latestItem = model.feed[model.feed.length - 1];'));
		assert.ok(!html.includes('<h1 class="header-title">Corgi</h1>'));
		assert.ok(!html.includes('<div class="brand-mark">C</div>'));
		assert.ok(!html.includes('<div class="message-label">Corgi</div>'));
		assert.ok(!html.includes('action-card'));
		assert.ok(!html.includes('Run controls'));
		assert.ok(html.includes("transportState === 'disconnected'"));
		assert.ok(
			html.includes(
				'Open the repo/workspace folder that contains orchestration/scripts/orchestrate.py, then reopen Corgi.'
			)
		);
		assert.ok(html.includes('const shouldResetPersistedState = false;'));
	});

	test('webview reports structured monitor snapshots without screenshots', () => {
		const webviewSource = readExecutionWindowSource();
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');
		const autoHtml = getExecutionWindowHtml(
			'vscode-webview-resource://test',
			'nonce-for-test',
			false,
			'plan'
		);

		assert.ok(webviewSource.includes("type: 'webview_snapshot'"));
		assert.ok(webviewSource.includes('corgi_webview_snapshot.json'));
		assert.ok(webviewSource.includes('removeOldWebviewSnapshotFiles'));
		assert.ok(webviewSource.includes('fs.renameSync(tempSnapshotPath, snapshotPath)'));
		assert.ok(webviewSource.includes("filename.startsWith('corgi_webview_snapshot')"));
		assert.ok(!webviewSource.includes('corgi_webview_snapshot.txt'));
		assert.ok(webviewSource.includes('this.context.extensionMode === vscode.ExtensionMode.Development'));
		assert.ok(webviewSource.includes('this.workspaceRoot ?? this.context.extensionUri'));
		assert.ok(webviewSource.includes('monitorSessionStartedAt'));
		assert.ok(webviewSource.includes('shouldReplaceWebviewSnapshot'));
		assert.ok(webviewSource.includes('isLatestWebviewSnapshot'));
		assert.ok(webviewSource.includes('existing.monitorSessionStartedAt === undefined'));
		assert.ok(webviewSource.includes('candidateSession < existingSession'));
		assert.ok(webviewSource.includes('candidateRenderedAt >= existingRenderedAt'));
		assert.ok(html.includes('function collectWebviewSnapshot(reason)'));
		assert.ok(html.includes('function cloneForSnapshot(value)'));
			assert.ok(html.includes("type: 'webview_snapshot'"));
			assert.ok(html.includes('messages: collectTextRows(feed'));
			assert.ok(html.includes('transcript: collectTextRows(feed'));
			assert.ok(html.includes('activity: collectTextRows(feed'));
			assert.ok(html.includes('detailsHidden:'));
			assert.ok(html.includes("actions: collectTextRows(composerActions, 'button')"));
			assert.ok(html.includes('model: {'));
		assert.ok(html.includes('feed: cloneForSnapshot(feedItems)'));
		assert.ok(html.includes('activeClarification: cloneForSnapshot(model?.activeClarification)'));
		assert.ok(html.includes('autoStep: {'));
		assert.ok(autoHtml.includes('const testWindowAutoStepMode = "plan";'));
		assert.ok(autoHtml.includes('function scheduleTestWindowAutoStep(reason)'));
		assert.ok(autoHtml.includes('button[data-clarification-answer]'));
		assert.ok(autoHtml.includes('button[data-action="set_permission_scope"]'));
		assert.ok(!html.toLowerCase().includes('screenshot'));
		assert.ok(!html.includes('toDataURL'));
	});

	test('webview can reset persisted state for development launches', () => {
		const html = getExecutionWindowHtml(
			'vscode-webview-resource://test',
			'nonce-for-test',
			true
		);

		assert.ok(html.includes('const shouldResetPersistedState = true;'));
		assert.ok(html.includes('vscode.setState(defaultPersistedState);'));
	});

	test('webview removes the current work panel and keeps context in the goal strip', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');

		assert.ok(!html.includes('<section class="session-rail" id="sessionRail"></section>'));
		assert.ok(!html.includes('data-action="toggle_rail"'));
		assert.ok(html.includes('class="goal-strip" id="headerContent"'));
		assert.ok(html.includes('<span class="goal-label">Goal:</span>'));
		assert.ok(html.includes('<span class="goal-label">Step:</span>'));
		assert.ok(html.includes('<span class="status-dot '));
		assert.ok(!html.includes('Lane: '));
		assert.ok(!html.includes('Branch: '));
	});

	test('plan-ready header stays calm even after snapshot freshness ages', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');

		assert.ok(html.includes('model?.planReadyRequest'));
		assert.ok(html.includes("return 'Plan ready';"));
		assert.ok(html.includes("return 'is-ready';"));
		assert.ok(html.includes('statusDotClass(snapshot, stale)'));
	});

	test('active clarification keeps the composer answerable while progress is live', () => {
		const html = getExecutionWindowHtml('vscode-webview-resource://test', 'nonce-for-test');

		assert.ok(html.includes("ui.foregroundRequest.status === 'live'"));
		assert.ok(html.includes('!model?.activeClarification'));
		assert.ok(html.includes("buttonLabel: 'Answer'"));
	});

	test('plan permission accepts intake and returns a Governor planning response', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-plan',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const runningModel = applyModelAction(approvalModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: approvalModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-permission-click',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(runningModel.snapshot.currentActor, 'governor');
		assert.strictEqual(runningModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(runningModel.snapshot.runState, 'idle');
		assert.strictEqual(runningModel.snapshot.permissionScope, 'plan');
		assert.ok(runningModel.acceptedIntakeSummary);
		assert.ok(runningModel.planReadyRequest);
		assert.strictEqual(runningModel.planReadyRequest.foregroundRequestId, 'req-plan');
		assert.deepStrictEqual(runningModel.planReadyRequest.allowedActions, [
			'execute_plan',
			'revise_plan',
		]);
		assert.ok(runningModel.snapshot.recentArtifacts.length >= 2);
		assert.ok(getArtifactById(runningModel, 'artifact-orchestration-readme'));
		assert.ok(!runningModel.feed.some((item) => item.type === 'artifact_reference'));
		const lastItem = runningModel.feed[runningModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'actor_event');
		assert.strictEqual(lastItem.source_actor, 'governor');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-plan');
		assert.match(lastItem.body ?? '', /Plan scope/);
		assert.match(lastItem.body ?? '', /Risks or unknowns/);
		assert.match(lastItem.body ?? '', /src\/executionWindowPanel\.ts/);
		assert.match(lastItem.body ?? '', /orchestration\/harness\/session\.py/);
	});

	test('execute plan action authorizes execute and queues dispatch without a second permission click', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on bugs, regressions, and architectural risks.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const continuationModel = applyModelAction(planReadyModel, {
			type: 'execute_plan',
			context_ref: planReadyModel.planReadyRequest?.contextRef,
			request_id: 'req-do-it',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(continuationModel.activeClarification, undefined);
		assert.strictEqual(continuationModel.snapshot.permissionScope, 'execute');
		assert.strictEqual(continuationModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(continuationModel.snapshot.currentStage, 'plan_executing');
		assert.strictEqual(continuationModel.snapshot.runState, 'queued');
		assert.strictEqual(continuationModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(
			!continuationModel.feed.some(
				(item) =>
					item.type === 'permission_request' &&
					item.in_response_to_request_id === 'req-do-it'
			)
		);
		assert.ok(
			!continuationModel.feed.some((item) =>
				item.in_response_to_request_id === 'req-do-it' &&
				/permission needed|choose execute/i.test(`${item.title ?? ''}\n${item.body ?? ''}`)
			)
		);
		assert.ok(continuationModel.acceptedIntakeSummary);
		assert.strictEqual(continuationModel.planReadyRequest, undefined);
		assert.ok(!continuationModel.feed.some((item) => item.type === 'clarification_request' && item.in_response_to_request_id === 'req-do-it'));
		const lastItem = continuationModel.feed[continuationModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'system_status');
		assert.strictEqual(lastItem.title, 'Executor starting');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-do-it');
	});

	test('optimistic execute plan state does not expose stop before authoritative running state', () => {
		const model: ExecutionWindowModel = {
			...createInitialModel('2026-04-10T10:00:00.000Z'),
			activeForegroundRequestId: 'req-do-it',
			snapshot: {
				...createInitialModel('2026-04-10T10:00:00.000Z').snapshot,
				currentActor: 'orchestration',
				currentStage: 'plan_executing',
				permissionScope: 'execute',
				runState: 'queued',
			},
		};

		const snapshot = renderWebviewSnapshot(model);

		assert.ok(!snapshot.actions.some((action) => action.text === 'Stop'));
	});

	test('execute plan action with stale context fails closed', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const failedModel = applyModelAction(planReadyModel, {
			type: 'execute_plan',
			context_ref: 'stale-plan-context',
			request_id: 'req-stale-execute',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(failedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(failedModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(failedModel.planReadyRequest);
		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.presentation_key, 'error.stale_context');
	});

	test('execute plan action without accepted intake fails with specific plan error', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const failedModel = applyModelAction(
			{
				...planReadyModel,
				acceptedIntakeSummary: undefined,
			},
			{
				type: 'execute_plan',
				context_ref: planReadyModel.planReadyRequest?.contextRef,
				request_id: 'req-missing-intake-execute',
				now: '2026-04-10T10:00:20.000Z',
			}
		);

		assert.strictEqual(failedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(failedModel.snapshot.permissionScope, 'plan');
		assert.ok(failedModel.planReadyRequest);
		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.title, 'Accepted intake missing');
		assert.strictEqual(lastItem.presentation_key, 'error.plan_not_ready');
		assert.deepStrictEqual(lastItem.presentation_args, { reason: 'missing_intake' });
	});

	test('execute plan action without request id fails closed', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const failedModel = applyModelAction(planReadyModel, {
			type: 'execute_plan',
			context_ref: planReadyModel.planReadyRequest?.contextRef,
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(failedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(failedModel.snapshot.permissionScope, 'plan');
		assert.strictEqual(failedModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(failedModel.planReadyRequest);
		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.title, 'Request id required');
		assert.strictEqual(lastItem.presentation_key, 'error.stale_context');
	});

	test('plan revision action stays in governor planning mode without starting execution', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Analyze the repo.',
			semantic_route_type: 'governed_work_intent',
			request_id: 'req-analyze',
			now: '2026-04-10T10:00:05.000Z',
		});
		const clarificationModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Focus on architecture, structure, and subsystem boundaries.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const planReadyModel = applyModelAction(clarificationModel, {
			type: 'set_permission_scope',
			permission_scope: 'plan',
			context_ref: clarificationModel.snapshot.pendingPermissionRequest?.contextRef,
			request_id: 'req-plan-click',
			now: '2026-04-10T10:00:15.000Z',
		});
		const revisedModel = applyModelAction(planReadyModel, {
			type: 'revise_plan',
			text: 'Also explain the testing risks before execution.',
			context_ref: planReadyModel.planReadyRequest?.contextRef,
			request_id: 'req-revise-plan',
			now: '2026-04-10T10:00:20.000Z',
		});

		assert.strictEqual(revisedModel.snapshot.permissionScope, 'plan');
		assert.strictEqual(revisedModel.snapshot.currentActor, 'governor');
		assert.strictEqual(revisedModel.snapshot.currentStage, 'plan_ready');
		assert.strictEqual(revisedModel.snapshot.runState, 'idle');
		assert.strictEqual(revisedModel.snapshot.pendingPermissionRequest, undefined);
		assert.ok(revisedModel.planReadyRequest);
		assert.notStrictEqual(
			revisedModel.planReadyRequest.contextRef,
			planReadyModel.planReadyRequest?.contextRef
		);
		assert.strictEqual(
			revisedModel.planReadyRequest.planVersion,
			(planReadyModel.planReadyRequest?.planVersion ?? 1) + 1
		);
		const lastItem = revisedModel.feed[revisedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'actor_event');
		assert.strictEqual(lastItem.source_actor, 'governor');
		assert.strictEqual(lastItem.in_response_to_request_id, 'req-revise-plan');
		assert.match(lastItem.body ?? '', /revise the current plan/i);
	});

	test('execute permission accepts the draft and queues dispatch truth', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const runningModel = applyModelAction(approvalModel, {
			type: 'set_permission_scope',
			permission_scope: 'execute',
			context_ref: approvalModel.snapshot.pendingPermissionRequest?.contextRef,
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(runningModel.snapshot.permissionScope, 'execute');
		assert.strictEqual(runningModel.snapshot.runState, 'queued');
		assert.strictEqual(runningModel.snapshot.currentActor, 'orchestration');
		assert.strictEqual(runningModel.snapshot.currentStage, 'dispatch_queued');
		assert.ok(runningModel.acceptedIntakeSummary?.body.includes('Execute permission'));
	});

	test('declining a permission request leaves scope unchanged and blocks the request', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const permissionModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const declinedModel = applyModelAction(permissionModel, {
			type: 'decline_permission',
			context_ref: permissionModel.snapshot.pendingPermissionRequest?.contextRef,
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.strictEqual(declinedModel.snapshot.permissionScope, 'unset');
		assert.strictEqual(declinedModel.snapshot.pendingPermissionRequest, undefined);
		assert.strictEqual(declinedModel.snapshot.currentStage, 'permission_declined');
	});

	test('state-bound actions fail closed when the context token is stale', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});

		const failedModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: 'clarification-context-stale',
			request_id: 'corgi-request:test-stale',
			now: '2026-04-10T10:00:10.000Z',
		});

		const lastItem = failedModel.feed[failedModel.feed.length - 1];
		assert.strictEqual(lastItem.type, 'error');
		assert.strictEqual(lastItem.in_response_to_request_id, 'corgi-request:test-stale');
		assert.match(lastItem.body ?? '', /clarification changed/i);
	});

	test('new prompts supersede a pending permission request instead of holding it', () => {
		const promptModel = applyModelAction(createInitialModel('2026-04-10T10:00:00.000Z'), {
			type: 'submit_prompt',
			text: 'Build a compact execution window for phase 1.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:05.000Z',
		});
		const approvalModel = applyModelAction(promptModel, {
			type: 'answer_clarification',
			text: 'Keep current actor and current stage visible.',
			context_ref: promptModel.activeClarification?.contextRef,
			now: '2026-04-10T10:00:10.000Z',
		});
		const supersededModel = applyModelAction(approvalModel, {
			type: 'submit_prompt',
			text: 'Start over with a quieter transcript.',
			semantic_route_type: 'governed_work_intent',
			now: '2026-04-10T10:00:15.000Z',
		});

		assert.ok(
			supersededModel.feed.some(
				(item) =>
					item.type === 'system_status' &&
					item.title === 'Pending permission request superseded'
			)
		);
	});

});
