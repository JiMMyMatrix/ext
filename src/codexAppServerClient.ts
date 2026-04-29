import { spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import { EventEmitter } from 'events';

type JsonObject = Record<string, unknown>;

type PendingRequest = {
	resolve: (value: unknown) => void;
	reject: (error: Error) => void;
	timer: NodeJS.Timeout;
};

export type AppServerAccountStatus =
	| { kind: 'chatgpt'; email?: string; planType?: string }
	| { kind: 'apiKey' }
	| { kind: 'unavailable'; reason: string };

export type AppServerTurnResult = {
	threadId: string;
	turnId?: string;
	itemId?: string;
	message: string;
};

export type AppServerTurnRequest = {
	threadId?: string;
	prompt: string;
	model: string;
	reasoning: string;
	cwd: string;
	ephemeralThread?: boolean;
	timeoutMs?: number;
};

type ActiveTurn = {
	threadId?: string;
	turnId?: string;
	itemId?: string;
	deltas: string[];
	completedMessage?: string;
	resolve: (value: AppServerTurnResult) => void;
	reject: (error: Error) => void;
	timer: NodeJS.Timeout;
};

export class CodexAppServerClient extends EventEmitter {
	private process: ChildProcessWithoutNullStreams | undefined;
	private nextId = 1;
	private readonly pendingRequests = new Map<string, PendingRequest>();
	private activeTurn: ActiveTurn | undefined;
	private stdoutBuffer = '';
	private initialized = false;
	private exited = false;

	public async initialize(): Promise<void> {
		if (this.initialized) {
			return;
		}
		this.ensureProcess();
		await this.request('initialize', {
			clientInfo: {
				name: 'corgi-vscode',
				version: '0.0.1',
			},
			capabilities: {
				experimentalApi: true,
				optOutNotificationMethods: [],
			},
		});
		this.notify('initialized', {});
		this.initialized = true;
	}

	public async readAccount(): Promise<AppServerAccountStatus> {
		try {
			const result = await this.request('account/read', { refreshToken: false });
			const response = asObject(result);
			const account = asObject(response?.account);
			const type = typeof account?.type === 'string' ? account.type : undefined;
			if (type === 'chatgpt') {
				return {
					kind: 'chatgpt',
					email: typeof account?.email === 'string' ? account.email : undefined,
					planType: typeof account?.planType === 'string' ? account.planType : undefined,
				};
			}
			if (type === 'apiKey') {
				return { kind: 'apiKey' };
			}
			return { kind: 'unavailable', reason: 'account/read returned no account' };
		} catch (error) {
			return {
				kind: 'unavailable',
				reason: error instanceof Error ? error.message : String(error),
			};
		}
	}

	public async startTurn(request: AppServerTurnRequest): Promise<AppServerTurnResult> {
		await this.initialize();
		if (this.activeTurn) {
			throw new Error('app-server turn already in progress');
		}
		const threadId = request.threadId
			? await this.resumeThread(request.threadId, request)
			: await this.startThread(request);
		const timeoutMs = request.timeoutMs ?? 300_000;
		const prompt = request.prompt.trim();
		if (!prompt) {
			throw new Error('app-server turn prompt is empty');
		}

		const resultPromise = new Promise<AppServerTurnResult>((resolve, reject) => {
			const timer = setTimeout(() => {
				this.activeTurn = undefined;
				reject(new Error('app-server Governor turn timed out'));
			}, timeoutMs);
			this.activeTurn = {
				threadId,
				deltas: [],
				resolve,
				reject,
				timer,
			};
		});

		try {
			await this.request('turn/start', {
				threadId,
				input: [
					{
						type: 'text',
						text: prompt,
						text_elements: [],
					},
				],
				model: request.model,
				effort: normalizeReasoning(request.reasoning),
				summary: 'none',
				approvalPolicy: 'never',
				sandboxPolicy: readOnlySandbox(),
			});
		} catch (error) {
			this.rejectActiveTurn(error instanceof Error ? error : new Error(String(error)));
		}

		return resultPromise;
	}

	public health(): 'starting' | 'ready' | 'exited' {
		if (this.exited) {
			return 'exited';
		}
		return this.initialized ? 'ready' : 'starting';
	}

	public shutdown(): void {
		this.rejectAll(new Error('app-server client shutting down'));
		if (this.process && !this.process.killed) {
			this.process.kill();
		}
		this.process = undefined;
		this.initialized = false;
	}

	private async startThread(request: AppServerTurnRequest): Promise<string> {
		const result = asObject(
			await this.request('thread/start', {
				model: request.model,
				cwd: request.cwd,
				approvalPolicy: 'never',
				sandbox: 'read-only',
				ephemeral: request.ephemeralThread,
				experimentalRawEvents: false,
				persistExtendedHistory: true,
				sessionStartSource: 'startup',
			})
		);
		const threadId =
			stringAt(result, ['threadId']) ??
			stringAt(result, ['thread', 'id']) ??
			stringAt(result, ['id']);
		if (!threadId) {
			throw new Error('app-server thread/start returned no thread id');
		}
		return threadId;
	}

	private async resumeThread(threadId: string, request: AppServerTurnRequest): Promise<string> {
		await this.request('thread/resume', {
			threadId,
			model: request.model,
			cwd: request.cwd,
			approvalPolicy: 'never',
			sandbox: 'read-only',
			persistExtendedHistory: true,
		});
		return threadId;
	}

	private ensureProcess(): void {
		if (this.process && !this.exited) {
			return;
		}
		this.exited = false;
		this.process = spawn('codex', [
			'app-server',
			'-c',
			'analytics.enabled=false',
			'--listen',
			'stdio://',
		]);
		this.process.stdout.setEncoding('utf8');
		this.process.stderr.setEncoding('utf8');
		this.process.stdout.on('data', (chunk: string) => this.handleStdout(chunk));
		this.process.stderr.on('data', (chunk: string) => {
			this.emit('diagnostic', chunk.trim());
		});
		this.process.on('error', (error) => {
			this.exited = true;
			this.rejectAll(error);
		});
		this.process.on('exit', (code, signal) => {
			this.exited = true;
			this.initialized = false;
			this.rejectAll(
				new Error(`app-server exited${code === null ? '' : ` with code ${code}`}${signal ? ` signal ${signal}` : ''}`)
			);
		});
	}

	private request(method: string, params: JsonObject, timeoutMs = 30_000): Promise<unknown> {
		this.ensureProcess();
		const id = String(this.nextId++);
		const payload = JSON.stringify({ jsonrpc: '2.0', id, method, params });
		return new Promise((resolve, reject) => {
			const timer = setTimeout(() => {
				this.pendingRequests.delete(id);
				reject(new Error(`app-server ${method} timed out`));
			}, timeoutMs);
			this.pendingRequests.set(id, { resolve, reject, timer });
			this.process?.stdin.write(`${payload}\n`);
		});
	}

	private notify(method: string, params: JsonObject): void {
		this.process?.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method, params })}\n`);
	}

	private handleStdout(chunk: string): void {
		this.stdoutBuffer += chunk;
		let newlineIndex = this.stdoutBuffer.indexOf('\n');
		while (newlineIndex >= 0) {
			const rawLine = this.stdoutBuffer.slice(0, newlineIndex).trim();
			this.stdoutBuffer = this.stdoutBuffer.slice(newlineIndex + 1);
			if (rawLine) {
				this.handleMessageLine(rawLine);
			}
			newlineIndex = this.stdoutBuffer.indexOf('\n');
		}
	}

	private handleMessageLine(rawLine: string): void {
		let message: JsonObject;
		try {
			message = JSON.parse(rawLine) as JsonObject;
		} catch (error) {
			this.rejectAll(new Error(`app-server emitted malformed JSON: ${rawLine.slice(0, 120)}`));
			return;
		}
		if ('id' in message && ('result' in message || 'error' in message)) {
			this.handleResponse(message);
			return;
		}
		if ('id' in message && typeof message.method === 'string') {
			this.respondUnsupportedRequest(message);
			return;
		}
		if (typeof message.method === 'string') {
			this.handleNotification(message.method, asObject(message.params) ?? {});
		}
	}

	private handleResponse(message: JsonObject): void {
		const id = String(message.id ?? '');
		const pending = this.pendingRequests.get(id);
		if (!pending) {
			return;
		}
		clearTimeout(pending.timer);
		this.pendingRequests.delete(id);
		if (message.error) {
			const error = asObject(message.error);
			pending.reject(new Error(String(error?.message ?? 'app-server request failed')));
			return;
		}
		pending.resolve(message.result);
	}

	private handleNotification(method: string, params: JsonObject): void {
		switch (method) {
			case 'turn/started':
				if (this.activeTurn) {
					this.activeTurn.threadId = stringAt(params, ['threadId']) ?? this.activeTurn.threadId;
					this.activeTurn.turnId = stringAt(params, ['turn', 'id']) ?? stringAt(params, ['turnId']) ?? this.activeTurn.turnId;
				}
				break;
			case 'item/agentMessage/delta':
				if (this.activeTurn && typeof params.delta === 'string') {
					this.activeTurn.deltas.push(params.delta);
					this.activeTurn.itemId = stringAt(params, ['itemId']) ?? this.activeTurn.itemId;
					this.activeTurn.turnId = stringAt(params, ['turnId']) ?? this.activeTurn.turnId;
				}
				break;
			case 'item/completed': {
				const item = asObject(params.item);
				if (this.activeTurn && item?.type === 'agentMessage' && typeof item.text === 'string') {
					this.activeTurn.completedMessage = item.text;
					this.activeTurn.itemId = typeof item.id === 'string' ? item.id : this.activeTurn.itemId;
					this.activeTurn.turnId = stringAt(params, ['turnId']) ?? this.activeTurn.turnId;
				}
				break;
			}
			case 'turn/completed':
				this.resolveActiveTurn();
				break;
			case 'error': {
				const error = asObject(params.error);
				this.rejectActiveTurn(new Error(String(error?.message ?? 'app-server turn failed')));
				break;
			}
		}
	}

	private respondUnsupportedRequest(message: JsonObject): void {
		const id = message.id;
		this.process?.stdin.write(
			`${JSON.stringify({
				jsonrpc: '2.0',
				id,
				error: {
					code: -32601,
					message: `Corgi does not support app-server request ${String(message.method)}`,
				},
			})}\n`
		);
		this.rejectActiveTurn(new Error(`app-server requested unsupported method ${String(message.method)}`));
	}

	private resolveActiveTurn(): void {
		const activeTurn = this.activeTurn;
		if (!activeTurn) {
			return;
		}
		const message = (activeTurn.completedMessage ?? activeTurn.deltas.join('')).trim();
		clearTimeout(activeTurn.timer);
		this.activeTurn = undefined;
		if (!message) {
			activeTurn.reject(new Error('app-server turn completed without a Governor message'));
			return;
		}
		activeTurn.resolve({
			threadId: activeTurn.threadId ?? '',
			turnId: activeTurn.turnId,
			itemId: activeTurn.itemId,
			message,
		});
	}

	private rejectActiveTurn(error: Error): void {
		if (!this.activeTurn) {
			return;
		}
		clearTimeout(this.activeTurn.timer);
		this.activeTurn.reject(error);
		this.activeTurn = undefined;
	}

	private rejectAll(error: Error): void {
		for (const pending of this.pendingRequests.values()) {
			clearTimeout(pending.timer);
			pending.reject(error);
		}
		this.pendingRequests.clear();
		this.rejectActiveTurn(error);
	}
}

function readOnlySandbox(): JsonObject {
	return {
		type: 'readOnly',
		access: {
			type: 'fullAccess',
		},
		networkAccess: false,
	};
}

function normalizeReasoning(reasoning: string): string {
	return reasoning === 'minimal' ? 'low' : reasoning;
}

function asObject(value: unknown): JsonObject | undefined {
	return typeof value === 'object' && value !== null ? (value as JsonObject) : undefined;
}

function stringAt(value: JsonObject | undefined, path: string[]): string | undefined {
	let cursor: unknown = value;
	for (const key of path) {
		cursor = asObject(cursor)?.[key];
	}
	return typeof cursor === 'string' ? cursor : undefined;
}
