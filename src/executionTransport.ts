import { execFile } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import {
	applyModelAction,
	createInitialModel,
	type ExecutionWindowModel,
	type ModelAction,
} from './phase1Model';

export interface ExecutionTransport {
	load(): Promise<ExecutionWindowModel>;
	dispatch(action: ModelAction): Promise<ExecutionWindowModel>;
}

class MockExecutionTransport implements ExecutionTransport {
	private model: ExecutionWindowModel;

	constructor() {
		this.model = createInitialModel();
	}

	public async load(): Promise<ExecutionWindowModel> {
		return this.model;
	}

	public async dispatch(action: ModelAction): Promise<ExecutionWindowModel> {
		this.model = applyModelAction(this.model, action);
		return this.model;
	}
}

class OrchestrationExecutionTransport implements ExecutionTransport {
	private readonly scriptPath: string;
	private readonly cwd: string;

	constructor(workspaceRoot: vscode.Uri) {
		this.cwd = workspaceRoot.fsPath;
		this.scriptPath = path.join(
			this.cwd,
			'orchestration',
			'scripts',
			'orchestrate.py'
		);
	}

	public async load(): Promise<ExecutionWindowModel> {
		return this.run('session', 'state');
	}

	public async dispatch(action: ModelAction): Promise<ExecutionWindowModel> {
		switch (action.type) {
			case 'submit_prompt':
				return this.run('session', 'submit-prompt', action.text);
			case 'answer_clarification':
				return this.run('session', 'answer-clarification', action.text);
			case 'approve':
				return this.run('session', 'approve');
			case 'full_access':
				return this.run('session', 'full-access');
			case 'interrupt_run':
				return this.run('session', 'interrupt');
			case 'reconnect':
				return this.run('session', 'reconnect');
		}
	}

	private run(group: string, command: string, text?: string): Promise<ExecutionWindowModel> {
		const args = [this.scriptPath, group, command];
		if (typeof text === 'string') {
			args.push('--text', text);
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
	workspaceRoot: vscode.Uri | undefined
): ExecutionTransport {
	if (
		workspaceRoot &&
		extensionMode !== vscode.ExtensionMode.Test &&
		fs.existsSync(
			path.join(workspaceRoot.fsPath, 'orchestration', 'scripts', 'orchestrate.py')
		)
	) {
		return new OrchestrationExecutionTransport(workspaceRoot);
	}

	return new MockExecutionTransport();
}
