from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration.harness import session_permissions
from orchestration.harness import session_work_lifecycle
from orchestration.harness.paths import git_branch_name, load_json, resolve_paths, utc_now, write_json
from orchestration.harness.session_feed import _feed_item, _next_id
from orchestration.harness.start_guard import collect_active_dispatches


def initial_model(now: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	branch = git_branch_name(repo_root)
	return {
		"snapshot": {
			"sessionRef": _next_id("session"),
			"lane": None,
			"branch": branch,
			"task": None,
			"currentActor": "intake_shell",
			"currentStage": "idle",
			"permissionScope": "unset",
			"runState": "idle",
			"transportState": "connected",
			"pendingPermissionRequest": None,
			"pendingInterrupt": None,
			"recentArtifacts": [],
			"currentWorkRef": None,
			"currentParallelSetRef": None,
			"activeParallelDispatchCount": None,
			"currentPlanVersion": None,
			"currentAttemptNumber": None,
			"latestReviewRef": None,
			"latestReviewVerdict": None,
			"latestGovernorDecisionRef": None,
			"latestGovernorDecision": None,
			"snapshotFreshness": {"receivedAt": now},
		},
		"feed": [
			_feed_item(
				"system_status",
				"Ready when you are",
				"Ask Corgi to work on this repo.",
				authoritative=True,
				now=now,
			)
		],
		"activeClarification": None,
		"activeForegroundRequestId": None,
		"acceptedIntakeSummary": None,
		"planReadyRequest": None,
		"currentWorkRef": None,
		"currentParallelSetRef": None,
		"activeParallelDispatchCount": None,
		"currentPlanRef": None,
		"currentAttemptNumber": 0,
		"latestReviewRef": None,
		"latestReviewVerdict": None,
		"latestGovernorDecisionRef": None,
		"latestGovernorDecision": None,
		"planVersion": 0,
	}


def active_parallel_snapshot(
	repo_root: str | Path | None,
	*,
	lane: str | None,
) -> dict[str, Any]:
	try:
		paths = resolve_paths(repo_root)
		active = collect_active_dispatches(paths.repo_root, lane=lane)
	except Exception:
		return {"currentParallelSetRef": None, "activeParallelDispatchCount": None}
	if len(active) < 2:
		return {"currentParallelSetRef": None, "activeParallelDispatchCount": None}
	set_refs = {
		dispatch.get("parallel_set_ref")
		for dispatch in active
		if isinstance(dispatch.get("parallel_set_ref"), str) and dispatch.get("parallel_set_ref").strip()
	}
	return {
		"currentParallelSetRef": next(iter(set_refs)) if len(set_refs) == 1 else None,
		"activeParallelDispatchCount": len(active),
	}


def _restore_plan_ready_request_if_needed(
	session: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
) -> None:
	model = session["model"]
	snapshot = model["snapshot"]
	if not (
		model.get("planReadyRequest") is None
		and model.get("acceptedIntakeSummary")
		and snapshot.get("currentStage") == "plan_ready"
		and snapshot.get("permissionScope") == "plan"
		and not snapshot.get("pendingPermissionRequest")
		and not model.get("activeClarification")
		and snapshot.get("runState") != "running"
	):
		return
	model["planVersion"] = int(model.get("planVersion") or 1)
	model["planReadyRequest"] = session_work_lifecycle.build_plan_ready_request(
		model,
		now,
		next_id=_next_id,
		foreground_request_id=model.get("activeForegroundRequestId"),
	)


def normalize_session(session: dict[str, Any], now: str, *, repo_root: str | Path | None = None) -> None:
	session.setdefault("meta", {})
	session["meta"].setdefault("activeIntakeRef", None)
	session["meta"].setdefault("activeWorkRef", None)
	session["meta"].setdefault("processedRequestIds", {})
	session["meta"].setdefault("governorDialogue", {})
	model = session.setdefault("model", initial_model(now, repo_root=repo_root))
	snapshot = model.setdefault("snapshot", {})
	snapshot.setdefault("sessionRef", _next_id("session"))
	snapshot.setdefault("lane", None)
	snapshot.setdefault("branch", git_branch_name(repo_root))
	snapshot.setdefault("task", None)
	snapshot.setdefault("currentActor", "intake_shell")
	snapshot.setdefault("currentStage", "idle")
	if "permissionScope" not in snapshot:
		legacy_access_mode = snapshot.get("accessMode")
		snapshot["permissionScope"] = (
			"execute" if legacy_access_mode == "full_access" else "unset"
		)
	snapshot.setdefault("runState", "idle")
	snapshot.setdefault("transportState", "connected")
	if "pendingPermissionRequest" not in snapshot:
		legacy_pending = snapshot.get("pendingApproval")
		if isinstance(legacy_pending, dict):
			snapshot["pendingPermissionRequest"] = {
				**legacy_pending,
				"recommendedScope": "plan",
				"allowedScopes": session_permissions.allowed_permission_scopes("plan"),
			}
		else:
			snapshot["pendingPermissionRequest"] = None
	snapshot.setdefault("pendingInterrupt", None)
	snapshot.setdefault("recentArtifacts", [])
	snapshot.setdefault("currentWorkRef", model.get("currentWorkRef"))
	parallel_state = active_parallel_snapshot(repo_root, lane=snapshot.get("lane"))
	snapshot["currentParallelSetRef"] = parallel_state["currentParallelSetRef"]
	snapshot["activeParallelDispatchCount"] = parallel_state["activeParallelDispatchCount"]
	snapshot.setdefault("currentPlanVersion", model.get("planVersion"))
	snapshot.setdefault("currentAttemptNumber", model.get("currentAttemptNumber"))
	snapshot.setdefault("latestReviewRef", model.get("latestReviewRef"))
	snapshot.setdefault("latestReviewVerdict", model.get("latestReviewVerdict"))
	snapshot.setdefault("latestGovernorDecisionRef", model.get("latestGovernorDecisionRef"))
	snapshot.setdefault("latestGovernorDecision", model.get("latestGovernorDecision"))
	snapshot.setdefault("snapshotFreshness", {"receivedAt": now})
	model.setdefault("feed", [])
	model.setdefault("activeClarification", None)
	model.setdefault("activeForegroundRequestId", None)
	model.setdefault("acceptedIntakeSummary", None)
	model.setdefault("planReadyRequest", None)
	model.setdefault("currentWorkRef", session["meta"].get("activeWorkRef"))
	model["currentParallelSetRef"] = snapshot.get("currentParallelSetRef")
	model["activeParallelDispatchCount"] = snapshot.get("activeParallelDispatchCount")
	model.setdefault("currentPlanRef", None)
	model.setdefault("currentAttemptNumber", 0)
	model.setdefault("latestReviewRef", snapshot.get("latestReviewRef"))
	model.setdefault("latestReviewVerdict", snapshot.get("latestReviewVerdict"))
	model.setdefault("latestGovernorDecisionRef", snapshot.get("latestGovernorDecisionRef"))
	model.setdefault("latestGovernorDecision", snapshot.get("latestGovernorDecision"))
	model.setdefault("planVersion", 0)
	if isinstance(model.get("activeClarification"), dict):
		model["activeClarification"].setdefault(
			"contextRef", model["activeClarification"].get("id")
		)
	if isinstance(snapshot.get("pendingPermissionRequest"), dict):
		snapshot["pendingPermissionRequest"].setdefault(
			"contextRef", snapshot["pendingPermissionRequest"].get("id")
		)
		snapshot["pendingPermissionRequest"].setdefault("recommendedScope", "plan")
		snapshot["pendingPermissionRequest"]["allowedScopes"] = session_permissions.allowed_permission_scopes(
			snapshot["pendingPermissionRequest"].get("recommendedScope")
		)
		snapshot["pendingPermissionRequest"].setdefault(
			"continuationKind", "intake_acceptance"
		)
		snapshot["pendingPermissionRequest"].setdefault(
			"foregroundRequestId", None
		)
	if isinstance(snapshot.get("pendingInterrupt"), dict):
		snapshot["pendingInterrupt"].setdefault(
			"contextRef",
			f"interrupt:{snapshot['snapshotFreshness'].get('receivedAt', now)}",
		)
	_restore_plan_ready_request_if_needed(session, now, repo_root=repo_root)


def load_session(repo_root: str | Path | None = None) -> dict[str, Any]:
	now = utc_now()
	session_path = resolve_paths(repo_root).ui_session_path
	payload = load_json(session_path, default=None)
	if payload is None:
		payload = {
			"model": initial_model(now, repo_root=repo_root),
			"meta": {"activeIntakeRef": None},
		}
		normalize_session(payload, now, repo_root=repo_root)
		write_json(session_path, payload)
		return payload
	normalize_session(payload, now, repo_root=repo_root)
	return payload


def save_session(session: dict[str, Any], *, repo_root: str | Path | None = None) -> None:
	write_json(resolve_paths(repo_root).ui_session_path, session)


def refresh_snapshot(model: dict[str, Any], now: str, **overrides: Any) -> None:
	model["snapshot"].update(overrides)
	model["snapshot"]["snapshotFreshness"] = {"receivedAt": now}


def public_model(session: dict[str, Any]) -> dict[str, Any]:
	return session["model"]
