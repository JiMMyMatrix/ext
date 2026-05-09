import * as path from 'path';

export const PACKAGE_JSON_PATH = path.resolve(__dirname, '../../package.json');
export const REPO_ROOT = path.resolve(__dirname, '../..');
export const LAUNCH_JSON_PATH = path.resolve(__dirname, '../../.vscode/launch.json');
export const EXTENSION_TS_PATH = path.resolve(__dirname, '../../src/extension.ts');
export const DEVELOPMENT_SESSION_TS_PATH = path.resolve(
	__dirname,
	'../../src/developmentSession.ts'
);
export const EXECUTION_WINDOW_PANEL_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionWindowPanel.ts'
);
export const EXECUTION_WINDOW_RENDERER_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionWindowRenderer.ts'
);
export const EXECUTION_WINDOW_CLIENT_SCRIPT_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionWindowClientScript.ts'
);
export const EXECUTION_WINDOW_STYLES_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionWindowStyles.ts'
);
export const EXECUTION_TRANSPORT_TS_PATH = path.resolve(
	__dirname,
	'../../src/executionTransport.ts'
);
export const TEST_WINDOW_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/launch-corgi-test-window.sh'
);
export const TEST_WINDOW_CLOSE_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/close-corgi-test-window.sh'
);
export const TEST_WINDOW_AUTO_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/run-corgi-test-window-auto.sh'
);
export const TEST_WINDOW_PROMPT_CATALOG_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-test-prompts.json'
);
export const TEST_WINDOW_PROMPT_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-test-prompt.cjs'
);
export const TEST_WINDOW_STATUS_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-test-window-status.cjs'
);
export const PROCESS_TEST_SCRIPT_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-process-test.cjs'
);
export const PROCESS_REPLAN_HELPER_PATH = path.resolve(
	__dirname,
	'../../scripts/corgi-review-replan-process-test.py'
);
export const CODEX_APP_SERVER_CLIENT_TS_PATH = path.resolve(
	__dirname,
	'../../src/codexAppServerClient.ts'
);
export const GOVERNOR_RUNTIME_TS_PATH = path.resolve(
	__dirname,
	'../../src/governorRuntime.ts'
);
export const RUNTIME_ERGONOMICS_KERNEL_TS_PATH = path.resolve(
	__dirname,
	'../../src/runtimeErgonomicsKernel.ts'
);
export const GOVERNOR_RUNTIME_CONFIG_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/config.toml'
);
export const MCP_SERVER_ENTRYPOINT_PATH = path.resolve(__dirname, '../../mcp_server.py');
export const DEV_MCP_SERVER_ENTRYPOINT_PATH = path.resolve(__dirname, '../../dev_mcp_server.py');
export const ADVISORY_MCP_LAUNCHER_PATH = path.resolve(
	__dirname,
	'../../orchestration/scripts/serve_advisory_mcp.py'
);
export const DEVELOPMENT_CONSULTING_MCP_LAUNCHER_PATH = path.resolve(
	__dirname,
	'../../orchestration/scripts/serve_development_consulting_mcp.py'
);
export const ADVISORY_MCP_SETUP_PATH = path.resolve(
	__dirname,
	'../../orchestration/scripts/setup_advisory_mcp_env.py'
);
export const ADVISORY_MCP_REQUIREMENTS_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/advisory/requirements.txt'
);
export const ADVISORY_MCP_SERVER_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/advisory/mcp_server.py'
);
export const ADVISORY_CAPABILITIES_PATH = path.resolve(
	__dirname,
	'../../orchestration/runtime/advisory/capabilities.json'
);
export const ADVISORY_DOC_PATH = path.resolve(__dirname, '../../orchestration/advisory.md');
export const UX_CONTRACT_PATH = path.resolve(__dirname, '../../orchestration/contracts/ux.md');
export const SEMANTIC_ROUTING_FIXTURE_PATH = path.resolve(
	__dirname,
	'../../src/test/fixtures/semantic-routing.json'
);
