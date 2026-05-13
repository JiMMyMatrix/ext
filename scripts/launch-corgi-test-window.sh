#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_TEST_ROOT="${HOME:-/tmp}/.corgi/test-window/extension-ext"
TEST_ROOT="${CORGI_TEST_WINDOW_ROOT:-$DEFAULT_TEST_ROOT}"
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
AUTO_ACTION="${CORGI_TEST_WINDOW_AUTO_ACTION:-}"
WORKSPACE_MODE="${CORGI_TEST_WINDOW_WORKSPACE_MODE:-scratch}"
SCRATCH_ID="${CORGI_TEST_WINDOW_SCRATCH_ID:-pet-life-diary-app}"
SCRATCH_BASE="$TEST_ROOT/scratch-workspaces"
SCRATCH_ROOT=""
EMPTY_WORKSPACE_ID="${CORGI_TEST_WINDOW_EMPTY_ID:-corgi-ui-test-workspace}"
EMPTY_WORKSPACE_BASE="$TEST_ROOT/empty-workspaces"
EMPTY_WORKSPACE_ROOT=""
REPO_WORKSPACE_ID="${CORGI_TEST_WINDOW_REPO_ID:-corgi-ui-test-workspace}"
REPO_WORKSPACE_BASE="$TEST_ROOT/repo-workspaces"
REPO_WORKSPACE_ROOT=""
WORKSPACE_FILE=""

assert_writable_dir() {
	local dir="$1"
	local label="$2"
	local probe
	if [[ ! -d "$dir" ]]; then
		echo "Corgi test $label does not exist: $dir" >&2
		exit 2
	fi
	if ! probe="$(mktemp "$dir/.corgi-write-check.XXXXXX" 2>/dev/null)"; then
		echo "Corgi test $label is not writable: $dir" >&2
		exit 2
	fi
	if ! printf 'ok\n' > "$probe"; then
		rm -f -- "$probe"
		echo "Corgi test $label accepted a probe file but could not write it: $dir" >&2
		exit 2
	fi
	if ! rm -f -- "$probe"; then
		echo "Corgi test $label accepted writes but could not clean up the probe: $dir" >&2
		exit 2
	fi
}

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
ROOT_REAL="$(cd "$ROOT_DIR" && pwd -P)"
TEST_ROOT_REAL="$(cd "$TEST_ROOT" && pwd -P)"
case "$TEST_ROOT_REAL" in
	"$ROOT_REAL"|"$ROOT_REAL/"*)
		echo "Refusing to keep Corgi test-window state inside the development repo: $TEST_ROOT" >&2
		exit 2
		;;
esac

# Test launches should start clean, while production reload keeps session memory.
"$CLOSE_SCRIPT" >/dev/null 2>&1 || true
for _ in 1 2 3; do
	rm -rf "$PROFILE_ROOT" "$RUNTIME_AGENT_ROOT" && break
	sleep 0.4
done
case "$WORKSPACE_MODE" in
	repo)
		if [[ ! "$REPO_WORKSPACE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ || "$REPO_WORKSPACE_ID" == *..* ]]; then
			echo "Unsafe Corgi repo workspace id: $REPO_WORKSPACE_ID" >&2
			exit 2
		fi
		mkdir -p "$REPO_WORKSPACE_BASE"
		REPO_WORKSPACE_BASE_REAL="$(cd "$REPO_WORKSPACE_BASE" && pwd -P)"
		REPO_WORKSPACE_ROOT="$REPO_WORKSPACE_BASE/$REPO_WORKSPACE_ID"
		REPO_WORKSPACE_PARENT_REAL="$(cd "$(dirname "$REPO_WORKSPACE_ROOT")" && pwd -P)"
		if [[ "$REPO_WORKSPACE_PARENT_REAL" != "$REPO_WORKSPACE_BASE_REAL" ]]; then
			echo "Repo test workspace escaped the test root: $REPO_WORKSPACE_ROOT" >&2
			exit 2
		fi
		rm -rf -- "$REPO_WORKSPACE_ROOT"
		mkdir -p -- "$REPO_WORKSPACE_ROOT"
		if command -v rsync >/dev/null 2>&1; then
			rsync -a --delete \
				--exclude='.git/' \
				--exclude='.agent/' \
				--exclude='node_modules/' \
				--exclude='out/' \
				--exclude='.DS_Store' \
				"$ROOT_DIR"/ "$REPO_WORKSPACE_ROOT"/
		else
			(
				cd "$ROOT_DIR"
				tar \
					--exclude './.git' \
					--exclude './.agent' \
					--exclude './node_modules' \
					--exclude './out' \
					--exclude './.DS_Store' \
					-cf - .
			) | (
				cd "$REPO_WORKSPACE_ROOT"
				tar -xf -
			)
		fi
		WORKSPACE_ROOT="$REPO_WORKSPACE_ROOT"
		AGENT_ROOT="$WORKSPACE_ROOT/.agent"
		;;
	empty)
		if [[ -n "$TEST_SCENARIO" ]]; then
			echo "Empty workspace mode does not support seeded scenarios yet." >&2
			exit 2
		fi
		if [[ ! "$EMPTY_WORKSPACE_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ || "$EMPTY_WORKSPACE_ID" == *..* ]]; then
			echo "Unsafe Corgi empty workspace id: $EMPTY_WORKSPACE_ID" >&2
			exit 2
		fi
		mkdir -p "$EMPTY_WORKSPACE_BASE"
		EMPTY_WORKSPACE_BASE_REAL="$(cd "$EMPTY_WORKSPACE_BASE" && pwd -P)"
		EMPTY_WORKSPACE_ROOT="$EMPTY_WORKSPACE_BASE/$EMPTY_WORKSPACE_ID"
		EMPTY_WORKSPACE_PARENT_REAL="$(cd "$(dirname "$EMPTY_WORKSPACE_ROOT")" && pwd -P)"
		if [[ "$EMPTY_WORKSPACE_PARENT_REAL" != "$EMPTY_WORKSPACE_BASE_REAL" ]]; then
			echo "Empty test workspace escaped the test root: $EMPTY_WORKSPACE_ROOT" >&2
			exit 2
		fi
		rm -rf -- "$EMPTY_WORKSPACE_ROOT"
		mkdir -p -- "$EMPTY_WORKSPACE_ROOT"
		WORKSPACE_ROOT="$EMPTY_WORKSPACE_ROOT"
		AGENT_ROOT="$TEST_ROOT/empty-agent"
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
		if [[ "$AUTO_PROMPT_PRESET" == "pet-life-diary-bugfix" ]]; then
			node "$ROOT_DIR/scripts/pet-diary-fixture.cjs" seed-bugfix "$SCRATCH_ROOT"
		elif [[ "$AUTO_PROMPT_PRESET" == "pet-life-diary-filter" || "$AUTO_PROMPT_PRESET" == "pet-life-diary-filter-review-retry" ]]; then
			node "$ROOT_DIR/scripts/pet-diary-fixture.cjs" seed-filter "$SCRATCH_ROOT"
		fi
		WORKSPACE_ROOT="$SCRATCH_ROOT"
		AGENT_ROOT="$SCRATCH_ROOT/.agent"
		;;
	*)
		echo "Unknown Corgi test-window workspace mode: $WORKSPACE_MODE" >&2
		exit 2
		;;
esac
mkdir -p "$AGENT_ROOT"
WORKSPACE_REAL="$(cd "$WORKSPACE_ROOT" && pwd -P)"
AGENT_REAL="$(cd "$AGENT_ROOT" && pwd -P)"
if [[ "$WORKSPACE_REAL" == "$ROOT_REAL" ]]; then
	echo "Refusing to launch Corgi test window against the development repo: $WORKSPACE_ROOT" >&2
	exit 2
fi
if [[ "$WORKSPACE_REAL" != "$TEST_ROOT_REAL/"* ]]; then
	echo "Refusing to launch Corgi test window outside the configured test root: $WORKSPACE_ROOT" >&2
	exit 2
fi
if [[ "$AGENT_REAL" == "$ROOT_REAL/.agent" ]]; then
	echo "Refusing to use the development .agent folder for a Corgi test window: $AGENT_ROOT" >&2
	exit 2
fi
if [[ "$AGENT_REAL" != "$TEST_ROOT_REAL/"* ]]; then
	echo "Refusing to use a test agent root outside the configured test root: $AGENT_ROOT" >&2
	exit 2
fi
assert_writable_dir "$WORKSPACE_ROOT" "workspace"
assert_writable_dir "$AGENT_ROOT" "agent root"
if [[ "$WORKSPACE_MODE" != "empty" ]]; then
	MARKER_FILE="$WORKSPACE_ROOT/THIS_IS_A_CORGI_TEST_WORKSPACE.md"
	cat > "$MARKER_FILE" <<MARKER
# Corgi Test Workspace

This folder is an isolated VS Code test workspace.

- Source extension under test: $ROOT_DIR
- Runtime workspace: $WORKSPACE_ROOT
- Runtime .agent folder: $AGENT_ROOT

It is safe to delete this folder. Do not treat it as the development repo.
MARKER
fi
WORKSPACE_FILE="$TEST_ROOT/Corgi Test Workspace.code-workspace"
node - \
	"$WORKSPACE_FILE" \
	"$WORKSPACE_ROOT" <<'NODE'
const fs = require('fs');
const [filePath, workspaceRoot] = process.argv.slice(2);
fs.writeFileSync(
	filePath,
	JSON.stringify(
		{
			folders: [
				{
					name: 'Corgi Test Workspace',
					path: workspaceRoot,
				},
			],
			settings: {
				'window.title': 'Corgi Test Workspace',
			},
		},
		null,
		2
	) + '\n'
);
NODE
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
	"$WORKSPACE_FILE" \
	"$USER_DATA_DIR" \
	"$STDOUT_LOG" \
	"$STDERR_LOG" \
	"$AUTO_PROMPT_PRESET" \
	"$TEST_SCENARIO" \
	"$AUTO_ACTION" \
	"${CORGI_GOAL_PLAN_SOURCE:-}" \
	"${CORGI_EXECUTOR_RUNTIME:-}" <<'NODE'
const fs = require('fs');
const path = require('path');
const [
	filePath,
	workspaceMode,
	workspaceRoot,
	sourceRoot,
	agentRoot,
	workspaceFile,
	userDataDir,
	stdoutPath,
	stderrPath,
	promptPreset,
	scenario,
	autoAction,
	goalPlanSource,
	executorRuntime,
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
			workspaceFile,
			snapshotPath,
			userDataDir,
			stdoutPath,
			stderrPath,
			promptPreset: promptPreset || null,
			scenario: scenario || null,
			autoAction: autoAction || null,
			goalPlanSource: goalPlanSource || null,
			executorRuntime: executorRuntime || null,
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
	--env CORGI_SEMANTIC_MODE="${CORGI_SEMANTIC_MODE:-sidecar-first}" \
	--env CORGI_SEMANTIC_SIDECAR_RUNTIME="${CORGI_SEMANTIC_SIDECAR_RUNTIME:-app-server}" \
	--env CORGI_GOVERNOR_RUNTIME="${CORGI_GOVERNOR_RUNTIME:-app-server}" \
	--env CORGI_APP_SERVER_EPHEMERAL="${CORGI_APP_SERVER_EPHEMERAL:-1}" \
	--env CORGI_TEST_WINDOW_SCENARIO="$TEST_SCENARIO" \
	--env CORGI_TEST_WINDOW_AUTO_PROMPT="$AUTO_PROMPT" \
	--env CORGI_TEST_WINDOW_AUTO_STEPS="$AUTO_STEPS" \
	--env CORGI_TEST_WINDOW_AUTO_ACTION="$AUTO_ACTION" \
	--env CORGI_TEST_WINDOW_WORKSPACE_MODE="$WORKSPACE_MODE" \
	--env CORGI_GOAL_PLAN_SOURCE="${CORGI_GOAL_PLAN_SOURCE:-}" \
	--env CORGI_EXECUTOR_RUNTIME="${CORGI_EXECUTOR_RUNTIME:-}" \
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
	"$WORKSPACE_FILE"

echo "Launched Corgi test window"
echo "  profile:    $USER_DATA_DIR"
echo "  workspace:  $WORKSPACE_ROOT"
echo "  workspace file: $WORKSPACE_FILE"
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
if [[ -n "$AUTO_ACTION" ]]; then
	echo "  auto-action: $AUTO_ACTION"
fi
if [[ -n "${CORGI_GOAL_PLAN_SOURCE:-}" ]]; then
	echo "  goal plan source: ${CORGI_GOAL_PLAN_SOURCE}"
fi
if [[ -n "${CORGI_EXECUTOR_RUNTIME:-}" ]]; then
	echo "  executor runtime: ${CORGI_EXECUTOR_RUNTIME}"
fi
