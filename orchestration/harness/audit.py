from __future__ import annotations

import subprocess

from orchestration.harness.paths import resolve_paths


def run(command: str, argv: list[str], *, repo_root: str | None = None) -> int:
	if command not in {"verify-architecture", "verify-paths", "verify-role-policy"}:
		raise ValueError(f"unsupported audit command: {command}")
	paths = resolve_paths(repo_root)
	completed = subprocess.run(
		["bash", str(paths.scripts_root / "verify_architecture.sh"), *argv],
		cwd=paths.repo_root,
	)
	return completed.returncode
