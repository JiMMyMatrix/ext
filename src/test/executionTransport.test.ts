import * as assert from 'assert';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import {
	createExecutionTransport,
	resolveGovernorRoute,
	resolveExecutionTransportTarget,
	TransportUnavailableError,
} from '../executionTransport';
import {
	CODEX_APP_SERVER_CLIENT_TS_PATH,
	EXECUTION_TRANSPORT_TS_PATH,
	GOVERNOR_RUNTIME_TS_PATH,
} from './testPaths';

suite('Corgi Execution Transport', () => {
	test('transport gates app-server runtime behind selector and completes or falls back internally', () => {
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');

		assert.ok(transportSource.includes('CORGI_GOVERNOR_RUNTIME'));
		assert.ok(transportSource.includes('--semantic-mode'));
		assert.ok(transportSource.includes('prewarm()'));
		assert.ok(transportSource.includes('onRuntimeEvent'));
		assert.ok(transportSource.includes('model?: ExecutionWindowModel'));
		assert.ok(transportSource.includes('this.handleGovernorRuntimeResponse(result.request, result.model, elapsedMs)'));
		assert.ok(transportSource.includes('model: preparedModel'));
		assert.ok(transportSource.includes('orchestration_command_started'));
		assert.ok(transportSource.includes('orchestration_command_completed'));
		assert.ok(transportSource.includes('totalElapsedMs'));
		assert.ok(transportSource.includes('governorPromptLengthForRequest'));
		assert.ok(transportSource.includes("get<string>('governorRuntime')"));
		assert.ok(transportSource.includes("configured === 'exec' ? 'exec' : 'app-server'"));
		assert.ok(transportSource.includes("'--governor-runtime', 'external'"));
		assert.ok(transportSource.includes("'complete-governor-turn'"));
		assert.ok(transportSource.includes('const completed = await this.runRaw'));
		assert.ok(transportSource.includes('isGovernorRuntimeResponse(completed)'));
		assert.ok(transportSource.includes("'fail-governor-turn'"));
		assert.ok(transportSource.includes('isAppServerShutdownReason'));
		assert.ok(transportSource.includes('isGovernorRuntimeResponse'));
	});

	test('Governor runtime route resolution is explicit and action-bound', () => {
		for (const command of [
			'submit-prompt',
			'answer-clarification',
			'set-permission-scope',
			'execute-plan',
			'revise-plan',
		]) {
			assert.strictEqual(resolveGovernorRoute(command, 'app-server'), 'external');
		}
		for (const command of [
			'decline-permission',
			'interrupt',
			'reconnect',
			'state',
		]) {
			assert.strictEqual(resolveGovernorRoute(command, 'app-server'), 'exec');
		}
		assert.strictEqual(resolveGovernorRoute('submit-prompt', 'exec'), 'exec');
	});

	test('development app-server runtime uses ephemeral threads for clean test launches', () => {
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');
		const clientSource = fs.readFileSync(CODEX_APP_SERVER_CLIENT_TS_PATH, 'utf8');
		const runtimeSource = fs.readFileSync(GOVERNOR_RUNTIME_TS_PATH, 'utf8');

		assert.ok(
			transportSource.includes(
				'developmentMode: extensionMode === vscode.ExtensionMode.Development'
			)
		);
		assert.ok(transportSource.includes('CORGI_APP_SERVER_EPHEMERAL'));
		assert.ok(runtimeSource.includes('ephemeralThreads'));
		assert.ok(runtimeSource.includes('this.options.ephemeralThreads'));
		assert.ok(runtimeSource.includes('isUnavailableAppServerThreadError'));
		assert.ok(clientSource.includes('ephemeral: request.ephemeralThread'));
	});

	test('transport selection resolves the real orchestration workspace when available', () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Development,
			vscode.Uri.file(path.resolve(__dirname, '../..')),
			vscode.Uri.file('/tmp/not-used-because-workspace-wins')
		);

		assert.strictEqual(target.kind, 'orchestration');
		if (target.kind === 'orchestration') {
			assert.ok(target.scriptPath.endsWith('orchestration/scripts/orchestrate.py'));
			assert.strictEqual(target.source, 'workspace');
		}
	});

	test('transport prefers configured or Homebrew Python before system python', () => {
		const transportSource = fs.readFileSync(EXECUTION_TRANSPORT_TS_PATH, 'utf8');
		const testRunnerSource = fs.readFileSync(
			path.resolve(__dirname, '../../scripts/run-orchestration-tests.cjs'),
			'utf8'
		);

		for (const source of [transportSource, testRunnerSource]) {
			assert.ok(source.includes('CORGI_PYTHON'));
			assert.ok(source.includes('/opt/homebrew/bin/python3'));
			assert.ok(source.includes('/usr/local/bin/python3'));
		}
		assert.ok(transportSource.includes('this.pythonExecutable'));
		assert.ok(transportSource.includes('ORCHESTRATION_APPROVED_PYTHON'));
		assert.ok(transportSource.includes('--auto-consume-executor'));
		assert.match(
			transportSource,
			/action\?\.type === 'execute_plan'[\s\S]{0,120}args\.push\('--auto-consume-executor'\)/
		);
	});

	test('transport selection falls back to the development extension repo when no workspace is open', async () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Development,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		assert.strictEqual(target.kind, 'orchestration');
		if (target.kind === 'orchestration') {
			assert.strictEqual(target.source, 'extension_dev');
		}

		const transport = createExecutionTransport(
			vscode.ExtensionMode.Development,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		await assert.doesNotReject(() => transport.load());
	});

	test('development transport can run source orchestration against a scratch workspace', async () => {
		const scratchWorkspace = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-scratch-workspace-'));
		try {
			const target = resolveExecutionTransportTarget(
				vscode.ExtensionMode.Development,
				vscode.Uri.file(scratchWorkspace),
				vscode.Uri.file(path.resolve(__dirname, '../..'))
			);
			assert.strictEqual(target.kind, 'orchestration');
			if (target.kind === 'orchestration') {
				assert.strictEqual(target.source, 'extension_dev');
				assert.strictEqual(target.cwd, scratchWorkspace);
				assert.strictEqual(target.sourceRoot, path.resolve(__dirname, '../..'));
				assert.ok(target.scriptPath.endsWith('orchestration/scripts/orchestrate.py'));
			}
		} finally {
			fs.rmSync(scratchWorkspace, { recursive: true, force: true });
		}
	});

	test('transport selection fails closed in production when no workspace is open', async () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Production,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		assert.strictEqual(target.kind, 'unavailable');
		if (target.kind === 'unavailable') {
			assert.strictEqual(target.title, 'Real orchestration workspace required');
		}

		const transport = createExecutionTransport(
			vscode.ExtensionMode.Production,
			undefined,
			vscode.Uri.file(path.resolve(__dirname, '../..'))
		);
		await assert.rejects(
			() => transport.load(),
			(error: unknown) =>
				error instanceof TransportUnavailableError &&
				error.title === 'Real orchestration workspace required'
		);
	});

	test('transport selection fails closed in production when workspace lacks orchestration support', () => {
		const scratchWorkspace = fs.mkdtempSync(path.join(os.tmpdir(), 'corgi-prod-workspace-'));
		try {
			const target = resolveExecutionTransportTarget(
				vscode.ExtensionMode.Production,
				vscode.Uri.file(scratchWorkspace),
				vscode.Uri.file(path.resolve(__dirname, '../..'))
			);
			assert.strictEqual(target.kind, 'unavailable');
			if (target.kind === 'unavailable') {
				assert.strictEqual(target.title, 'Orchestration CLI not found');
			}
		} finally {
			fs.rmSync(scratchWorkspace, { recursive: true, force: true });
		}
	});

	test('transport selection fails closed when neither workspace nor development repo contains orchestrate', async () => {
		const target = resolveExecutionTransportTarget(
			vscode.ExtensionMode.Development,
			undefined,
			vscode.Uri.file('/tmp/corgi-missing-root')
		);
		assert.strictEqual(target.kind, 'unavailable');
		if (target.kind === 'unavailable') {
			assert.strictEqual(target.title, 'Real orchestration workspace required');
		}
	});
});
