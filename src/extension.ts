import * as vscode from 'vscode';
import { CodexChatParticipant } from './chatParticipant';
import {
	OPEN_EXECUTION_WINDOW_COMMAND,
	ExecutionWindowPanel,
} from './executionWindowPanel';

export function activate(context: vscode.ExtensionContext) {
	CodexChatParticipant.register(context);
	const executionWindow = ExecutionWindowPanel.register(context);
	const openExecutionWindow = vscode.commands.registerCommand(
		OPEN_EXECUTION_WINDOW_COMMAND,
		() => {
			void executionWindow.createOrShow();
		}
	);

	context.subscriptions.push(openExecutionWindow);
}

export function deactivate() {}
