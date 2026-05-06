#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_DATA_DIR="$ROOT_DIR/.agent/test-window/vscode-profile/user-data"
LEGACY_USER_DATA_DIR="$ROOT_DIR/.agent/vscode-governor-first-test-user-data"

assert_test_profile_path() {
	local profile_dir="$1"
	case "$profile_dir" in
		"$ROOT_DIR/.agent/test-window/"*|"$ROOT_DIR/.agent/vscode-governor-first-test-user-data")
			return
			;;
		*)
			echo "Refusing to close non-test VS Code profile: $profile_dir" >&2
			exit 2
			;;
	esac
}

close_profile() {
	local profile_dir="$1"
	assert_test_profile_path "$profile_dir"
	local main_pids
	main_pids="$(
		ps -axo pid=,ppid=,command= |
			awk -v profile="$profile_dir" '
				index($0, profile) > 0 &&
					(index($0, "Visual Studio Code.app") > 0 ||
					 index($0, "Code Helper") > 0 ||
					 index($0, "MacOS/Code") > 0) {
					print $2
				}
			' |
			sort -u
	)"
	if [[ -n "$main_pids" ]]; then
		while IFS= read -r pid; do
			[[ -n "$pid" ]] || continue
			kill -TERM "$pid" >/dev/null 2>&1 || true
		done <<< "$main_pids"
		for _ in 1 2 3 4 5 6 7 8 9 10; do
			if ! pgrep -f "$profile_dir" >/dev/null 2>&1; then
				return
			fi
			sleep 0.5
		done
	fi
	pkill -TERM -f "$profile_dir" >/dev/null 2>&1 || true
	for _ in 1 2 3 4 5; do
		if ! pgrep -f "$profile_dir" >/dev/null 2>&1; then
			return
		fi
		sleep 0.3
	done
	pkill -9 -f "$profile_dir" >/dev/null 2>&1 || true
}

close_profile "$USER_DATA_DIR"
close_profile "$LEGACY_USER_DATA_DIR"

if pgrep -f "$USER_DATA_DIR|$LEGACY_USER_DATA_DIR" >/dev/null 2>&1; then
	echo "Corgi test window still has live processes." >&2
	exit 1
fi

echo "Closed Corgi test window"
