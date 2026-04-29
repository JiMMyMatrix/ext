import * as path from 'path';

export function resolveAgentRootPath(rootPath: string): string {
	const configured = process.env.ORCHESTRATION_AGENT_ROOT?.trim();
	if (!configured) {
		return path.join(rootPath, '.agent');
	}
	return path.isAbsolute(configured)
		? configured
		: path.resolve(rootPath, configured);
}

export function resolveOrchestrationStateRootPath(rootPath: string): string {
	return path.join(resolveAgentRootPath(rootPath), 'orchestration');
}
