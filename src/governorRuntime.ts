import {
	CodexAppServerClient,
	type AppServerProgressEvent,
	type AppServerTurnResult,
} from './codexAppServerClient';

export type GovernorRuntimeRequest = {
	runtimeKind?: 'dialogue' | 'plan' | 'semantic_intake';
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

export type GovernorRuntimeProgressEvent = AppServerProgressEvent;

export interface GovernorRuntime {
	sendDialogueTurn(request: GovernorRuntimeRequest, cwd: string): Promise<GovernorRuntimeResult>;
	prewarm?(): Promise<void>;
	onProgress?(listener: (event: GovernorRuntimeProgressEvent) => void): () => void;
	health(): 'starting' | 'ready' | 'exited';
	shutdown(): void;
}

export type AppServerGovernorRuntimeOptions = {
	ephemeralThreads?: boolean;
};

const DEFAULT_SEMANTIC_INTAKE_TIMEOUT_MS = 60_000;
const MIN_SEMANTIC_INTAKE_TIMEOUT_MS = 30_000;

export class AppServerGovernorRuntime implements GovernorRuntime {
	private readonly client = new CodexAppServerClient();
	private accountChecked = false;
	private readyPromise: Promise<void> | undefined;

	constructor(private readonly options: AppServerGovernorRuntimeOptions = {}) {}

	public onProgress(listener: (event: GovernorRuntimeProgressEvent) => void): () => void {
		this.client.on('progress', listener);
		return () => this.client.off('progress', listener);
	}

	public async prewarm(): Promise<void> {
		if (this.client.health() === 'exited') {
			this.readyPromise = undefined;
			this.accountChecked = false;
		}
		this.readyPromise ??= this.prepareClient().catch((error: unknown) => {
			this.readyPromise = undefined;
			throw error;
		});
		await this.readyPromise;
	}

	public async sendDialogueTurn(
		request: GovernorRuntimeRequest,
		cwd: string
	): Promise<GovernorRuntimeResult> {
		await this.prewarm();
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

	private async prepareClient(): Promise<void> {
		await this.client.initialize();
		await this.ensureChatGptAuth();
	}

	public health(): 'starting' | 'ready' | 'exited' {
		return this.client.health();
	}

	public shutdown(): void {
		this.readyPromise = undefined;
		this.accountChecked = false;
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
			requestId: request.requestId,
			runtimeRequestId: request.runtimeRequestId,
			runtimeKind: request.runtimeKind,
			previewEnabled: request.runtimeKind !== 'semantic_intake',
			threadId,
			prompt: threadId ? request.resumePrompt : request.initialPrompt,
			model: request.model,
			reasoning: request.reasoning,
			cwd,
			ephemeralThread: this.options.ephemeralThreads,
			timeoutMs: request.runtimeKind === 'semantic_intake' ? semanticIntakeTimeoutMs() : undefined,
		});
	}
}

function semanticIntakeTimeoutMs(): number {
	const configured = Number.parseInt(
		process.env.CORGI_SEMANTIC_INTAKE_TIMEOUT_MS ?? '',
		10
	);
	if (Number.isFinite(configured) && configured >= MIN_SEMANTIC_INTAKE_TIMEOUT_MS) {
		return configured;
	}
	return DEFAULT_SEMANTIC_INTAKE_TIMEOUT_MS;
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
