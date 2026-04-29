import { execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import {
	AppServerGovernorRuntime,
	type GovernorRuntime,
	type GovernorRuntimeRequest,
} from './governorRuntime';
import { type ExecutionWindowModel, type ModelAction } from './phase1Model';

export interface ExecutionTransport {
	load(): Promise<ExecutionWindowModel>;
	dispatch(action: ModelAction): Promise<ExecutionWindowModel>;
	dispose?(): void;
}

export class TransportUnavailableError extends Error {
	public readonly title: string;
	public readonly details: string[];

	constructor(title: string, body: string, details: string[] = []) {
		super(body);
		this.name = 'TransportUnavailableError';
		this.title = title;
		this.details = details;
	}
}

export type ExecutionTransportTarget =
	| {
			kind: 'orchestration';
			cwd: string;
			scriptPath: string;
			source: 'workspace' | 'extension_dev';
	  }
	| {
			kind: 'unavailable';
			title: string;
			body: string;
			details: string[];
	  };

function resolvePythonExecutable(): string {
	const configuredPython = process.env.CORGI_PYTHON?.trim();
	if (configuredPython) {
		return configuredPython;
	}

	if (process.platform === 'darwin') {
		for (const candidate of ['/opt/homebrew/bin/python3', '/usr/local/bin/python3']) {
			if (fs.existsSync(candidate)) {
				return candidate;
			}
		}
	}

	return 'python3';
}

function orchestrationTarget(
	rootPath: string,
	source: 'workspace' | 'extension_dev'
): Extract<ExecutionTransportTarget, { kind: 'orchestration' }> {
	return {
		kind: 'orchestration',
		cwd: rootPath,
		scriptPath: path.join(rootPath, 'orchestration', 'scripts', 'orchestrate.py'),
		source,
	};
}

function missingWorkspaceTarget(): ExecutionTransportTarget {
	return {
		kind: 'unavailable',
		title: 'Real orchestration workspace required',
		body: 'Corgi needs an open workspace folder that contains orchestration/scripts/orchestrate.py before it can run.',
		details: [
			'Open the repo/workspace folder that contains orchestration/scripts/orchestrate.py.',
			'Reload or reopen the Corgi sidebar after the workspace is available.',
		],
	};
}

function missingOrchestrationTarget(workspaceRoot: vscode.Uri): ExecutionTransportTarget {
	return {
		kind: 'unavailable',
		title: 'Orchestration CLI not found',
		body: `The current workspace does not contain orchestration/scripts/orchestrate.py under ${workspaceRoot.fsPath}.`,
		details: [
			'Open the repo/workspace folder that contains orchestration/scripts/orchestrate.py.',
			'If you are testing seeded state, load the scenario into that same repo and then reopen Corgi.',
		],
	};
}

export function resolveExecutionTransportTarget(
	extensionMode: vscode.ExtensionMode,
	workspaceRoot: vscode.Uri | undefined,
	extensionUri?: vscode.Uri
): ExecutionTransportTarget {
	if (workspaceRoot) {
		const workspaceTarget = orchestrationTarget(workspaceRoot.fsPath, 'workspace');
		if (fs.existsSync(workspaceTarget.scriptPath)) {
			return workspaceTarget;
		}
		return missingOrchestrationTarget(workspaceRoot);
	}

	if (
		extensionMode === vscode.ExtensionMode.Development &&
		extensionUri
	) {
		const extensionTarget = orchestrationTarget(
			extensionUri.fsPath,
			'extension_dev'
		);
		if (fs.existsSync(extensionTarget.scriptPath)) {
			return extensionTarget;
		}
	}

	return missingWorkspaceTarget();
}

class UnavailableExecutionTransport implements ExecutionTransport {
	private readonly error: TransportUnavailableError;

	constructor(target: Extract<ExecutionTransportTarget, { kind: 'unavailable' }>) {
		this.error = new TransportUnavailableError(
			target.title,
			target.body,
			target.details
		);
	}

	public async load(): Promise<ExecutionWindowModel> {
		throw this.error;
	}

	public async dispatch(_action: ModelAction): Promise<ExecutionWindowModel> {
		throw this.error;
	}
}

class OrchestrationExecutionTransport implements ExecutionTransport {
	private readonly scriptPath: string;
	private readonly cwd: string;
	private readonly pythonExecutable: string;
	private readonly governorRuntimeMode: 'exec' | 'app-server';
	private readonly useEphemeralAppServerThreads: boolean;
	private appServerRuntime: GovernorRuntime | undefined;
	private disposed = false;

	constructor(
		target: Extract<ExecutionTransportTarget, { kind: 'orchestration' }>,
		options: { developmentMode: boolean }
	) {
		this.cwd = target.cwd;
		this.scriptPath = target.scriptPath;
		this.pythonExecutable = resolvePythonExecutable();
		this.governorRuntimeMode = resolveGovernorRuntimeMode();
		this.useEphemeralAppServerThreads =
			options.developmentMode || process.env.CORGI_APP_SERVER_EPHEMERAL === '1';
	}

	public async load(): Promise<ExecutionWindowModel> {
		return this.run('session', 'state');
	}

	public async dispatch(action: ModelAction): Promise<ExecutionWindowModel> {
		switch (action.type) {
			case 'submit_prompt':
				return this.run('session', 'submit-prompt', action);
			case 'answer_clarification':
				return this.run('session', 'answer-clarification', action);
			case 'set_permission_scope':
				return this.run('session', 'set-permission-scope', action);
			case 'decline_permission':
				return this.run('session', 'decline-permission', action);
			case 'execute_plan':
				return this.run('session', 'execute-plan', action);
			case 'revise_plan':
				return this.run('session', 'revise-plan', action);
			case 'interrupt_run':
				return this.run('session', 'interrupt', action);
			case 'reconnect':
				return this.run('session', 'reconnect', action);
		}
	}

	public dispose(): void {
		this.disposed = true;
		this.appServerRuntime?.shutdown();
	}

	private async run(group: string, command: string, action?: ModelAction): Promise<ExecutionWindowModel> {
		const result = await this.runRaw(group, command, action);
		if (isGovernorRuntimeResponse(result)) {
			return this.handleGovernorRuntimeResponse(result.request);
		}
		return result as ExecutionWindowModel;
	}

	private runRaw(
		group: string,
		command: string,
		action?: ModelAction,
		extraArgs: string[] = []
	): Promise<unknown> {
		const args = [this.scriptPath, group, command];
		if (action && 'text' in action && typeof action.text === 'string') {
			args.push('--text', action.text);
		}
		if (action?.request_id) {
			args.push('--request-id', action.request_id);
		}
		if (action?.session_ref) {
			args.push('--session-ref', action.session_ref);
		}
		if (action?.context_ref) {
			args.push('--context-ref', action.context_ref);
		}
		if (action?.type === 'set_permission_scope') {
			args.push('--permission-scope', action.permission_scope);
		}
		if (action && 'semantic_mode' in action && action.semantic_mode) {
			args.push('--semantic-mode', action.semantic_mode);
		}
		if (action && action.type !== 'reconnect' && 'semantic_route_type' in action) {
			if (action.semantic_route_type) {
				switch (action.semantic_route_type) {
					case 'governed_work_intent':
					case 'governor_dialogue':
					case 'clarification_reply':
						args.push('--turn-type', action.semantic_route_type);
						break;
					case 'explicit_action':
						args.push(
							'--turn-type',
							action.type === 'interrupt_run' ? 'stop_action' : 'permission_action'
						);
						break;
				}
				args.push('--semantic-route-type', action.semantic_route_type);
			}
			if (action.semantic_normalized_text) {
				args.push('--normalized-text', action.semantic_normalized_text);
			}
			if (action.semantic_paraphrase) {
				args.push('--paraphrase', action.semantic_paraphrase);
			}
			if (action.semantic_input_version) {
				args.push('--semantic-input-version', action.semantic_input_version);
			}
			if (action.semantic_summary_ref) {
				args.push('--semantic-summary-ref', action.semantic_summary_ref);
			}
			if (action.semantic_context_flags) {
				args.push(
					'--semantic-context-flags-json',
					JSON.stringify(action.semantic_context_flags)
				);
			}
			if (action.semantic_confidence) {
				args.push('--semantic-confidence', action.semantic_confidence);
			}
			if (action.semantic_block_reason) {
				args.push('--semantic-block-reason', action.semantic_block_reason);
			}
		}
		if (this.shouldUseExternalGovernor(command)) {
			args.push('--governor-runtime', 'external');
		}
		args.push(...extraArgs);

		return new Promise((resolve, reject) => {
			execFile(
				this.pythonExecutable,
				args,
				{
					cwd: this.cwd,
					env: {
						...process.env,
						ORCHESTRATION_REPO_ROOT: this.cwd,
					},
					maxBuffer: 1024 * 1024,
				},
				(error, stdout, stderr) => {
					if (error) {
						const detail = stderr.trim() || stdout.trim() || error.message;
						reject(new Error(detail));
						return;
					}

					try {
						resolve(JSON.parse(stdout) as unknown);
					} catch (parseError) {
						reject(
							new Error(
								parseError instanceof Error
									? parseError.message
									: 'Failed to parse orchestration state.'
							)
						);
					}
				}
			);
		});
	}

	private shouldUseExternalGovernor(command: string): boolean {
		return (
			this.governorRuntimeMode === 'app-server' &&
			[
				'submit-prompt',
				'answer-clarification',
				'set-permission-scope',
				'revise-plan',
			].includes(command)
		);
	}

	private async handleGovernorRuntimeResponse(
		request: GovernorRuntimeRequest
	): Promise<ExecutionWindowModel> {
		const runtime = this.getAppServerRuntime();
		try {
			const result = await runtime.sendDialogueTurn(request, this.cwd);
			return (await this.runRaw(
				'session',
				'complete-governor-turn',
				undefined,
				[
					'--runtime-request-id',
					request.runtimeRequestId,
					'--body',
					result.body,
					'--runtime-source',
					result.runtimeSource,
					...(result.threadId ? ['--thread-id', result.threadId] : []),
					...(result.turnId ? ['--turn-id', result.turnId] : []),
					...(result.itemId ? ['--item-id', result.itemId] : []),
				]
			)) as ExecutionWindowModel;
		} catch (error) {
			const reason = error instanceof Error ? error.message : String(error);
			if (this.disposed || isAppServerShutdownReason(reason)) {
				return (await this.runRaw('session', 'state')) as ExecutionWindowModel;
			}
			return (await this.runRaw(
				'session',
				'fallback-governor-turn',
				undefined,
				[
					'--runtime-request-id',
					request.runtimeRequestId,
					'--reason',
					reason,
				]
			)) as ExecutionWindowModel;
		}
	}

	private getAppServerRuntime(): GovernorRuntime {
		this.appServerRuntime ??= new AppServerGovernorRuntime({
			ephemeralThreads: this.useEphemeralAppServerThreads,
		});
		return this.appServerRuntime;
	}
}

function isAppServerShutdownReason(reason: string): boolean {
	return reason.includes('app-server client shutting down');
}

function resolveGovernorRuntimeMode(): 'exec' | 'app-server' {
	const envMode = process.env.CORGI_GOVERNOR_RUNTIME?.trim();
	if (envMode === 'app-server' || envMode === 'exec') {
		return envMode;
	}
	if (typeof vscode.workspace.getConfiguration !== 'function') {
		return 'app-server';
	}
	const configured = vscode.workspace
		.getConfiguration('corgi')
		.get<string>('governorRuntime');
	return configured === 'exec' ? 'exec' : 'app-server';
}

type GovernorRuntimeResponse = {
	kind: 'governor_runtime_request';
	model: ExecutionWindowModel;
	request: GovernorRuntimeRequest;
};

function isGovernorRuntimeResponse(value: unknown): value is GovernorRuntimeResponse {
	const payload = value as Partial<GovernorRuntimeResponse> | undefined;
	return (
		typeof payload === 'object' &&
		payload !== null &&
		payload.kind === 'governor_runtime_request' &&
		typeof payload.request?.runtimeRequestId === 'string'
	);
}

export function createExecutionTransport(
	extensionMode: vscode.ExtensionMode,
	workspaceRoot: vscode.Uri | undefined,
	extensionUri?: vscode.Uri
): ExecutionTransport {
	const target = resolveExecutionTransportTarget(
		extensionMode,
		workspaceRoot,
		extensionUri
	);
	if (target.kind === 'orchestration') {
		return new OrchestrationExecutionTransport(target, {
			developmentMode: extensionMode === vscode.ExtensionMode.Development,
		});
	}

	return new UnavailableExecutionTransport(target);
}
