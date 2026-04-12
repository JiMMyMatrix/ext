import * as vscode from 'vscode';
import { ExecutionWindowPanel } from './executionWindowPanel';

export function activate(context: vscode.ExtensionContext) {
	ExecutionWindowPanel.register(context);
}

export function deactivate() {}
