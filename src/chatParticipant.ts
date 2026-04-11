import * as vscode from 'vscode';
import {
	createExecutionTransport,
	type ExecutionTransport,
} from './executionTransport';
import {
	isSnapshotStale,
	type ExecutionWindowModel,
	type FeedItem,
	type ModelAction,
	type TransportState,
} from './phase1Model';

export const CODEX_CHAT_PARTICIPANT_ID = 'ext.codex';

type ChatCommand =
	| 'status'
	| 'approve'
	| 'hold'
	| 'interrupt'
	| 'reconnect';

interface ChatResultMetadata {
	hasClarification?: boolean;
	hasApproval?: boolean;
	hasInterrupt?: boolean;
	transportState: TransportState;
	stale?: boolean;
}

interface ChatRenderOptions {
	includeStatus?: boolean;
}

export function resolveChatAction(
	command: string | undefined,
	prompt: string,
	model: ExecutionWindowModel
): ModelAction | undefined {
	switch (command as ChatCommand | undefined) {
		case 'status':
			return undefined;
		case 'approve':
			return { type: 'approve' };
		case 'hold':
			return { type: 'decline_or_hold' };
		case 'interrupt':
			return { type: 'interrupt_run' };
		case 'reconnect':
			return { type: 'reconnect' };
	}

	const text = prompt.trim();
	if (!text) {
		return undefined;
	}

	if (model.activeClarification) {
		return {
			type: 'answer_clarification',
			text,
		};
	}

	return {
		type: 'submit_prompt',
		text,
	};
}

export function buildChatResultMetadata(
	model: ExecutionWindowModel
): ChatResultMetadata {
	return {
		hasClarification: Boolean(model.activeClarification),
		hasApproval: Boolean(model.snapshot.pendingApproval),
		hasInterrupt: Boolean(model.snapshot.pendingInterrupt),
		transportState: model.snapshot.transportState,
		stale: isSnapshotStale(model.snapshot.snapshotFreshness),
	};
}

export function buildChatFollowups(
	metadata: ChatResultMetadata
): vscode.ChatFollowup[] {
	const followups: vscode.ChatFollowup[] = [];

	if (metadata.hasApproval) {
		followups.push(
			{
				label: 'Approve',
				prompt: 'Approve the pending request.',
				command: 'approve',
			},
			{
				label: 'Hold',
				prompt: 'Hold the pending request.',
				command: 'hold',
			}
		);
	}

	if (metadata.hasInterrupt) {
		followups.push({
			label: 'Interrupt',
			prompt: 'Interrupt the current run.',
			command: 'interrupt',
		});
	}

	if (metadata.transportState !== 'connected' || metadata.stale) {
		followups.push({
			label: 'Reconnect',
			prompt: 'Reconnect and refresh the orchestration state.',
			command: 'reconnect',
		});
	}

	if (!metadata.hasClarification && followups.length === 0) {
		followups.push({
			label: 'Status',
			prompt: 'Show current status.',
			command: 'status',
		});
	}

	return followups.slice(0, 3);
}

export class CodexChatParticipant implements vscode.Disposable {
	public static register(
		context: vscode.ExtensionContext
	): CodexChatParticipant {
		const participant = new CodexChatParticipant(context);
		context.subscriptions.push(participant);
		return participant;
	}

	private readonly transport: ExecutionTransport;
	private readonly participant: vscode.ChatParticipant;
	private readonly disposables: vscode.Disposable[] = [];

	private constructor(context: vscode.ExtensionContext) {
		const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
		this.transport = createExecutionTransport(
			context.extensionMode,
			workspaceRoot
		);
		this.participant = vscode.chat.createChatParticipant(
			CODEX_CHAT_PARTICIPANT_ID,
			(request, chatContext, stream, token) =>
				this.handleRequest(request, chatContext, stream, token)
		);
		this.participant.iconPath = vscode.Uri.joinPath(
			context.extensionUri,
			'resources',
			'execution-window.svg'
		);
		this.participant.followupProvider = {
			provideFollowups: (result) =>
				buildChatFollowups(
					(result.metadata as ChatResultMetadata | undefined) ?? {
						transportState: 'connected',
					}
				),
		};

		this.disposables.push(this.participant);
	}

	public dispose() {
		while (this.disposables.length) {
			this.disposables.pop()?.dispose();
		}
	}

	private async handleRequest(
		request: vscode.ChatRequest,
		_context: vscode.ChatContext,
		stream: vscode.ChatResponseStream,
		_token: vscode.CancellationToken
	): Promise<vscode.ChatResult> {
		try {
			const before = await this.transport.load();
			const action = resolveChatAction(request.command, request.prompt, before);

			const model = action
				? await this.transport.dispatch(action)
				: before;

			this.renderModel(stream, model, {
				includeStatus: request.command === 'status',
			});

			return {
				metadata: buildChatResultMetadata(model),
			};
		} catch (error) {
				const message =
					error instanceof Error
						? error.message
						: 'The project runtime did not return a usable response.';
			stream.markdown(`$(error) ${message}`);
			return {
				errorDetails: {
					message,
				},
				metadata: {
					transportState: 'disconnected',
					stale: true,
				},
			};
		}
	}

	private renderModel(
		stream: vscode.ChatResponseStream,
		model: ExecutionWindowModel,
		options: ChatRenderOptions = {}
	) {
		stream.markdown(buildChatMarkdown(model, options));
	}
}

export function buildChatMarkdown(
	model: ExecutionWindowModel,
	options: ChatRenderOptions = {}
): string {
	const primary = buildPrimaryMessage(model);
	const status = options.includeStatus ? buildStatusMessage(model) : undefined;

	if (primary && status) {
		return `${primary}\n\n${status}`;
	}

	return primary ?? status ?? 'Ready for your next request.';
}

function buildPrimaryMessage(model: ExecutionWindowModel): string | undefined {
	if (model.activeClarification) {
		return `${model.activeClarification.body}\n\nReply here to continue.`;
	}

	if (model.snapshot.pendingApproval) {
		return `${model.snapshot.pendingApproval.body}\n\nUse \`/approve\` or \`/hold\`.`;
	}

	if (model.snapshot.pendingInterrupt) {
		return `${model.snapshot.pendingInterrupt.body}\n\nUse \`/interrupt\` if you want to stop the run.`;
	}

	if (model.acceptedIntakeSummary) {
		return model.acceptedIntakeSummary.body;
	}

	const latest = latestNarrativeItem(model.feed);
	if (!latest) {
		return undefined;
	}

	return latest.body ?? latest.title;
}

function buildStatusMessage(model: ExecutionWindowModel): string {
	const stale = isSnapshotStale(model.snapshot.snapshotFreshness);
	const { transportState } = model.snapshot;
	const notes: string[] = [];

	if (transportState !== 'connected') {
		notes.push(`Connection is ${transportState}.`);
	}
	if (stale) {
		notes.push('State may be stale.');
	}
	if (model.activeClarification) {
		notes.push('Clarification is waiting.');
	} else if (model.snapshot.pendingApproval) {
		notes.push('Approval is waiting.');
	} else if (model.snapshot.pendingInterrupt) {
		notes.push('Interrupt is available.');
	}

	if (notes.length === 0) {
		return 'Ready.';
	}

	return notes.join(' ');
}

function latestNarrativeItem(feed: FeedItem[]): FeedItem | undefined {
	return [...feed]
		.reverse()
		.find(
			(item) =>
				item.type !== 'user_message' &&
				item.type !== 'artifact_reference' &&
				item.type !== 'clarification_request' &&
				item.type !== 'approval_request' &&
				item.type !== 'interrupt_request'
		);
}
