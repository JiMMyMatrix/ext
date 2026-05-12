from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestration.harness.artifacts import ArtifactContractError, load_review_artifact
from orchestration.harness.paths import load_json, resolve_agent_root, resolve_paths
from orchestration.harness.reviewer import ReviewerContractViolation, resolve_review_artifact_path


def _effective_repo_root(repo_root: str | Path | None = None) -> Path:
	return resolve_paths(repo_root).repo_root


def dispatch_dir_for_ref(repo_root: str | Path | None, dispatch_ref: str) -> Path:
	root = _effective_repo_root(repo_root)
	return resolve_agent_root(root) / "dispatches" / Path(dispatch_ref)


def _safe_dispatch_dir_for_ref(
	repo_root: str | Path | None,
	dispatch_ref: str,
	blockers: list[str],
) -> Path | None:
	if not isinstance(dispatch_ref, str) or not dispatch_ref.strip():
		blockers.append("missing_dispatch_ref")
		return None
	dispatch_path = Path(dispatch_ref.strip())
	if dispatch_path.is_absolute():
		blockers.append("dispatch_ref_not_repo_local")
		return None
	root = _effective_repo_root(repo_root)
	dispatches_root = (resolve_agent_root(root) / "dispatches").resolve()
	dispatch_dir = (dispatches_root / dispatch_path).resolve()
	try:
		dispatch_dir.relative_to(dispatches_root)
	except ValueError:
		blockers.append("dispatch_ref_not_repo_local")
		return None
	return dispatch_dir


def dispatch_ref_from_decision_ref(repo_root: str | Path | None, decision_ref: Any) -> str | None:
	if not isinstance(decision_ref, str) or not decision_ref.strip():
		return None
	root = _effective_repo_root(repo_root)
	decision_path = (root / decision_ref).resolve()
	dispatches_root = (resolve_agent_root(root) / "dispatches").resolve()
	try:
		dispatch_dir = decision_path.parent.relative_to(dispatches_root)
	except ValueError:
		return None
	if decision_path.name != "governor_decision.json":
		return None
	return str(dispatch_dir)


def _repo_relative(path: Path, repo_root: str | Path | None) -> str:
	return str(path.resolve().relative_to(_effective_repo_root(repo_root)))


def _load_required_json(path: Path, artifact_name: str, blockers: list[str]) -> dict[str, Any] | None:
	if not path.exists():
		blockers.append(f"missing_{artifact_name}")
		return None
	try:
		payload = load_json(path)
	except Exception as exc:
		blockers.append(f"invalid_{artifact_name}:{exc}")
		return None
	if not isinstance(payload, dict):
		blockers.append(f"invalid_{artifact_name}:not_object")
		return None
	return payload


def _artifact_ref_exists(repo_root: str | Path | None, raw_ref: Any, blockers: list[str], label: str) -> Path | None:
	if not isinstance(raw_ref, str) or not raw_ref.strip():
		blockers.append(f"missing_{label}_ref")
		return None
	path = Path(raw_ref)
	if path.is_absolute():
		blockers.append(f"{label}_ref_not_repo_local")
		return None
	root = _effective_repo_root(repo_root)
	resolved = (root / path).resolve()
	try:
		resolved.relative_to(root)
	except ValueError:
		blockers.append(f"{label}_ref_not_repo_local")
		return None
	if not resolved.exists():
		blockers.append(f"missing_{label}:{raw_ref}")
		return None
	return resolved


def _required_outputs_exist(repo_root: str | Path | None, request: dict[str, Any], blockers: list[str]) -> None:
	root = _effective_repo_root(repo_root)
	for rel_path in request.get("required_outputs", []):
		if not isinstance(rel_path, str) or not rel_path.strip():
			continue
		path = Path(rel_path)
		if path.is_absolute():
			blockers.append(f"required_output_not_repo_local:{rel_path}")
			continue
		resolved = (root / path).resolve()
		try:
			resolved.relative_to(root)
		except ValueError:
			blockers.append(f"required_output_not_repo_local:{rel_path}")
			continue
		if not resolved.exists():
			blockers.append(f"missing_required_output:{rel_path}")


def _review_blockers(
	repo_root: str | Path | None,
	dispatch_ref: str,
	request: dict[str, Any],
	decision: dict[str, Any],
) -> list[str]:
	blockers: list[str] = []
	if request.get("review_required") is not True:
		return blockers
	raw_review_ref = request.get("review_artifact_path") or decision.get("review_ref")
	try:
		review_path = resolve_review_artifact_path(_effective_repo_root(repo_root), dispatch_ref, raw_review_ref)
	except ReviewerContractViolation as exc:
		return [str(exc)]
	if not review_path.exists():
		return [f"missing_review:{_repo_relative(review_path, repo_root)}"]
	try:
		review = load_review_artifact(review_path)
	except ArtifactContractError as exc:
		return [f"invalid_review:{exc}"]
	if review.get("dispatch_ref") != dispatch_ref:
		blockers.append("review_dispatch_ref_mismatch")
	if review.get("verdict") != "pass":
		blockers.append("review_not_pass")
	if decision.get("review_ref") and decision.get("review_ref") != _repo_relative(review_path, repo_root):
		blockers.append("decision_review_ref_mismatch")
	return blockers


def accepted_dispatch_blockers(repo_root: str | Path | None, dispatch_ref: str) -> list[str]:
	"""Return reasons why a dispatch is not safe to depend on as accepted output."""
	from orchestration.harness import dispatch_contracts

	blockers: list[str] = []
	root = _effective_repo_root(repo_root)
	dispatch_dir = _safe_dispatch_dir_for_ref(root, dispatch_ref, blockers)
	if dispatch_dir is None:
		return blockers
	request_path = dispatch_dir / "request.json"
	result_path = dispatch_dir / "result.json"
	decision_path = dispatch_dir / "governor_decision.json"

	request = _load_required_json(request_path, "request", blockers)
	result = _load_required_json(result_path, "result", blockers)
	decision = _load_required_json(decision_path, "governor_decision", blockers)
	if not isinstance(request, dict) or not isinstance(result, dict) or not isinstance(decision, dict):
		return blockers

	request_failures: list[str] = []
	dispatch_contracts.validate_request(request, request_failures)
	# validate_request only has the payload and may validate review paths against the
	# process cwd when ORCHESTRATION_AGENT_ROOT points at a scratch workspace. The
	# accepted-dispatch kernel re-validates the review artifact below with the real
	# repo_root, so avoid double-counting that compatibility false positive here.
	request_failures = [
		failure
		for failure in request_failures
		if not failure.startswith("reviewer_contract_violation:review_artifact_path")
	]
	blockers.extend(f"request_contract:{failure}" for failure in request_failures)

	result_failures: list[str] = []
	dispatch_contracts.validate_result(result, result_failures, request=request, repo_root=root)
	blockers.extend(f"result_contract:{failure}" for failure in result_failures)

	decision_failures: list[str] = []
	dispatch_contracts.validate_governor_decision(decision, decision_failures)
	blockers.extend(f"decision_contract:{failure}" for failure in decision_failures)

	for label, payload in [
		("request", request),
		("result", result),
		("governor_decision", decision),
	]:
		if payload.get("dispatch_ref") != dispatch_ref:
			blockers.append(f"{label}_dispatch_ref_mismatch")

	if result.get("status") != "completed":
		blockers.append("result_not_completed")
	if result.get("blocker"):
		blockers.append("result_has_blocker")
	auto_validated = result.get("auto_validated")
	if not isinstance(auto_validated, list) or not auto_validated:
		blockers.append("missing_validation_evidence")
	if decision.get("decision") != "accept":
		blockers.append("decision_not_accept")

	expected_result_ref = _repo_relative(result_path, repo_root)
	if decision.get("result_ref") != expected_result_ref:
		blockers.append("decision_result_ref_mismatch")
	_artifact_ref_exists(repo_root, decision.get("result_ref"), blockers, "decision_result")

	_required_outputs_exist(repo_root, request, blockers)
	blockers.extend(_review_blockers(repo_root, dispatch_ref, request, decision))

	return blockers


def dispatch_is_accepted(repo_root: str | Path | None, dispatch_ref: str) -> bool:
	return not accepted_dispatch_blockers(repo_root, dispatch_ref)
