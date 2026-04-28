import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { resolveExecutionTransportTarget } from './executionTransport';

export function shouldResetDevelopmentSessionState(
	context: vscode.ExtensionContext
): boolean {
	return context.extensionMode === vscode.ExtensionMode.Development;
}

export function resetDevelopmentSessionState(
	context: vscode.ExtensionContext
): boolean {
	if (!shouldResetDevelopmentSessionState(context)) {
		return false;
	}

	const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
	const target = resolveExecutionTransportTarget(
		context.extensionMode,
		workspaceRoot,
		context.extensionUri
	);

	if (target.kind !== 'orchestration') {
		return false;
	}

	fs.rmSync(
		path.join(target.cwd, '.agent', 'orchestration', 'ui_session.json'),
		{ force: true }
	);
	return true;
}
