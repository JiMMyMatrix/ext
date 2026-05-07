#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEST_ROOT="$ROOT_DIR/.agent/test-window"
PROFILE_ROOT="$TEST_ROOT/vscode-profile"
RUNTIME_AGENT_ROOT="$TEST_ROOT/runtime-agent"
LOG_DIR="$TEST_ROOT/logs"
USER_DATA_DIR="$PROFILE_ROOT/user-data"
EXTENSIONS_DIR="$PROFILE_ROOT/extensions"
STDOUT_LOG="$LOG_DIR/vscode.stdout.log"
STDERR_LOG="$LOG_DIR/vscode.stderr.log"
CURRENT_RUN_FILE="$TEST_ROOT/current-run.json"
LEGACY_USER_DATA_DIR="$ROOT_DIR/.agent/vscode-governor-first-test-user-data"
CLOSE_SCRIPT="$ROOT_DIR/scripts/close-corgi-test-window.sh"
APP_NAME="${CORGI_VSCODE_APP_NAME:-Visual Studio Code}"
TEST_SCENARIO="${CORGI_TEST_WINDOW_SCENARIO:-}"
PROMPT_PRESET="${CORGI_TEST_WINDOW_PROMPT_PRESET:-}"
AUTO_STEPS="${CORGI_TEST_WINDOW_AUTO_STEPS:-}"
WORKSPACE_MODE="${CORGI_TEST_WINDOW_WORKSPACE_MODE:-repo}"
SCRATCH_ID="${CORGI_TEST_WINDOW_SCRATCH_ID:-pet-life-diary-app}"
SCRATCH_BASE="$TEST_ROOT/scratch-workspaces"
SCRATCH_ROOT=""
if [[ -n "${CORGI_TEST_WINDOW_AUTO_PROMPT+x}" ]]; then
	AUTO_PROMPT="$CORGI_TEST_WINDOW_AUTO_PROMPT"
	AUTO_PROMPT_PRESET=""
elif [[ -n "$PROMPT_PRESET" ]]; then
	AUTO_PROMPT="$(node "$ROOT_DIR/scripts/corgi-test-prompt.cjs" get "$PROMPT_PRESET")"
	AUTO_PROMPT_PRESET="$PROMPT_PRESET"
elif [[ -n "$TEST_SCENARIO" ]]; then
	AUTO_PROMPT=""
	AUTO_PROMPT_PRESET=""
else
	AUTO_PROMPT_PRESET="$(node "$ROOT_DIR/scripts/corgi-test-prompt.cjs" default)"
	AUTO_PROMPT="$(node "$ROOT_DIR/scripts/corgi-test-prompt.cjs" get "$AUTO_PROMPT_PRESET")"
fi

mkdir -p "$TEST_ROOT" "$LOG_DIR"

# Test launches should start clean, while production reload keeps session memory.
"$CLOSE_SCRIPT" >/dev/null 2>&1 || true
for _ in 1 2 3; do
	rm -rf "$PROFILE_ROOT" "$RUNTIME_AGENT_ROOT" && break
	sleep 0.4
done
case "$WORKSPACE_MODE" in
	repo)
		WORKSPACE_ROOT="$ROOT_DIR"
		AGENT_ROOT="$RUNTIME_AGENT_ROOT"
		;;
	scratch)
		if [[ -n "$TEST_SCENARIO" ]]; then
			echo "Scratch workspace mode does not support seeded scenarios yet." >&2
			exit 2
		fi
		if [[ ! "$SCRATCH_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ || "$SCRATCH_ID" == *..* ]]; then
			echo "Unsafe Corgi scratch workspace id: $SCRATCH_ID" >&2
			exit 2
		fi
		mkdir -p "$SCRATCH_BASE"
		SCRATCH_BASE_REAL="$(cd "$SCRATCH_BASE" && pwd -P)"
		SCRATCH_ROOT="$SCRATCH_BASE/$SCRATCH_ID"
		SCRATCH_PARENT_REAL="$(cd "$(dirname "$SCRATCH_ROOT")" && pwd -P)"
		if [[ "$SCRATCH_PARENT_REAL" != "$SCRATCH_BASE_REAL" ]]; then
			echo "Scratch workspace escaped the scratch root: $SCRATCH_ROOT" >&2
			exit 2
		fi
		rm -rf -- "$SCRATCH_ROOT"
		mkdir -p -- "$SCRATCH_ROOT"
		if command -v git >/dev/null 2>&1; then
			git -C "$SCRATCH_ROOT" init -b main >/dev/null 2>&1 || git -C "$SCRATCH_ROOT" init >/dev/null 2>&1 || true
			if [[ -d "$SCRATCH_ROOT/.git/info" ]]; then
				printf '\n.agent/\n' >> "$SCRATCH_ROOT/.git/info/exclude"
			fi
		fi
		WORKSPACE_ROOT="$SCRATCH_ROOT"
		AGENT_ROOT="$SCRATCH_ROOT/.agent"
		;;
	*)
		echo "Unknown Corgi test-window workspace mode: $WORKSPACE_MODE" >&2
		exit 2
		;;
esac
mkdir -p "$USER_DATA_DIR" "$EXTENSIONS_DIR" "$RUNTIME_AGENT_ROOT" "$AGENT_ROOT"
rm -f "$STDOUT_LOG" "$STDERR_LOG"
mkdir -p "$USER_DATA_DIR/User"
cat > "$USER_DATA_DIR/User/settings.json" <<'JSON'
{
	"update.mode": "none",
	"extensions.autoCheckUpdates": false,
	"extensions.autoUpdate": false
}
JSON

if [[ -n "$TEST_SCENARIO" ]]; then
	PYTHON_BIN="${CORGI_PYTHON:-${ORCHESTRATION_APPROVED_PYTHON:-}}"
	if [[ -z "$PYTHON_BIN" ]]; then
		if [[ -x /opt/homebrew/bin/python3 ]]; then
			PYTHON_BIN="/opt/homebrew/bin/python3"
		else
			PYTHON_BIN="$(command -v python3)"
		fi
	fi
	case "$TEST_SCENARIO" in
		plan-ready|execute-permission)
			SEED_SCRIPT="$ROOT_DIR/orchestration/scripts/seed_executor_test_session.py"
			;;
		reviewer-ready|reviewer-completed)
			SEED_SCRIPT="$ROOT_DIR/orchestration/scripts/seed_reviewer_test_session.py"
			;;
		*)
			echo "Unknown Corgi test-window scenario: $TEST_SCENARIO" >&2
			exit 2
			;;
	esac
	ORCHESTRATION_AGENT_ROOT="$AGENT_ROOT" \
	ORCHESTRATION_SOURCE_ROOT="$ROOT_DIR" \
	ORCHESTRATION_APPROVED_PYTHON="$PYTHON_BIN" \
	"$PYTHON_BIN" "$SEED_SCRIPT" \
		--root "$WORKSPACE_ROOT" \
		--scenario "$TEST_SCENARIO"
fi

node - \
	"$CURRENT_RUN_FILE" \
	"$WORKSPACE_MODE" \
	"$WORKSPACE_ROOT" \
	"$ROOT_DIR" \
	"$AGENT_ROOT" \
	"$USER_DATA_DIR" \
	"$STDOUT_LOG" \
	"$STDERR_LOG" \
	"$AUTO_PROMPT_PRESET" \
	"$TEST_SCENARIO" <<'NODE'
const fs = require('fs');
const path = require('path');
const [
	filePath,
	workspaceMode,
	workspaceRoot,
	sourceRoot,
	agentRoot,
	userDataDir,
	stdoutPath,
	stderrPath,
	promptPreset,
	scenario,
] = process.argv.slice(2);
const snapshotPath = path.join(agentRoot, 'orchestration', 'corgi_webview_snapshot.json');
fs.mkdirSync(path.dirname(filePath), { recursive: true });
fs.writeFileSync(
	filePath,
	JSON.stringify(
		{
			schemaVersion: 1,
			recordedAt: new Date().toISOString(),
			workspaceMode,
			workspaceRoot,
			sourceRoot,
			agentRoot,
			snapshotPath,
			userDataDir,
			stdoutPath,
			stderrPath,
			promptPreset: promptPreset || null,
			scenario: scenario || null,
		},
		null,
		2
	) + '\n'
);
NODE

# Codex often runs inside a VS Code extension-host environment. If those
# variables leak into the launched app, VS Code can start in Node mode and the
# test window silently disappears.
open -n -a "$APP_NAME" \
	--env ELECTRON_RUN_AS_NODE= \
	--env VSCODE_ESM_ENTRYPOINT= \
	--env VSCODE_HANDLES_UNCAUGHT_ERRORS= \
	--env VSCODE_IPC_HOOK= \
	--env VSCODE_IPC_HOOK_CLI= \
	--env VSCODE_PID= \
	--env VSCODE_CWD= \
	--env VSCODE_CRASH_REPORTER_PROCESS_TYPE= \
	--env CORGI_SEMANTIC_MODE="${CORGI_SEMANTIC_MODE:-governor-first}" \
	--env CORGI_GOVERNOR_RUNTIME="${CORGI_GOVERNOR_RUNTIME:-app-server}" \
	--env CORGI_APP_SERVER_EPHEMERAL="${CORGI_APP_SERVER_EPHEMERAL:-1}" \
	--env CORGI_TEST_WINDOW_SCENARIO="$TEST_SCENARIO" \
	--env CORGI_TEST_WINDOW_AUTO_PROMPT="$AUTO_PROMPT" \
	--env CORGI_TEST_WINDOW_AUTO_STEPS="$AUTO_STEPS" \
	--env CORGI_TEST_WINDOW_WORKSPACE_MODE="$WORKSPACE_MODE" \
	--env ORCHESTRATION_TARGET_WORKSPACE_MODE="$WORKSPACE_MODE" \
	--env ORCHESTRATION_TEST_PROMPT_PRESET="$AUTO_PROMPT_PRESET" \
	--env ORCHESTRATION_AGENT_ROOT="$AGENT_ROOT" \
	--env ORCHESTRATION_SOURCE_ROOT="$ROOT_DIR" \
	--env ORCHESTRATION_APPROVED_PYTHON="${PYTHON_BIN:-}" \
	--stdout "$STDOUT_LOG" \
	--stderr "$STDERR_LOG" \
	--args \
	--new-window \
	--user-data-dir "$USER_DATA_DIR" \
	--extensions-dir "$EXTENSIONS_DIR" \
	--extensionDevelopmentPath="$ROOT_DIR" \
	"$WORKSPACE_ROOT"

echo "Launched Corgi test window"
echo "  profile:    $USER_DATA_DIR"
echo "  workspace:  $WORKSPACE_ROOT"
echo "  source:     $ROOT_DIR"
echo "  runtime:    $AGENT_ROOT"
echo "  snapshot:   $AGENT_ROOT/orchestration/corgi_webview_snapshot.json"
echo "  stdout:     $STDOUT_LOG"
echo "  stderr:     $STDERR_LOG"
echo "  mode:       $WORKSPACE_MODE"
if [[ -n "$TEST_SCENARIO" ]]; then
	echo "  scenario:   $TEST_SCENARIO"
fi
if [[ -n "$AUTO_PROMPT" ]]; then
	echo "  auto-prompt: $AUTO_PROMPT"
fi
if [[ -n "$AUTO_PROMPT_PRESET" ]]; then
	echo "  prompt preset: $AUTO_PROMPT_PRESET"
fi
if [[ -n "$AUTO_STEPS" ]]; then
	echo "  auto-steps: $AUTO_STEPS"
fi
