import { execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { type ExecutionWindowModel, type ModelAction } from './phase1Model';

export interface ExecutionTransport {
	load(): Promise<ExecutionWindowModel>;
	dispatch(action: ModelAction): Promise<ExecutionWindowModel>;
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

	constructor(target: Extract<ExecutionTransportTarget, { kind: 'orchestration' }>) {
		this.cwd = target.cwd;
		this.scriptPath = target.scriptPath;
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
			case 'approve':
				return this.run('session', 'approve', action);
			case 'full_access':
				return this.run('session', 'full-access', action);
			case 'interrupt_run':
				return this.run('session', 'interrupt', action);
			case 'reconnect':
				return this.run('session', 'reconnect');
		}
	}

	private run(group: string, command: string, action?: ModelAction): Promise<ExecutionWindowModel> {
		const args = [this.scriptPath, group, command];
		if (action && 'text' in action && typeof action.text === 'string') {
			args.push('--text', action.text);
		}
		if (action?.request_id) {
			args.push('--request-id', action.request_id);
		}
		if (action?.context_ref) {
			args.push('--context-ref', action.context_ref);
		}
		if (action && action.type !== 'reconnect') {
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
							action.type === 'interrupt_run' ? 'stop_action' : 'approval_action'
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

		return new Promise((resolve, reject) => {
			execFile(
				'python3',
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
						resolve(JSON.parse(stdout) as ExecutionWindowModel);
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
		return new OrchestrationExecutionTransport(target);
	}

	return new UnavailableExecutionTransport(target);
}
