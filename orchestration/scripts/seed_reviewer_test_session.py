#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness import session  # noqa: E402
from orchestration.harness.paths import load_json, repo_relative, resolve_paths, utc_now  # noqa: E402
from orchestration.scripts.seed_executor_test_session import seed_plan_ready_session  # noqa: E402


def _latest_dispatch_refs(model: dict[str, Any], repo_root: Path) -> dict[str, Any]:
	request_ref = None
	for artifact in model["snapshot"].get("recentArtifacts") or []:
		path = artifact.get("path") if isinstance(artifact, dict) else None
		if isinstance(path, str) and path.endswith("/request.json"):
			request_ref = path
			break

	if request_ref is None:
		agent_root = resolve_paths(repo_root).agent_root
		requests = sorted(
			agent_root.glob("dispatches/**/request.json"),
			key=lambda item: item.stat().st_mtime,
			reverse=True,
		)
		if not requests:
			raise SystemExit("reviewer fixture could not find seeded dispatch request")
		request_ref = repo_relative(requests[0], repo_root)

	dispatch_dir = (repo_root / request_ref).parent
	request = load_json(dispatch_dir / "request.json")
	review_ref = request.get("review_artifact_path")
	if not isinstance(review_ref, str) or not review_ref.strip():
		raise SystemExit("seeded dispatch does not expose a reviewer artifact path")
	return {
		"dispatch_ref": request["dispatch_ref"],
		"request_ref": request_ref,
		"state_ref": repo_relative(dispatch_dir / "state.json", repo_root),
		"review_ref": review_ref,
		"dispatch_dir": str(dispatch_dir),
	}


def seed_reviewer_ready_session(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
	payload = seed_plan_ready_session(repo_root)
	model = payload["model"]
	model["snapshot"]["permissionScope"] = "execute"
	session.save_session(payload, repo_root=repo_root)

	model = session.dispatch_session_action(
		"execute_plan",
		request_id="corgi-fixture:reviewer-dispatch",
		session_ref=model["snapshot"]["sessionRef"],
		context_ref=model["planReadyRequest"]["contextRef"],
		repo_root=repo_root,
	)
	payload = session.load_session(repo_root)
	dispatch_refs = _latest_dispatch_refs(model, repo_root)
	now = utc_now()
	existing_artifacts = list(payload["model"]["snapshot"].get("recentArtifacts") or [])
	execution = session._consume_executor_dispatch(  # noqa: SLF001 - dev fixture seeds one module boundary.
		payload,
		dispatch_refs,
		now,
		repo_root=repo_root,
		request_id="corgi-fixture:reviewer-executor",
	)
	payload["model"]["snapshot"]["recentArtifacts"] = execution["artifacts"] + existing_artifacts
	payload["model"]["activeForegroundRequestId"] = "corgi-fixture:reviewer"
	session._refresh_snapshot(  # noqa: SLF001
		payload["model"],
		now,
		currentActor="reviewer" if execution.get("ok") else "executor",
		currentStage="reviewer_ready" if execution.get("ok") else "executor_blocked",
		runState="idle",
		transportState="connected",
	)
	session.save_session(payload, repo_root=repo_root)
	return payload, dispatch_refs


def seed_reviewer_completed_session(repo_root: Path) -> dict[str, Any]:
	payload, dispatch_refs = seed_reviewer_ready_session(repo_root)
	now = utc_now()
	existing_artifacts = list(payload["model"]["snapshot"].get("recentArtifacts") or [])
	review = session._consume_reviewer_dispatch(  # noqa: SLF001 - dev fixture isolates Reviewer consumption.
		payload,
		dispatch_refs,
		now,
		repo_root=repo_root,
		request_id="corgi-fixture:reviewer-run",
	)
	payload["model"]["snapshot"]["recentArtifacts"] = review["artifacts"] + existing_artifacts
	if review.get("ok"):
		payload["model"]["activeForegroundRequestId"] = None
	session._refresh_snapshot(  # noqa: SLF001
		payload["model"],
		now,
		currentActor="reviewer",
		currentStage="reviewer_completed" if review.get("ok") else "reviewer_blocked",
		runState="idle",
		transportState="connected",
	)
	session.save_session(payload, repo_root=repo_root)
	return payload


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(
		description="Seed a dev/test Corgi session for modular Reviewer testing."
	)
	parser.add_argument(
		"--scenario",
		choices=["reviewer-ready", "reviewer-completed"],
		default="reviewer-completed",
		help="reviewer-ready stops after Executor output; reviewer-completed pre-runs Reviewer.",
	)
	parser.add_argument("--root", default=".", help="Repository root to seed.")
	return parser


def main(argv: list[str] | None = None) -> int:
	args = build_parser().parse_args(argv)
	repo_root = Path(args.root).resolve()
	if args.scenario == "reviewer-ready":
		seed_reviewer_ready_session(repo_root)
	else:
		seed_reviewer_completed_session(repo_root)
	print(f"Seeded Corgi test session: {args.scenario}")
	print(f"  session: {resolve_paths(repo_root).ui_session_path}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
