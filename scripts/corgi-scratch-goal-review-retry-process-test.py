#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from unittest import mock


def assert_condition(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def governor_retry_reply(session_module, body: str) -> mock._patch:
    def reply(_session: dict, prompt: str, *, repo_root: str | Path | None = None, runtime_kind: str = "dialogue"):
        del repo_root
        if runtime_kind != "plan" or "Retry handoff:" not in prompt:
            raise AssertionError(f"unexpected Governor dialogue in goal retry benchmark: {runtime_kind}")
        for marker in [
            "failed_dispatch_ref=",
            "attempt_number=",
            "failure_summary=",
            "recommended_next_bounded_action=",
        ]:
            if marker not in prompt:
                raise AssertionError(f"retry Governor prompt missing {marker}")
        return (body, ["process-test Governor"], None)

    return mock.patch.object(
        session_module,
        "_continue_governor_dialogue",
        side_effect=reply,
    )


def dispatch_requests(agent_root: Path) -> list[dict]:
    return [
        load_json(path)
        for path in sorted((agent_root / "dispatches").glob("**/request.json"))
    ]


def dispatch_dir_for(agent_root: Path, dispatch_ref: str) -> Path:
    return agent_root / "dispatches" / Path(dispatch_ref)


def output_signature_for(agent_root: Path, request: dict, rel_path: str) -> dict:
    run_ref = request["executor_run"]["run_ref"]
    signature_path = agent_root / "runs" / Path(run_ref) / "output_signatures.json"
    payload = load_json(signature_path)
    return payload["required_outputs"][rel_path]


def goal_progress(agent_root: Path, goal_ref: str) -> dict:
    return load_json(agent_root / "goals" / goal_ref / "goal_progress.json")


def work_index(agent_root: Path, work_ref: str) -> dict:
    return load_json(agent_root / "work" / Path(work_ref) / "work.json")


def run(source_root: Path, scratch_root: Path, agent_root: Path) -> dict[str, object]:
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    from orchestration.harness import runtime_support, session  # noqa: WPS433

    os.environ["ORCHESTRATION_SOURCE_ROOT"] = str(source_root)
    os.environ["ORCHESTRATION_REPO_ROOT"] = str(scratch_root)
    os.environ["ORCHESTRATION_AGENT_ROOT"] = str(agent_root)
    os.environ["ORCHESTRATION_TARGET_WORKSPACE_MODE"] = "scratch"
    os.environ["ORCHESTRATION_TEST_PROMPT_PRESET"] = "pet-life-diary-goal-review-retry"
    os.environ["ORCHESTRATION_APPROVED_PYTHON"] = str(Path(sys.executable).resolve())
    os.environ["CORGI_GOAL_PLAN_SOURCE"] = "template"

    prompt = (
        "Build a polished Pet Life Diary web app demo from scratch, then improve it "
        "through multiple development steps until it is ready to show as a small portfolio demo."
    )
    revised_plan = (
        "Revised plan: keep the same species-filter goal step and complete the missing "
        "visibleEntries filtering pass in src/app.js before allowing the parent goal to continue."
    )

    with mock.patch.object(runtime_support, "APPROVED_PYTHON", Path(sys.executable).resolve()):
        with governor_retry_reply(session, revised_plan) as governor_mock:
            model = session.dispatch_session_action(
                "start_goal",
                text=prompt,
                request_id="process-test:scratch-goal-review-retry:start",
                repo_root=scratch_root,
                auto_consume_executor=True,
                governor_runtime="exec",
            )
        assert_condition(governor_mock.call_count == 1, "retry Governor should be called exactly once")

    snapshot = model["snapshot"]
    assert_condition(snapshot["goalStatus"] == "completed", "goal did not complete")
    assert_condition(
        snapshot["currentStage"] == "governor_decision_recorded",
        f"goal stopped at {snapshot['currentStage']}",
    )
    goal_ref = snapshot["currentGoalRef"]
    assert_condition(isinstance(goal_ref, str) and goal_ref, "goal ref missing")

    progress = goal_progress(agent_root, goal_ref)
    assert_condition(progress["status"] == "completed", "goal progress did not complete")
    assert_condition(
        len(progress.get("completed_steps", [])) >= 3,
        "goal did not record at least three completed steps",
    )
    linked_work_refs = list(dict.fromkeys(progress.get("linked_work_refs", [])))
    assert_condition(len(linked_work_refs) >= 3, "goal did not link at least three work refs")

    retry_work = None
    for work_ref in linked_work_refs:
        index = work_index(agent_root, work_ref)
        if index.get("goal_ref") == goal_ref and len(index.get("attempts", [])) == 2:
            retry_work = index
            break
    assert_condition(retry_work is not None, "goal did not contain a same-work retry")
    assert_condition(retry_work["goal_step_ref"] == "step-02", "retry did not stay on goal step 2")
    assert_condition(retry_work["current_plan_version"] == 2, "retry did not revise to plan v2")
    assert_condition(retry_work["revision_count"] == 1, "retry revision count was not 1")
    assert_condition(
        retry_work["reviews"][0]["verdict"] == "request_changes",
        "attempt 1 review did not request changes",
    )
    assert_condition(retry_work["reviews"][1]["verdict"] == "pass", "attempt 2 review did not pass")
    assert_condition(retry_work["decisions"][0]["decision"] == "reject", "attempt 1 was not rejected")
    assert_condition(retry_work["decisions"][1]["decision"] == "accept", "attempt 2 was not accepted")
    latest_handoff = retry_work.get("latest_retry_handoff")
    assert_condition(isinstance(latest_handoff, dict), "retry handoff missing")
    assert_condition(
        latest_handoff.get("work_ref") == retry_work["work_ref"],
        "retry handoff work_ref mismatch",
    )
    assert_condition(
        latest_handoff.get("failed_dispatch_ref") == retry_work["attempts"][0]["dispatch_ref"],
        "retry handoff did not point at attempt 1",
    )

    all_requests = dispatch_requests(agent_root)
    assert_condition(len(all_requests) >= 4, "goal retry benchmark expected at least four dispatches")
    first_retry = next(
        request
        for request in all_requests
        if request["dispatch_ref"] == retry_work["attempts"][0]["dispatch_ref"]
    )
    second_retry = next(
        request
        for request in all_requests
        if request["dispatch_ref"] == retry_work["attempts"][1]["dispatch_ref"]
    )
    assert_condition(first_retry["work_ref"] == retry_work["work_ref"], "attempt 1 work_ref mismatch")
    assert_condition(second_retry["work_ref"] == retry_work["work_ref"], "attempt 2 work_ref mismatch")
    assert_condition(second_retry["plan_version"] == 2, "attempt 2 did not target revised plan")
    assert_condition(
        second_retry["revision_of_dispatch_ref"] == first_retry["dispatch_ref"],
        "attempt 2 did not link to attempt 1",
    )
    assert_condition(
        first_retry["required_outputs"] == ["index.html", "src/app.js"],
        "attempt 1 should require index.html and src/app.js",
    )
    assert_condition(
        second_retry["required_outputs"] == ["src/app.js"],
        "attempt 2 should require only src/app.js",
    )
    assert_condition(
        output_signature_for(agent_root, first_retry, "index.html")["classification"] == "mutated",
        "attempt 1 index.html authorship was not mutated",
    )
    assert_condition(
        output_signature_for(agent_root, first_retry, "src/app.js")["classification"] == "mutated",
        "attempt 1 src/app.js authorship was not mutated",
    )
    assert_condition(
        output_signature_for(agent_root, second_retry, "src/app.js")["classification"] == "mutated",
        "attempt 2 src/app.js authorship was not mutated",
    )

    app_source = (scratch_root / "src" / "app.js").read_text(encoding="utf-8")
    index_source = (scratch_root / "index.html").read_text(encoding="utf-8")
    readme = (scratch_root / "README.md").read_text(encoding="utf-8")
    assert_condition('id="species-filter"' in index_source, "final index.html lacks species filter")
    assert_condition("function visibleEntries()" in app_source, "final app lacks visibleEntries helper")
    assert_condition(
        ".filter((entry) => entry.species === selectedSpecies)" in app_source,
        "final app does not filter entries by species",
    )
    assert_condition("Demo highlights" in readme, "final README was not polished")

    for dispatch_ref in [first_retry["dispatch_ref"], second_retry["dispatch_ref"]]:
        dispatch_dir = dispatch_dir_for(agent_root, dispatch_ref)
        assert_condition((dispatch_dir / "result.json").exists(), f"{dispatch_ref}: result missing")
        assert_condition((dispatch_dir / "governor_decision.json").exists(), f"{dispatch_ref}: decision missing")
        assert_condition(
            (agent_root / "reviews" / Path(dispatch_ref) / "review.json").exists(),
            f"{dispatch_ref}: review missing",
        )

    return {
        "id": "module:scratch-goal-review-retry",
        "stage": "governor_decision_recorded",
        "permissionScope": snapshot["permissionScope"],
        "goalRef": goal_ref,
        "retryWorkRef": retry_work["work_ref"],
        "retryDispatchRef": second_retry["dispatch_ref"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scratch goal review-retry benchmark.")
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--scratch-root", required=True)
    parser.add_argument("--agent-root", required=True)
    args = parser.parse_args(argv)

    result = run(
        Path(args.source_root).resolve(),
        Path(args.scratch_root).resolve(),
        Path(args.agent_root).resolve(),
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
