import { CodexAppServerClient, type AppServerTurnResult } from './codexAppServerClient';

export type GovernorRuntimeRequest = {
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
		const prompt = request.preferredAppServerThreadId
			? request.resumePrompt
			: request.initialPrompt;
		const result = await this.client.startTurn({
			threadId: request.preferredAppServerThreadId,
			prompt,
			model: request.model,
			reasoning: request.reasoning,
			cwd,
			ephemeralThread: this.options.ephemeralThreads,
		});
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
