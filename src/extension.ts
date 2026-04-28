import * as fs from 'fs';
import * as path from 'path';
import * as vscode from 'vscode';
import { resetDevelopmentSessionState } from './developmentSession';
import { ExecutionWindowPanel } from './executionWindowPanel';

function appendDevelopmentLog(context: vscode.ExtensionContext, message: string) {
	if (context.extensionMode !== vscode.ExtensionMode.Development) {
		return;
	}

	const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri ?? context.extensionUri;

	const logDir = path.join(workspaceRoot.fsPath, '.agent', 'orchestration');
	fs.mkdirSync(logDir, { recursive: true });
	fs.appendFileSync(
		path.join(logDir, 'corgi_extension_dev.log'),
		`${new Date().toISOString()} ${message}\n`,
		'utf8'
	);
}

function scheduleDevelopmentExecutionWindowOpen(
	context: vscode.ExtensionContext,
	provider: ExecutionWindowPanel
) {
	if (context.extensionMode !== vscode.ExtensionMode.Development) {
		return;
	}

	for (const delayMs of [250, 1000, 2500]) {
		setTimeout(() => {
			appendDevelopmentLog(context, `openView attempt after ${delayMs}ms`);
			void provider.openView().catch((error: unknown) => {
				appendDevelopmentLog(
					context,
					`openView failed after ${delayMs}ms: ${
						error instanceof Error ? error.message : String(error)
					}`
				);
			});
		}, delayMs);
	}
}

export function activate(context: vscode.ExtensionContext) {
	appendDevelopmentLog(context, 'activate');
	resetDevelopmentSessionState(context);
	const provider = ExecutionWindowPanel.register(context);
	scheduleDevelopmentExecutionWindowOpen(context, provider);
}

export function deactivate() {}
