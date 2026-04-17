import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { ExecutionWindowPanel } from './executionWindowPanel';
import { resolveExecutionTransportTarget } from './executionTransport';

function resetDevelopmentSessionState(context: vscode.ExtensionContext) {
	if (context.extensionMode !== vscode.ExtensionMode.Development) {
		return;
	}

	const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
	const target = resolveExecutionTransportTarget(
		context.extensionMode,
		workspaceRoot,
		context.extensionUri
	);

	if (target.kind !== 'orchestration') {
		return;
	}

	const sessionPath = path.join(
		target.cwd,
		'.agent',
		'orchestration',
		'ui_session.json'
	);
	fs.rmSync(sessionPath, { force: true });
}

export function activate(context: vscode.ExtensionContext) {
	resetDevelopmentSessionState(context);
	ExecutionWindowPanel.register(context);
}

export function deactivate() {}
