#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLOSE_SCRIPT="$ROOT_DIR/scripts/close-corgi-test-window.sh"
STATUS_SCRIPT="$ROOT_DIR/scripts/corgi-test-window-status.cjs"
PROMPT_PRESET="${CORGI_TEST_WINDOW_PROMPT_PRESET:-architecture}"
AUTO_STEPS="${CORGI_TEST_WINDOW_AUTO_STEPS:-plan}"
TIMEOUT_SECONDS="${CORGI_TEST_WINDOW_MONITOR_TIMEOUT_SECONDS:-180}"
SNAPSHOT_GRACE_SECONDS="${CORGI_TEST_WINDOW_SNAPSHOT_GRACE_SECONDS:-30}"

cleanup() {
	"$CLOSE_SCRIPT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$CLOSE_SCRIPT" >/dev/null 2>&1 || true

CORGI_TEST_WINDOW_PROMPT_PRESET="$PROMPT_PRESET" \
CORGI_TEST_WINDOW_AUTO_STEPS="$AUTO_STEPS" \
	bash "$ROOT_DIR/scripts/launch-corgi-test-window.sh"

deadline=$((SECONDS + TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
	status_json="$(node "$STATUS_SCRIPT" --json || true)"
	printf '%s\n' "$status_json"
	snapshot_state="$(node -e "const s=JSON.parse(process.argv[1]); console.log(s.snapshot || '')" "$status_json")"
	if [[ "$snapshot_state" == "missing" && "$SECONDS" -lt "$((deadline - TIMEOUT_SECONDS + SNAPSHOT_GRACE_SECONDS))" ]]; then
		sleep 2
		continue
	fi
	if ! node -e "const s=JSON.parse(process.argv[1]); process.exit(s.ok ? 0 : 1)" "$status_json"; then
		echo "Corgi test window reported an unhealthy state." >&2
		exit 1
	fi
	stage="$(node -e "const s=JSON.parse(process.argv[1]); console.log(s.stage || '')" "$status_json")"
	process_alive="$(node -e "const s=JSON.parse(process.argv[1]); console.log(s.processAlive ? '1' : '0')" "$status_json")"
	if [[ "$AUTO_STEPS" == "plan" && "$stage" == "plan_ready" ]]; then
		echo "Corgi test window reached plan_ready."
		exit 0
	fi
	if [[ "$AUTO_STEPS" == "execute" && "$stage" =~ ^(governor_decision_recorded|reviewer_completed|executor_completed|executor_blocked|reviewer_blocked)$ ]]; then
		echo "Corgi test window reached post-execute checkpoint: $stage."
		exit 0
	fi
	if [[ "$process_alive" != "1" ]]; then
		echo "Corgi test window exited before reaching the expected checkpoint." >&2
		exit 1
	fi
	sleep 5
done

echo "Timed out waiting for Corgi test window auto-run to finish." >&2
exit 1
