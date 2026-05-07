from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from orchestration.harness.paths import resolve_agent_root, unique_strings
from orchestration.scripts.overlap_worktree import OVERLAP_ISOLATION_MODE

MAX_PARALLEL_SET_ACTIVE = 2
PARALLEL_SET_FILENAME = "parallel_dispatch_set.json"
PRE_DISPATCH_REVIEW_FILENAME = "pre_dispatch_review.json"
SUBAGENT_ONLY_MODES = {"guided_agent", "strict_refactor"}
INTEGRATION_POLICIES = {"choose_one", "can_stack"}
CPU_HINTS = {"low", "medium", "high"}
GPU_HINTS = {"none", "shared", "exclusive"}

DependencyChecker = Callable[[Path, str], bool]


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_repo_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip("/")


def repo_local_path_valid(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    normalized = normalize_repo_path(value)
    path = Path(normalized)
    return not path.is_absolute() and ".." not in path.parts


def _require_repo_local_path(value: Any, failures: List[str], field: str) -> Optional[str]:
    if not repo_local_path_valid(value):
        failures.append(f"{field} must be a repo-local non-empty path")
        return None
    return normalize_repo_path(str(value))


def _require_string(value: Any, failures: List[str], field: str) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        failures.append(f"{field} must be a non-empty string")
        return None
    return value.strip()


def _require_string_list(value: Any, failures: List[str], field: str) -> Optional[List[str]]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        failures.append(f"{field} must be a list of non-empty strings")
        return None
    return unique_strings(value)


def dispatch_dir_for_ref(repo_root: Path, dispatch_ref: str) -> Path:
    return resolve_agent_root(repo_root) / "dispatches" / Path(dispatch_ref)


def parallel_set_artifact_path(repo_root: Path, parallel_set_ref: str) -> Path:
    return resolve_agent_root(repo_root) / "parallel_sets" / Path(parallel_set_ref) / PARALLEL_SET_FILENAME


def parallel_set_max_active(repo_root: Path, parallel_set_ref: Any) -> Optional[int]:
    failures: List[str] = []
    normalized_ref = _require_repo_local_path(parallel_set_ref, failures, "parallel_set_ref")
    if failures or normalized_ref is None:
        return None
    set_path = parallel_set_artifact_path(repo_root, normalized_ref)
    if not set_path.exists():
        return None
    try:
        payload = load_json(set_path)
    except Exception:
        return None
    max_active = payload.get("max_active")
    if isinstance(max_active, int) and 1 <= max_active <= MAX_PARALLEL_SET_ACTIVE:
        return max_active
    return None


def default_pre_dispatch_review_artifact_path(dispatch_ref: str) -> str:
    return f".agent/reviews/{dispatch_ref}/{PRE_DISPATCH_REVIEW_FILENAME}"


def validate_pre_dispatch_review_artifact_path(
    value: Any,
    failures: List[str],
    *,
    field: str = "pre_dispatch_review_artifact_path",
) -> Optional[str]:
    normalized = _require_repo_local_path(value, failures, field)
    if normalized is None:
        return None
    if not normalized.startswith(".agent/reviews/"):
        failures.append(f"{field} must stay under .agent/reviews/")
    if Path(normalized).name != PRE_DISPATCH_REVIEW_FILENAME:
        failures.append(f"{field} must end with {PRE_DISPATCH_REVIEW_FILENAME}")
    return normalized


def validate_resource_hints(payload: Any, failures: List[str], *, prefix: str = "resource_hints") -> None:
    if payload is None:
        return
    if not isinstance(payload, dict):
        failures.append(f"{prefix} must be an object")
        return
    cpu = payload.get("cpu")
    if cpu is not None and cpu not in CPU_HINTS:
        failures.append(f"{prefix}.cpu must be low, medium, or high")
    gpu = payload.get("gpu")
    if gpu is not None and gpu not in GPU_HINTS:
        failures.append(f"{prefix}.gpu must be none, shared, or exclusive")
    for field in ["memory_gb", "storage_gb"]:
        value = payload.get(field)
        if value is not None and (not isinstance(value, (int, float)) or value < 0):
            failures.append(f"{prefix}.{field} must be a non-negative number")


def validate_parallel_request_metadata(payload: Dict[str, Any], failures: List[str]) -> None:
    parallel_set_ref = payload.get("parallel_set_ref")
    if parallel_set_ref is not None:
        _require_repo_local_path(parallel_set_ref, failures, "request.json parallel_set_ref")
        if payload.get("pre_dispatch_review_required") is not True:
            failures.append("request.json pre_dispatch_review_required must be true when parallel_set_ref is set")
        if not isinstance(payload.get("scope_reservations"), list) or not payload.get("scope_reservations"):
            failures.append("request.json parallel_set_ref requires non-empty scope_reservations")
        if not isinstance(payload.get("work_ref"), str) or not payload.get("work_ref", "").strip():
            failures.append("request.json parallel_set_ref requires work_ref")

    pre_dispatch_required = payload.get("pre_dispatch_review_required")
    if pre_dispatch_required is not None and not isinstance(pre_dispatch_required, bool):
        failures.append("request.json pre_dispatch_review_required must be a boolean")
    if pre_dispatch_required is True and not payload.get("pre_dispatch_review_artifact_path"):
        failures.append("request.json pre_dispatch_review_artifact_path is required when pre_dispatch_review_required is true")

    review_path = payload.get("pre_dispatch_review_artifact_path")
    if review_path is not None:
        validate_pre_dispatch_review_artifact_path(
            review_path,
            failures,
            field="request.json pre_dispatch_review_artifact_path",
        )

    for field in ["parallel_group", "parallel_intent"]:
        if field in payload:
            _require_string(payload.get(field), failures, f"request.json {field}")

    validate_resource_hints(payload.get("resource_hints"), failures, prefix="request.json resource_hints")


def validate_pre_dispatch_review_payload(
    payload: Dict[str, Any],
    failures: List[str],
    *,
    expected_dispatch_ref: str,
    covered_dispatch_refs: Optional[Iterable[str]] = None,
) -> None:
    if payload.get("dispatch_ref") != expected_dispatch_ref:
        failures.append("pre_dispatch_review.json dispatch_ref mismatch")
    if payload.get("review_phase") != "pre_dispatch":
        failures.append("pre_dispatch_review.json review_phase must be pre_dispatch")
    if payload.get("verdict") != "pass":
        failures.append("pre_dispatch_review.json verdict must be pass")
    if covered_dispatch_refs is not None:
        expected = sorted(unique_strings(list(covered_dispatch_refs)))
        actual = payload.get("covered_dispatch_refs")
        if not isinstance(actual, list) or any(not isinstance(item, str) or not item.strip() for item in actual):
            failures.append("pre_dispatch_review.json covered_dispatch_refs must be a list of non-empty strings")
        elif sorted(unique_strings(actual)) != expected:
            failures.append("pre_dispatch_review.json covered_dispatch_refs must match parallel set members")


def _pre_dispatch_review_blockers_for_path(
    repo_root: Path,
    artifact_ref: str,
    *,
    expected_dispatch_ref: str,
    covered_dispatch_refs: Optional[Iterable[str]] = None,
) -> List[str]:
    failures: List[str] = []
    normalized = validate_pre_dispatch_review_artifact_path(artifact_ref, failures)
    if failures:
        return [f"pre_dispatch_review_invalid:{expected_dispatch_ref}:{failure}" for failure in failures]
    review_path = repo_root / normalized
    if not review_path.exists():
        return [f"pre_dispatch_review_missing:{expected_dispatch_ref}:{normalized}"]
    try:
        payload = load_json(review_path)
    except Exception as exc:
        return [f"pre_dispatch_review_invalid:{expected_dispatch_ref}:{exc}"]
    failures = []
    validate_pre_dispatch_review_payload(
        payload,
        failures,
        expected_dispatch_ref=expected_dispatch_ref,
        covered_dispatch_refs=covered_dispatch_refs,
    )
    return [f"pre_dispatch_review_invalid:{expected_dispatch_ref}:{failure}" for failure in failures]


def pre_dispatch_review_blockers(repo_root: Path, request: Dict[str, Any]) -> List[str]:
    if request.get("parallel_set_ref"):
        return parallel_set_blockers(repo_root, request)
    if request.get("pre_dispatch_review_required") is not True:
        return []
    dispatch_ref = str(request.get("dispatch_ref") or "<unknown>")
    artifact_ref = request.get("pre_dispatch_review_artifact_path") or default_pre_dispatch_review_artifact_path(dispatch_ref)
    return _pre_dispatch_review_blockers_for_path(
        repo_root,
        artifact_ref,
        expected_dispatch_ref=dispatch_ref,
    )


def _request_scope_reservations(request: Dict[str, Any]) -> List[str]:
    values = request.get("scope_reservations")
    if not isinstance(values, list):
        return []
    return [normalize_repo_path(item) for item in unique_strings(values)]


def _scopes_overlap(left: List[str], right: List[str]) -> bool:
    for candidate in left:
        for active in right:
            if not candidate or not active:
                continue
            if candidate == active:
                return True
            if candidate.startswith(active + "/") or active.startswith(candidate + "/"):
                return True
    return False


def _requested_overlap_isolation(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    payload = request.get("overlap_isolation")
    return payload if isinstance(payload, dict) else None


def _overlap_isolation_allows_pair(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    if left.get("execution_mode") not in SUBAGENT_ONLY_MODES:
        return False
    if right.get("execution_mode") not in SUBAGENT_ONLY_MODES:
        return False
    if left.get("task_track") != "patch" or right.get("task_track") != "patch":
        return False
    left_overlap = _requested_overlap_isolation(left)
    right_overlap = _requested_overlap_isolation(right)
    if not left_overlap or not right_overlap:
        return False
    if left_overlap.get("mode") != OVERLAP_ISOLATION_MODE or right_overlap.get("mode") != OVERLAP_ISOLATION_MODE:
        return False
    if left_overlap.get("overlap_group") != right_overlap.get("overlap_group"):
        return False
    if left_overlap.get("integration_policy") != right_overlap.get("integration_policy"):
        return False
    return True


def resource_conflict(left: Dict[str, Any], right: Dict[str, Any]) -> Optional[str]:
    left_gpu = (left.get("resource_hints") or {}).get("gpu") if isinstance(left.get("resource_hints"), dict) else None
    right_gpu = (right.get("resource_hints") or {}).get("gpu") if isinstance(right.get("resource_hints"), dict) else None
    if left_gpu == "exclusive" and right_gpu in {"shared", "exclusive"}:
        return "gpu_exclusive"
    if right_gpu == "exclusive" and left_gpu in {"shared", "exclusive"}:
        return "gpu_exclusive"
    return None


def validate_parallel_set_payload(payload: Dict[str, Any], failures: List[str]) -> None:
    for field in ["parallel_set_ref", "work_ref", "lane", "intent", "review_artifact_path", "created_at"]:
        _require_string(payload.get(field), failures, f"parallel_dispatch_set.json {field}")
    _require_repo_local_path(payload.get("parallel_set_ref"), failures, "parallel_dispatch_set.json parallel_set_ref")
    validate_pre_dispatch_review_artifact_path(
        payload.get("review_artifact_path"),
        failures,
        field="parallel_dispatch_set.json review_artifact_path",
    )
    dispatch_refs = _require_string_list(
        payload.get("dispatch_refs"),
        failures,
        "parallel_dispatch_set.json dispatch_refs",
    )
    if dispatch_refs is not None and len(dispatch_refs) < 2:
        failures.append("parallel_dispatch_set.json dispatch_refs must include at least two dispatches")
    max_active = payload.get("max_active")
    if not isinstance(max_active, int) or max_active < 1 or max_active > MAX_PARALLEL_SET_ACTIVE:
        failures.append(f"parallel_dispatch_set.json max_active must be an integer between 1 and {MAX_PARALLEL_SET_ACTIVE}")


def parallel_set_blockers(
    repo_root: Path,
    request: Dict[str, Any],
    *,
    dependency_checker: Optional[DependencyChecker] = None,
) -> List[str]:
    parallel_set_ref = request.get("parallel_set_ref")
    if not parallel_set_ref:
        return []

    failures: List[str] = []
    normalized_ref = _require_repo_local_path(parallel_set_ref, failures, "parallel_set_ref")
    if failures or normalized_ref is None:
        return [f"parallel_set_invalid:{parallel_set_ref}:{failure}" for failure in failures]

    set_path = parallel_set_artifact_path(repo_root, normalized_ref)
    if not set_path.exists():
        return [f"parallel_set_missing:{normalized_ref}"]
    try:
        payload = load_json(set_path)
    except Exception as exc:
        return [f"parallel_set_invalid:{normalized_ref}:{exc}"]

    failures = []
    validate_parallel_set_payload(payload, failures)
    if payload.get("parallel_set_ref") != normalized_ref:
        failures.append("parallel_dispatch_set.json parallel_set_ref mismatch")
    if failures:
        return [f"parallel_set_invalid:{normalized_ref}:{failure}" for failure in failures]

    blockers: List[str] = []
    dispatch_refs = unique_strings(payload["dispatch_refs"])
    if request.get("dispatch_ref") not in dispatch_refs:
        blockers.append(f"parallel_set_member_missing:{request.get('dispatch_ref')}")

    member_requests: Dict[str, Dict[str, Any]] = {}
    for dispatch_ref in dispatch_refs:
        request_path = dispatch_dir_for_ref(repo_root, dispatch_ref) / "request.json"
        if not request_path.exists():
            blockers.append(f"parallel_set_member_request_missing:{dispatch_ref}")
            continue
        try:
            member = load_json(request_path)
        except Exception as exc:
            blockers.append(f"parallel_set_member_invalid:{dispatch_ref}:{exc}")
            continue
        member_requests[dispatch_ref] = member
        if member.get("parallel_set_ref") != normalized_ref:
            blockers.append(f"parallel_set_member_invalid:{dispatch_ref}:parallel_set_ref_mismatch")
        if member.get("lane") != payload.get("lane"):
            blockers.append(f"parallel_set_member_invalid:{dispatch_ref}:lane_mismatch")
        if member.get("work_ref") != payload.get("work_ref"):
            blockers.append(f"parallel_set_member_invalid:{dispatch_ref}:work_ref_mismatch")
        if member.get("pre_dispatch_review_required") is not True:
            blockers.append(f"parallel_set_member_invalid:{dispatch_ref}:pre_dispatch_review_required_missing")
        else:
            artifact_ref = (
                member.get("pre_dispatch_review_artifact_path")
                or default_pre_dispatch_review_artifact_path(dispatch_ref)
            )
            blockers.extend(
                _pre_dispatch_review_blockers_for_path(
                    repo_root,
                    artifact_ref,
                    expected_dispatch_ref=dispatch_ref,
                )
            )
        if not _request_scope_reservations(member):
            blockers.append(f"parallel_set_member_invalid:{dispatch_ref}:scope_reservations_missing")
        for dependency_ref in unique_strings(member.get("depends_on_dispatches", [])):
            if dependency_checker is not None and not dependency_checker(repo_root, dependency_ref):
                blockers.append(f"parallel_set_unsatisfied_dependency:{dispatch_ref}:{dependency_ref}")

    refs = list(member_requests.keys())
    for index, left_ref in enumerate(refs):
        for right_ref in refs[index + 1 :]:
            left = member_requests[left_ref]
            right = member_requests[right_ref]
            if _scopes_overlap(_request_scope_reservations(left), _request_scope_reservations(right)):
                if not _overlap_isolation_allows_pair(left, right):
                    blockers.append(f"parallel_set_scope_conflict:{left_ref}:{right_ref}")
            conflict = resource_conflict(left, right)
            if conflict:
                blockers.append(f"parallel_set_resource_conflict:{left_ref}:{right_ref}:{conflict}")

    blockers.extend(
        _pre_dispatch_review_blockers_for_path(
            repo_root,
            payload["review_artifact_path"],
            expected_dispatch_ref=normalized_ref,
            covered_dispatch_refs=dispatch_refs,
        )
    )

    return unique_strings(blockers)
