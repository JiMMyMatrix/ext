import * as vscode from 'vscode';
import {
	OPEN_EXECUTION_WINDOW_COMMAND,
	ExecutionWindowPanel,
} from './executionWindowPanel';

export function activate(context: vscode.ExtensionContext) {
	const executionWindow = ExecutionWindowPanel.register(context);
	const openExecutionWindow = vscode.commands.registerCommand(
		OPEN_EXECUTION_WINDOW_COMMAND,
		() => {
			void executionWindow.createOrShow();
		}
	);

	context.subscriptions.push(openExecutionWindow);

	if (context.extensionMode === vscode.ExtensionMode.Development) {
		setTimeout(() => {
			void executionWindow.createOrShow();
		}, 250);
	}
}

export function deactivate() {}
