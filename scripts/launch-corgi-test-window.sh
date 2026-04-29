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
LEGACY_USER_DATA_DIR="$ROOT_DIR/.agent/vscode-governor-first-test-user-data"
APP_NAME="${CORGI_VSCODE_APP_NAME:-Visual Studio Code}"

mkdir -p "$TEST_ROOT" "$LOG_DIR"

# Test launches should start clean, while production reload keeps session memory.
pkill -f "$USER_DATA_DIR" >/dev/null 2>&1 || true
pkill -f "$LEGACY_USER_DATA_DIR" >/dev/null 2>&1 || true
for _ in 1 2 3 4 5; do
	if ! pgrep -f "$USER_DATA_DIR|$LEGACY_USER_DATA_DIR" >/dev/null 2>&1; then
		break
	fi
	sleep 0.4
done
pkill -9 -f "$USER_DATA_DIR" >/dev/null 2>&1 || true
pkill -9 -f "$LEGACY_USER_DATA_DIR" >/dev/null 2>&1 || true
for _ in 1 2 3; do
	rm -rf "$PROFILE_ROOT" "$RUNTIME_AGENT_ROOT" && break
	sleep 0.4
done
mkdir -p "$USER_DATA_DIR" "$EXTENSIONS_DIR" "$RUNTIME_AGENT_ROOT"
rm -f "$STDOUT_LOG" "$STDERR_LOG"
mkdir -p "$USER_DATA_DIR/User"
cat > "$USER_DATA_DIR/User/settings.json" <<'JSON'
{
	"update.mode": "none",
	"extensions.autoCheckUpdates": false,
	"extensions.autoUpdate": false
}
JSON

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
	--env ORCHESTRATION_AGENT_ROOT="$RUNTIME_AGENT_ROOT" \
	--stdout "$STDOUT_LOG" \
	--stderr "$STDERR_LOG" \
	--args \
	--new-window \
	--user-data-dir "$USER_DATA_DIR" \
	--extensions-dir "$EXTENSIONS_DIR" \
	--extensionDevelopmentPath="$ROOT_DIR" \
	"$ROOT_DIR"

echo "Launched Corgi test window"
echo "  profile:    $USER_DATA_DIR"
echo "  runtime:    $RUNTIME_AGENT_ROOT"
echo "  snapshot:   $RUNTIME_AGENT_ROOT/orchestration/corgi_webview_snapshot.json"
echo "  stdout:     $STDOUT_LOG"
echo "  stderr:     $STDERR_LOG"
