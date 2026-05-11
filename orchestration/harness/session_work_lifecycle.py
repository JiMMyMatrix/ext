from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from orchestration.harness import session_execution
from orchestration.harness.paths import (
	default_lane,
	git_branch_name,
	load_json,
	repo_relative,
	resolve_paths,
	trim_text,
	write_json,
)


NextId = Callable[[str], str]
ArtifactFactory = Callable[..., dict[str, Any]]


def build_plan_ready_request(
	model: dict[str, Any],
	now: str,
	*,
	next_id: NextId,
	foreground_request_id: str | None = None,
) -> dict[str, Any] | None:
	summary = model.get("acceptedIntakeSummary")
	if not isinstance(summary, dict):
		return None
	request_id = next_id("plan-ready")
	plan_version = int(model.get("planVersion") or 1)
	return {
		"id": request_id,
		"contextRef": request_id,
		"planContextRef": request_id,
		"planVersion": plan_version,
		"workRef": model.get("currentWorkRef") or model["snapshot"].get("currentWorkRef"),
		"planRef": model.get("currentPlanRef"),
		"revisionReason": model.get("currentPlanRevisionReason"),
		"latestReviewRef": model.get("latestReviewRef"),
		"title": "Plan ready",
		"body": "Review the Governor plan, then execute it or add details for a revision.",
		"requestedAt": now,
		"foregroundRequestId": foreground_request_id,
		"acceptedIntakeSummary": summary,
		"allowedActions": ["execute_plan", "revise_plan"],
	}


def reset_work_loop_state(session: dict[str, Any]) -> None:
	model = session["model"]
	session.setdefault("meta", {})["activeWorkRef"] = None
	for key in [
		"currentPlanRevisionReason",
		"latestReviewRef",
		"latestReviewVerdict",
		"latestGovernorDecisionRef",
		"latestGovernorDecision",
		"revisionOfDispatchRef",
	]:
		model.pop(key, None)
	model["currentWorkRef"] = None
	model["currentPlanRef"] = None
	model["currentAttemptNumber"] = 0
	model["planVersion"] = 0
	model["snapshot"]["currentWorkRef"] = None
	model["snapshot"]["currentPlanVersion"] = None
	model["snapshot"]["currentAttemptNumber"] = None
	model["snapshot"]["latestReviewRef"] = None
	model["snapshot"]["latestReviewVerdict"] = None
	model["snapshot"]["latestGovernorDecisionRef"] = None
	model["snapshot"]["latestGovernorDecision"] = None


def work_index_path(work_ref: str, *, repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).agent_root / "work" / Path(work_ref) / "work.json"


def load_work_index(work_ref: str, *, repo_root: str | Path | None = None) -> dict[str, Any]:
	path = work_index_path(work_ref, repo_root=repo_root)
	return load_json(path) if path.exists() else {}


def save_work_index(
	work_ref: str,
	payload: dict[str, Any],
	*,
	repo_root: str | Path | None = None,
) -> None:
	write_json(work_index_path(work_ref, repo_root=repo_root), payload)


def ensure_work_bundle(
	session: dict[str, Any],
	now: str,
	*,
	next_id: NextId,
	repo_root: str | Path | None = None,
) -> tuple[str, dict[str, Any]]:
	model = session["model"]
	meta = session.setdefault("meta", {})
	work_ref = meta.get("activeWorkRef")
	if not isinstance(work_ref, str) or not work_ref.strip():
		lane = model["snapshot"].get("lane") or default_lane(
			model["snapshot"].get("branch") or git_branch_name(repo_root)
		)
		work_ref = f"{lane}/{next_id('work')}"
		meta["activeWorkRef"] = work_ref
	index = load_work_index(work_ref, repo_root=repo_root)
	if not index:
		index = {
			"work_ref": work_ref,
			"accepted_intake_ref": session_execution.accepted_intake_ref(session, repo_root),
			"goal_ref": model.get("currentGoalRef") or model["snapshot"].get("currentGoalRef"),
			"goal_step_ref": model.get("currentGoalStepRef") or model["snapshot"].get("currentGoalStepRef"),
			"goal_step_index": model.get("currentGoalStepIndex") or model["snapshot"].get("currentGoalStepIndex"),
			"lane": model["snapshot"].get("lane"),
			"task": model["snapshot"].get("task"),
			"status": "planning",
			"current_plan_version": 0,
			"current_plan_ref": None,
			"revision_count": 0,
			"plans": [],
			"attempts": [],
			"reviews": [],
			"decisions": [],
			"created_at": now,
			"updated_at": now,
		}
	else:
		index.setdefault("work_ref", work_ref)
		index.setdefault("accepted_intake_ref", session_execution.accepted_intake_ref(session, repo_root))
		index.setdefault("goal_ref", model.get("currentGoalRef") or model["snapshot"].get("currentGoalRef"))
		index.setdefault("goal_step_ref", model.get("currentGoalStepRef") or model["snapshot"].get("currentGoalStepRef"))
		index.setdefault("goal_step_index", model.get("currentGoalStepIndex") or model["snapshot"].get("currentGoalStepIndex"))
		index.setdefault("status", "planning")
		index.setdefault("current_plan_version", 0)
		index.setdefault("current_plan_ref", None)
		index.setdefault("revision_count", 0)
		index.setdefault("plans", [])
		index.setdefault("attempts", [])
		index.setdefault("reviews", [])
		index.setdefault("decisions", [])
		index["updated_at"] = now
	save_work_index(work_ref, index, repo_root=repo_root)
	model["snapshot"]["currentWorkRef"] = work_ref
	return work_ref, index


def write_plan_artifact(
	session: dict[str, Any],
	now: str,
	body: str,
	*,
	next_id: NextId,
	artifact_factory: ArtifactFactory,
	repo_root: str | Path | None = None,
	revision_reason: str | None = None,
	latest_review_ref: str | None = None,
) -> tuple[str, int]:
	model = session["model"]
	work_ref, index = ensure_work_bundle(session, now, next_id=next_id, repo_root=repo_root)
	plan_version = int(model.get("planVersion") or 1)
	plan_path = resolve_paths(repo_root).agent_root / "work" / Path(work_ref) / "plans" / f"plan-v{plan_version}.md"
	plan_path.parent.mkdir(parents=True, exist_ok=True)
	header = [
		f"# Plan v{plan_version}",
		"",
		f"- work_ref: {work_ref}",
		f"- plan_version: {plan_version}",
	]
	accepted_ref = session_execution.accepted_intake_ref(session, repo_root)
	if accepted_ref:
		header.append(f"- accepted_intake_ref: {accepted_ref}")
	if revision_reason:
		header.append(f"- revision_reason: {revision_reason}")
	if latest_review_ref:
		header.append(f"- latest_review_ref: {latest_review_ref}")
	header.extend(["", trim_text(body) or "Governor did not return plan text.", ""])
	plan_path.write_text("\n".join(header), encoding="utf-8")
	plan_ref = repo_relative(plan_path, repo_root)
	plans = [item for item in index.get("plans", []) if isinstance(item, dict)]
	plans = [item for item in plans if item.get("plan_version") != plan_version]
	plans.append(
		{
			"plan_version": plan_version,
			"plan_ref": plan_ref,
			"created_at": now,
			"revision_reason": revision_reason,
			"latest_review_ref": latest_review_ref,
		}
	)
	index["plans"] = plans
	index["current_plan_version"] = plan_version
	index["current_plan_ref"] = plan_ref
	index["status"] = "plan_ready"
	index["updated_at"] = now
	if plan_version > 1:
		index["revision_count"] = max(int(index.get("revision_count") or 0), plan_version - 1)
	save_work_index(work_ref, index, repo_root=repo_root)
	model["currentPlanRef"] = plan_ref
	model["currentWorkRef"] = work_ref
	model["snapshot"]["currentWorkRef"] = work_ref
	model["snapshot"]["currentPlanVersion"] = plan_version
	model["snapshot"]["latestReviewRef"] = latest_review_ref
	model["snapshot"]["recentArtifacts"] = [
		artifact_factory(plan_ref, summary=f"Governor plan v{plan_version}.", authoritative=True, status="plan_ready"),
		*list(model["snapshot"].get("recentArtifacts") or []),
	]
	return plan_ref, plan_version


def record_work_dispatch_attempt(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any] | None,
	now: str,
	*,
	repo_root: str | Path | None = None,
) -> None:
	if not dispatch_refs:
		return
	work_ref = dispatch_refs.get("work_ref")
	if not isinstance(work_ref, str) or not work_ref.strip():
		return
	index = load_work_index(work_ref, repo_root=repo_root)
	if not index:
		return
	attempt_number = dispatch_refs.get("attempt_number")
	attempts = [item for item in index.get("attempts", []) if isinstance(item, dict)]
	attempts.append(
		{
			"attempt_number": attempt_number,
			"dispatch_ref": dispatch_refs.get("dispatch_ref"),
			"request_ref": dispatch_refs.get("request_ref"),
			"plan_version": dispatch_refs.get("plan_version"),
			"plan_ref": dispatch_refs.get("plan_ref"),
			"created_at": now,
		}
	)
	index["attempts"] = attempts
	index["status"] = "dispatch_queued"
	index["updated_at"] = now
	save_work_index(work_ref, index, repo_root=repo_root)
	model = session["model"]
	model["currentAttemptNumber"] = attempt_number
	model["snapshot"]["currentWorkRef"] = work_ref
	model["snapshot"]["currentAttemptNumber"] = attempt_number


def normalize_legacy_work_refs(
	items: Any,
	*,
	ref_key: str,
	migrated_at: str,
) -> list[dict[str, Any]]:
	normalized: list[dict[str, Any]] = []
	for item in items if isinstance(items, list) else []:
		if isinstance(item, dict):
			normalized.append(item)
			continue
		if isinstance(item, str) and item.strip():
			normalized.append(
				{
					"attempt_number": None,
					"dispatch_ref": None,
					ref_key: item,
					"recorded_at": None,
					"migrated_at": migrated_at,
				}
			)
	return normalized


def record_work_review_and_decision(
	session: dict[str, Any],
	dispatch_refs: dict[str, Any] | None,
	decision: dict[str, Any],
	now: str,
	*,
	repo_root: str | Path | None = None,
) -> dict[str, Any] | None:
	if not dispatch_refs:
		return None
	work_ref = dispatch_refs.get("work_ref")
	if not isinstance(work_ref, str) or not work_ref.strip():
		return None
	index = load_work_index(work_ref, repo_root=repo_root)
	if not index:
		return None
	decision_ref = None
	decision_payload: dict[str, Any] = {}
	dispatch_dir = Path(str(dispatch_refs.get("dispatch_dir") or ""))
	if dispatch_dir:
		decision_path = dispatch_dir / "governor_decision.json"
		if decision_path.exists():
			decision_ref = repo_relative(decision_path, repo_root)
			decision_payload = load_json(decision_path)
	review_ref = dispatch_refs.get("review_ref")
	review_payload: dict[str, Any] = {}
	if isinstance(review_ref, str) and review_ref.strip():
		review_path = resolve_paths(repo_root).repo_root / review_ref
		if review_path.exists():
			review_payload = load_json(review_path)
	review_verdict = trim_text(review_payload.get("verdict"))
	attempt_number = dispatch_refs.get("attempt_number")
	dispatch_ref = dispatch_refs.get("dispatch_ref")
	reviews = normalize_legacy_work_refs(
		index.get("reviews", []),
		ref_key="review_ref",
		migrated_at=now,
	)
	if isinstance(review_ref, str) and review_ref.strip():
		reviews = [
			item
			for item in reviews
			if item.get("dispatch_ref") != dispatch_ref
			or item.get("attempt_number") != attempt_number
		]
		reviews.append(
			{
				"attempt_number": attempt_number,
				"dispatch_ref": dispatch_ref,
				"review_ref": review_ref,
				"verdict": review_verdict or None,
				"recorded_at": now,
			}
		)
	index["reviews"] = reviews
	decision_value = trim_text(decision_payload.get("decision"))
	decisions = normalize_legacy_work_refs(
		index.get("decisions", []),
		ref_key="decision_ref",
		migrated_at=now,
	)
	if decision_ref:
		decisions = [
			item
			for item in decisions
			if item.get("dispatch_ref") != dispatch_ref
			or item.get("attempt_number") != attempt_number
		]
		decisions.append(
			{
				"attempt_number": attempt_number,
				"dispatch_ref": dispatch_ref,
				"decision_ref": decision_ref,
				"decision": decision_value or None,
				"recommended_next_action": trim_text(
					decision_payload.get("recommended_next_action")
				)
				or None,
				"recorded_at": now,
			}
		)
	index["decisions"] = decisions
	index["status"] = "completed" if decision_value == "accept" else "needs_replan"
	index["updated_at"] = now
	save_work_index(work_ref, index, repo_root=repo_root)
	model = session["model"]
	model["latestReviewRef"] = review_ref if isinstance(review_ref, str) and review_ref.strip() else None
	model["latestReviewVerdict"] = review_verdict or None
	model["latestGovernorDecisionRef"] = decision_ref
	model["latestGovernorDecision"] = decision_value or None
	model["snapshot"]["latestReviewRef"] = model["latestReviewRef"]
	model["snapshot"]["latestReviewVerdict"] = model["latestReviewVerdict"]
	model["snapshot"]["latestGovernorDecisionRef"] = decision_ref
	model["snapshot"]["latestGovernorDecision"] = model["latestGovernorDecision"]
	return decision_payload or None


def decision_needs_replan(decision_payload: dict[str, Any] | None) -> bool:
	if not isinstance(decision_payload, dict):
		return False
	next_action = trim_text(decision_payload.get("recommended_next_action"))
	decision = decision_payload.get("decision")
	if decision == "reject":
		return next_action in {
			"redispatch_or_reject",
			"redispatch_or_escalate",
			"replan",
		}
	return decision == "needs_verification" and next_action in {
		"bounded_verification_or_reviewer_subagent",
		"bounded_verification",
		"replan",
	}
