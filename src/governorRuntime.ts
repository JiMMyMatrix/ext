import { CodexAppServerClient, type AppServerTurnResult } from './codexAppServerClient';

export type GovernorRuntimeRequest = {
	runtimeKind?: 'dialogue' | 'semantic_intake';
	runtimeRequestId: string;
	requestId?: string;
	preferredAppServerThreadId?: string;
	initialPrompt: string;
	resumePrompt: string;
	model: string;
	reasoning: string;
	resultStage: string;
	context?: Record<string, unknown>;
};

export type GovernorRuntimeResult = {
	body: string;
	threadId?: string;
	turnId?: string;
	itemId?: string;
	runtimeSource: 'app-server';
};

export interface GovernorRuntime {
	sendDialogueTurn(request: GovernorRuntimeRequest, cwd: string): Promise<GovernorRuntimeResult>;
	health(): 'starting' | 'ready' | 'exited';
	shutdown(): void;
}

export type AppServerGovernorRuntimeOptions = {
	ephemeralThreads?: boolean;
};

export class AppServerGovernorRuntime implements GovernorRuntime {
	private readonly client = new CodexAppServerClient();
	private accountChecked = false;

	constructor(private readonly options: AppServerGovernorRuntimeOptions = {}) {}

	public async sendDialogueTurn(
		request: GovernorRuntimeRequest,
		cwd: string
	): Promise<GovernorRuntimeResult> {
		await this.client.initialize();
		await this.ensureChatGptAuth();
		const preferredThreadId = this.options.ephemeralThreads
			? undefined
			: request.preferredAppServerThreadId;
		const result = await this.startTurnWithFreshThreadRetry(
			request,
			cwd,
			preferredThreadId
		);
		return runtimeResult(result);
	}

	public health(): 'starting' | 'ready' | 'exited' {
		return this.client.health();
	}

	public shutdown(): void {
		this.client.shutdown();
	}

	private async ensureChatGptAuth(): Promise<void> {
		if (this.accountChecked) {
			return;
		}
		const account = await this.client.readAccount();
		this.accountChecked = true;
		if (account.kind === 'apiKey') {
			throw new Error('codex app-server reported API key auth; Corgi expects ChatGPT auth for this experimental path');
		}
	}

	private async startTurnWithFreshThreadRetry(
		request: GovernorRuntimeRequest,
		cwd: string,
		preferredThreadId: string | undefined
	): Promise<AppServerTurnResult> {
		try {
			return await this.startTurn(request, cwd, preferredThreadId);
		} catch (error) {
			if (!preferredThreadId || !isUnavailableAppServerThreadError(error)) {
				throw error;
			}
			return this.startTurn(request, cwd, undefined);
		}
	}

	private startTurn(
		request: GovernorRuntimeRequest,
		cwd: string,
		threadId: string | undefined
	): Promise<AppServerTurnResult> {
		return this.client.startTurn({
			threadId,
			prompt: threadId ? request.resumePrompt : request.initialPrompt,
			model: request.model,
			reasoning: request.reasoning,
			cwd,
			ephemeralThread: this.options.ephemeralThreads,
			timeoutMs: request.runtimeKind === 'semantic_intake' ? 25_000 : undefined,
		});
	}
}

function runtimeResult(result: AppServerTurnResult): GovernorRuntimeResult {
	return {
		body: result.message,
		threadId: result.threadId,
		turnId: result.turnId,
		itemId: result.itemId,
		runtimeSource: 'app-server',
	};
}

function isUnavailableAppServerThreadError(error: unknown): boolean {
	const message = error instanceof Error ? error.message : String(error);
	return /no rollout found|thread .*not found|unknown thread/i.test(message);
}
