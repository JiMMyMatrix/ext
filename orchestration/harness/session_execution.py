from __future__ import annotations

import contextlib
import io
import os
import shlex
from pathlib import Path
from typing import Any, Callable

from orchestration.harness import dispatch as dispatch_harness
from orchestration.harness.intake import accepted_intake_path
from orchestration.harness.paths import (
    default_lane,
    git_branch_name,
    load_json,
    repo_relative,
    resolve_paths,
    script_ref,
    trim_text,
)

FeedItemFactory = Callable[..., dict[str, Any]]
ArtifactFactory = Callable[..., dict[str, Any]]
AppendError = Callable[..., None]
NextId = Callable[[str], str]


def accepted_intake_ref(session: dict[str, Any], repo_root: str | Path | None = None) -> str | None:
    intake_ref = session["meta"].get("activeIntakeRef")
    if not isinstance(intake_ref, str) or not intake_ref:
        return None
    path = accepted_intake_path(intake_ref, repo_root=repo_root)
    if not path.exists():
        return None
    return repo_relative(path, repo_root)


def plan_execution_objective(model: dict[str, Any]) -> str:
    plan_ready = model.get("planReadyRequest")
    summary: Any = None
    if isinstance(plan_ready, dict):
        summary = plan_ready.get("acceptedIntakeSummary")
    if not isinstance(summary, dict):
        summary = model.get("acceptedIntakeSummary")
    if isinstance(summary, dict):
        body = trim_text(summary.get("body"))
        if body:
            return body
    task = trim_text(model["snapshot"].get("task"))
    if task:
        return task
    return "Execute the accepted Corgi plan."


def executor_run_ref(dispatch_ref: str) -> str:
    return f"{dispatch_ref}/result/attempt-1"


def plan_execution_summary(model: dict[str, Any], dispatch_ref: str) -> str:
    objective = plan_execution_objective(model)
    return f"Executor generated a bounded readout for dispatch {dispatch_ref}: {objective}."


def command_arg(value: str) -> str:
    return shlex.quote(str(value))


def emit_plan_execution_dispatch(
    session: dict[str, Any],
    now: str,
    *,
    repo_root: str | Path | None = None,
    request_id: str | None = None,
    next_id: NextId,
    append_error: AppendError,
) -> dict[str, Any] | None:
    model = session["model"]
    paths = resolve_paths(repo_root)
    branch = model["snapshot"].get("branch") or git_branch_name(repo_root)
    lane = model["snapshot"].get("lane") or default_lane(branch)
    dispatch_ref = f"{lane}/{next_id('dispatch')}"
    dispatch_dir = paths.agent_root / "dispatches" / Path(dispatch_ref)
    run_ref = executor_run_ref(dispatch_ref)
    run_dir = paths.agent_root / "runs" / Path(run_ref)
    readout_ref = repo_relative(run_dir / "executor_readout.md", repo_root)
    review_ref = repo_relative(
        paths.agent_root / "reviews" / Path(dispatch_ref) / "review.json",
        repo_root,
    )
    objective = plan_execution_objective(model)
    accepted_ref = accepted_intake_ref(session, repo_root)
    if not accepted_ref:
        append_error(
            model,
            "Accepted intake artifact missing",
            "The accepted intake artifact is required before Executor can start.",
            now,
            in_response_to_request_id=request_id,
            presentation_key="error.plan_not_ready",
            presentation_args={"reason": "missing_accepted_intake_artifact"},
        )
        return None
    plan_ready = model.get("planReadyRequest") if isinstance(model.get("planReadyRequest"), dict) else {}
    work_ref = trim_text(plan_ready.get("workRef")) if plan_ready else ""
    plan_ref = trim_text(plan_ready.get("planRef")) if plan_ready else ""
    plan_version = plan_ready.get("planVersion") if plan_ready else None
    attempt_number = int(model.get("currentAttemptNumber") or 0) + 1
    inputs = [
        ref
        for ref in [
            accepted_ref,
            plan_ref or None,
            f"plan_context_ref:{plan_ready.get('planContextRef')}" if plan_ready else None,
            f"plan_version:{plan_ready.get('planVersion')}" if plan_ready else None,
        ]
        if isinstance(ref, str) and ref.strip()
    ]
    args = [
        "--dispatch-ref",
        dispatch_ref,
        "--attempt-number",
        str(attempt_number),
        "--objective",
        objective,
        "--lane",
        lane,
        "--execution-mode",
        "command_chain",
        "--executor-run-ref",
        run_ref,
        "--run-objective",
        objective,
        "--run-scope",
        objective,
        "--run-produce",
        readout_ref,
        "--required-output",
        readout_ref,
        "--command",
        " ".join(
            [
                command_arg(os.environ.get("ORCHESTRATION_APPROVED_PYTHON") or "python3"),
                command_arg(script_ref("executor_write_readout.py", paths.repo_root)),
                "--repo-root",
                command_arg(str(paths.repo_root)),
                "--dispatch-ref",
                command_arg(dispatch_ref),
                "--objective",
                command_arg(objective),
                "--output",
                command_arg(readout_ref),
                *(["--accepted-intake", command_arg(accepted_ref)] if accepted_ref else []),
            ]
        ),
        "--execution-summary",
        plan_execution_summary(model, dispatch_ref),
        "--execution-claim",
        "Executor generated a bounded readout artifact for the accepted plan.",
        "--execution-claim",
        "This helper-backed Executor path produced analysis artifacts but did not mutate product code.",
        "--execution-evidence",
        readout_ref,
        "--execution-note",
        "artifact_only_executor_readout",
        "--execution-next-action",
        "Governor should review the Executor result and decide the next bounded step.",
        "--acceptance-criterion",
        "Executor work stays within the accepted intake and latest validated plan context.",
        "--stop-condition",
        "Stop on stale context, authority boundary, safety boundary, or missing required input.",
        "--review-required",
        "--review-artifact-path",
        review_ref,
        "--root",
        str(paths.repo_root),
    ]
    if work_ref:
        args.extend(["--work-ref", work_ref])
    if plan_ref:
        args.extend(["--plan-ref", plan_ref])
    if isinstance(plan_version, int):
        args.extend(["--plan-version", str(plan_version)])
    revision_of_dispatch_ref = trim_text(model.get("revisionOfDispatchRef"))
    if revision_of_dispatch_ref:
        args.extend(["--revision-of-dispatch-ref", revision_of_dispatch_ref])
    for input_ref in inputs:
        args.extend(["--input", input_ref])
        args.extend(["--run-read", input_ref])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            dispatch_harness.emit_main(args)
    except (OSError, SystemExit, ValueError) as exc:
        append_error(
            model,
            "Dispatch could not start",
            f"Corgi could not create dispatch truth for this plan: {exc}",
            now,
            in_response_to_request_id=request_id,
        )
        return None

    return {
        "dispatch_ref": dispatch_ref,
        "request_ref": repo_relative(dispatch_dir / "request.json", repo_root),
        "state_ref": repo_relative(dispatch_dir / "state.json", repo_root),
        "review_ref": review_ref,
        "dispatch_dir": str(dispatch_dir),
        "work_ref": work_ref or None,
        "plan_ref": plan_ref or None,
        "plan_version": plan_version,
        "attempt_number": attempt_number,
    }


def dispatch_artifacts(
    dispatch_refs: dict[str, Any],
    *,
    artifact: ArtifactFactory,
    status: str = "queued",
) -> list[dict[str, Any]]:
    return [
        artifact(
            dispatch_refs["request_ref"],
            summary="Dispatch truth for the accepted plan.",
            authoritative=True,
            status=status,
        ),
        artifact(
            dispatch_refs["state_ref"],
            summary="Dispatch lifecycle state.",
            authoritative=True,
            status=status,
        ),
    ]


def executor_result_artifacts(
    dispatch_refs: dict[str, Any],
    state: dict[str, Any],
    *,
    artifact: ArtifactFactory,
    repo_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    status = trim_text(state.get("status")) or "completed"
    run_ref = state.get("run_ref")
    if isinstance(run_ref, str) and run_ref.strip():
        run_dir = resolve_paths(repo_root).agent_root / "runs" / Path(run_ref)
        report_payload = load_json(run_dir / "report.json") if (run_dir / "report.json").exists() else {}
        raw_outputs = report_payload.get("outputs", []) if isinstance(report_payload, dict) else []
        outputs = [output for output in raw_outputs if isinstance(output, str) and output.strip()]
        primary_output_ref = executor_primary_output_ref(report_payload)
        ordered_outputs = [
            output
            for output in [primary_output_ref, *outputs]
            if isinstance(output, str)
            and output.strip()
            and "/command_logs/" not in output
        ]
        for output_ref in dict.fromkeys(ordered_outputs):
            if isinstance(output_ref, str) and output_ref.strip():
                artifacts.append(
                    artifact(
                        output_ref,
                        summary="Executor produced output artifact.",
                        authoritative=True,
                        status=status,
                    )
                )
        for name, summary in [
            ("report.json", "Executor run report."),
            ("status.json", "Executor run status."),
        ]:
            path = run_dir / name
            if path.exists():
                artifacts.append(
                    artifact(
                        repo_relative(path, repo_root),
                        summary=summary,
                        authoritative=True,
                        status=status,
                    )
                )
    result_ref = state.get("result_ref")
    if isinstance(result_ref, str) and result_ref.strip():
        artifacts.append(
            artifact(
                result_ref,
                summary="Executor result for the accepted dispatch.",
                authoritative=True,
                status=status,
            )
        )
    return artifacts + dispatch_artifacts(dispatch_refs, artifact=artifact, status=status)


def executor_report_payload(
    state: dict[str, Any],
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    run_ref = state.get("run_ref") if isinstance(state, dict) else None
    if not isinstance(run_ref, str) or not run_ref.strip():
        return {}
    report_path = resolve_paths(repo_root).agent_root / "runs" / Path(run_ref) / "report.json"
    return load_json(report_path) if report_path.exists() else {}


def executor_primary_output_ref(report: dict[str, Any]) -> str | None:
    outputs = report.get("outputs") if isinstance(report, dict) else None
    if not isinstance(outputs, list):
        return None
    for suffix in (".md", ".json"):
        for output in outputs:
            if isinstance(output, str) and output.strip() and output.endswith(suffix):
                return output
    for output in outputs:
        if isinstance(output, str) and output.strip():
            return output
    return None


def executor_output_body(
    output_ref: str | None,
    *,
    repo_root: str | Path | None = None,
) -> str | None:
    if not isinstance(output_ref, str) or not output_ref.strip() or not output_ref.endswith(".md"):
        return None
    path = resolve_paths(repo_root).repo_root / output_ref
    if not path.exists():
        return None
    body = trim_text(path.read_text(encoding="utf-8"))
    if not body:
        return None
    max_chars = 12000
    if len(body) > max_chars:
        return body[:max_chars].rstrip() + "\n\n_Output truncated. View source for the full Executor readout._"
    return body


def executor_completion_body(report: dict[str, Any], output_body: str | None = None) -> str:
    summary = trim_text(report.get("summary") if isinstance(report, dict) else "")
    next_action = trim_text(report.get("next_action") if isinstance(report, dict) else "")
    claims = report.get("claims") if isinstance(report, dict) else None
    claim_lines = [
        f"- {trim_text(claim)}"
        for claim in claims[:3]
        if isinstance(claim, str) and trim_text(claim)
    ] if isinstance(claims, list) else []
    parts = [
        output_body or summary or "Executor completed the dispatch and wrote the bounded result artifact.",
    ]
    if claim_lines and not output_body:
        parts.append("What changed:\n" + "\n".join(claim_lines))
    if next_action:
        parts.append(f"Next: {next_action}")
    return "\n\n".join(parts)


def reviewer_completion_body(review: dict[str, Any]) -> str:
    verdict = trim_text(review.get("verdict")) or "inconclusive"
    recommendation = trim_text(review.get("recommendation")) or "No recommendation provided."
    findings = review.get("findings")
    residual_risks = review.get("residual_risks")
    validator_assessment = review.get("validator_assessment")

    parts = [
        "# Reviewer Readout",
        f"Verdict: {verdict}",
        f"Recommendation: {recommendation}",
    ]
    if isinstance(findings, list) and findings:
        parts.append(
            "Findings:\n"
            + "\n".join(
                f"- {trim_text(item)}"
                for item in findings
                if isinstance(item, str) and trim_text(item)
            )
        )
    if isinstance(residual_risks, list) and residual_risks:
        parts.append(
            "Residual risks:\n"
            + "\n".join(
                f"- {trim_text(item)}"
                for item in residual_risks
                if isinstance(item, str) and trim_text(item)
            )
        )
    if isinstance(validator_assessment, list) and validator_assessment:
        parts.append(
            "Validation checked:\n"
            + "\n".join(
                f"- {trim_text(item)}"
                for item in validator_assessment[:5]
                if isinstance(item, str) and trim_text(item)
            )
        )
    return "\n\n".join(part for part in parts if trim_text(part))


def governor_decision_body(decision: dict[str, Any]) -> str:
    decision_value = trim_text(decision.get("decision")) or "unknown"
    reason = trim_text(decision.get("reason")) or "No reason recorded."
    next_action = trim_text(decision.get("recommended_next_action"))
    parts = [
        "# Governor Decision",
        f"Decision: {decision_value}",
        f"Reason: {reason}",
    ]
    if next_action:
        parts.append(f"Next: {next_action}")
    return "\n\n".join(parts)


def consume_executor_dispatch(
    session: dict[str, Any],
    dispatch_refs: dict[str, Any],
    now: str,
    *,
    feed_item: FeedItemFactory,
    artifact: ArtifactFactory,
    append_error: AppendError,
    repo_root: str | Path | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    model = session["model"]
    paths = resolve_paths(repo_root)
    dispatch_dir = Path(dispatch_refs["dispatch_dir"])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = dispatch_harness.run(
                "consume-executor",
                [
                    "--dispatch-dir",
                    str(dispatch_dir),
                    "--root",
                    str(paths.repo_root),
                ],
            )
    except (OSError, SystemExit, ValueError) as exc:
        append_error(
            model,
            "Executor could not start",
            f"Corgi created dispatch truth, but Executor launch failed: {exc}",
            now,
            in_response_to_request_id=request_id,
            source_artifact_ref=dispatch_refs["request_ref"],
        )
        return {
            "ok": False,
            "actor": "executor",
            "stage": "executor_blocked",
            "artifacts": dispatch_artifacts(dispatch_refs, artifact=artifact, status="queued"),
        }

    state_path = dispatch_dir / "state.json"
    state = load_json(state_path) if state_path.exists() else {}
    status = trim_text(state.get("status")) or "queued"
    artifacts = executor_result_artifacts(dispatch_refs, state, artifact=artifact, repo_root=repo_root)
    if exit_code != 0 or status not in {"completed", "validated"}:
        source_ref = dispatch_refs["state_ref"]
        escalation_path = dispatch_dir / "escalation.json"
        if escalation_path.exists():
            source_ref = repo_relative(escalation_path, repo_root)
            artifacts = [
                artifact(
                    source_ref,
                    summary="Executor blocker artifact.",
                    authoritative=True,
                    status="blocked",
                )
            ] + artifacts
        append_error(
            model,
            "Executor blocked",
            "Executor could not complete this dispatch. View the source artifact for the blocker details.",
            now,
            in_response_to_request_id=request_id,
            source_artifact_ref=source_ref,
        )
        return {"ok": False, "actor": "executor", "stage": "executor_blocked", "artifacts": artifacts}

    report = executor_report_payload(state, repo_root=repo_root)
    primary_output_ref = executor_primary_output_ref(report)
    primary_output_body = executor_output_body(primary_output_ref, repo_root=repo_root)
    result_ref = state.get("result_ref") if isinstance(state, dict) else None
    model["feed"].append(
        feed_item(
            "system_status",
            "Executor completed",
            executor_completion_body(report, primary_output_body),
            authoritative=True,
            now=now,
            source_artifact_ref=primary_output_ref
            or (result_ref if isinstance(result_ref, str) else dispatch_refs["state_ref"]),
            turn_type="permission_action",
            in_response_to_request_id=request_id,
        )
    )
    return {"ok": True, "actor": "executor", "stage": "executor_completed", "artifacts": artifacts}


def consume_reviewer_dispatch(
    session: dict[str, Any],
    dispatch_refs: dict[str, Any],
    now: str,
    *,
    feed_item: FeedItemFactory,
    artifact: ArtifactFactory,
    append_error: AppendError,
    repo_root: str | Path | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    model = session["model"]
    dispatch_dir = Path(dispatch_refs["dispatch_dir"])
    review_ref = trim_text(dispatch_refs.get("review_ref"))
    if not review_ref:
        return {"ok": True, "artifacts": []}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = dispatch_harness.run(
                "consume-reviewer",
                [
                    "--dispatch-dir",
                    str(dispatch_dir),
                ],
            )
    except (OSError, SystemExit, ValueError) as exc:
        append_error(
            model,
            "Reviewer could not start",
            f"Corgi could not complete the advisory review for this dispatch: {exc}",
            now,
            in_response_to_request_id=request_id,
            source_artifact_ref=dispatch_refs.get("request_ref"),
        )
        return {"ok": False, "actor": "reviewer", "stage": "reviewer_blocked", "artifacts": []}

    review_path = resolve_paths(repo_root).repo_root / review_ref
    if exit_code != 0 or not review_path.exists():
        append_error(
            model,
            "Reviewer blocked",
            "Reviewer did not produce the expected advisory review artifact.",
            now,
            in_response_to_request_id=request_id,
            source_artifact_ref=dispatch_refs.get("request_ref"),
        )
        return {"ok": False, "actor": "reviewer", "stage": "reviewer_blocked", "artifacts": []}

    review_payload = load_json(review_path)
    review_artifact = artifact(
        review_ref,
        summary="Reviewer advisory artifact for the completed dispatch.",
        authoritative=True,
        status=trim_text(review_payload.get("verdict")) or "completed",
    )
    model["feed"].append(
        feed_item(
            "system_status",
            "Reviewer completed",
            reviewer_completion_body(review_payload),
            authoritative=True,
            now=now,
            source_artifact_ref=review_ref,
            turn_type="permission_action",
            in_response_to_request_id=request_id,
        )
    )
    return {"ok": True, "actor": "reviewer", "stage": "reviewer_completed", "artifacts": [review_artifact]}


def finalize_dispatch(
    session: dict[str, Any],
    dispatch_refs: dict[str, Any],
    now: str,
    *,
    feed_item: FeedItemFactory,
    artifact: ArtifactFactory,
    append_error: AppendError,
    repo_root: str | Path | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    model = session["model"]
    dispatch_dir = Path(dispatch_refs["dispatch_dir"])
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = dispatch_harness.run(
                "finalize",
                [
                    "--dispatch-dir",
                    str(dispatch_dir),
                ],
            )
    except (OSError, SystemExit, ValueError) as exc:
        append_error(
            model,
            "Governor finalization blocked",
            f"Corgi completed Executor and Reviewer steps, but Governor finalization could not complete: {exc}",
            now,
            in_response_to_request_id=request_id,
            source_artifact_ref=dispatch_refs.get("review_ref") or dispatch_refs.get("request_ref"),
        )
        return {"ok": False, "actor": "governor", "stage": "governor_finalization_blocked", "artifacts": []}

    decision_path = dispatch_dir / "governor_decision.json"
    if exit_code != 0 or not decision_path.exists():
        append_error(
            model,
            "Governor finalization blocked",
            "Governor finalization did not produce the expected decision artifact.",
            now,
            in_response_to_request_id=request_id,
            source_artifact_ref=dispatch_refs.get("review_ref") or dispatch_refs.get("request_ref"),
        )
        return {"ok": False, "actor": "governor", "stage": "governor_finalization_blocked", "artifacts": []}

    decision_ref = repo_relative(decision_path, repo_root)
    decision_payload = load_json(decision_path)
    decision_artifact = artifact(
        decision_ref,
        summary="Governor decision artifact for the completed dispatch.",
        authoritative=True,
        status=trim_text(decision_payload.get("decision")) or "recorded",
    )
    model["feed"].append(
        feed_item(
            "system_status",
            "Governor decision recorded",
            governor_decision_body(decision_payload),
            authoritative=True,
            now=now,
            source_layer="orchestration",
            source_actor="governor",
            source_artifact_ref=decision_ref,
            turn_type="permission_action",
            in_response_to_request_id=request_id,
        )
    )
    return {
        "ok": True,
        "actor": "governor",
        "stage": "governor_decision_recorded",
        "artifacts": [decision_artifact],
    }


def post_execution_actor_stage(*results: dict[str, Any]) -> tuple[str, str]:
    for result in reversed(results):
        actor = result.get("actor") if isinstance(result, dict) else None
        stage = result.get("stage") if isinstance(result, dict) else None
        if isinstance(actor, str) and actor and isinstance(stage, str) and stage:
            return (actor, stage)
    return ("executor", "executor_completed")
