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


def semantic_submit(route_type: str = "governed_work_intent") -> dict[str, str]:
    return {
        "turn_type": route_type,
        "semantic_route_type": route_type,
        "semantic_confidence": "high",
    }


def governor_reply(session_module, body: str) -> mock._patch:
    return mock.patch.object(
        session_module,
        "_continue_governor_dialogue",
        return_value=(body, ["process-test Governor"], None),
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


def review_with_first_change(repo_root: Path, request: dict, result: dict) -> dict:
    dispatch_ref = request["dispatch_ref"]
    if request.get("attempt_number") != 1:
        validation_hits = [
            item
            for item in result.get("auto_validated", [])
            if isinstance(item, str) and "validate_pet_diary_filter.py" in item
        ]
        return {
            "dispatch_ref": dispatch_ref,
            "reviewer_role": "agentR-helper",
            "verdict": "pass",
            "validator_assessment": validation_hits or ["second attempt completed"],
            "scope_assessment": ["same work retry stayed bounded"],
            "findings": [],
            "residual_risks": [],
            "recommendation": "accept",
        }

    app_source = (repo_root / "src" / "app.js").read_text(encoding="utf-8")
    index_source = (repo_root / "index.html").read_text(encoding="utf-8")
    assert_condition("species-filter" in index_source, "attempt 1 did not add the filter control")
    assert_condition("speciesFilter" in app_source, "attempt 1 did not touch filter wiring")
    assert_condition(
        "function visibleEntries()" not in app_source,
        "attempt 1 unexpectedly completed the filter behavior",
    )
    return {
        "dispatch_ref": dispatch_ref,
        "reviewer_role": "agentR-helper",
        "verdict": "request_changes",
        "validator_assessment": ["filter control exists but renderEntries still ignores the selected species"],
        "scope_assessment": ["scope is bounded to the Pet Life Diary feature files"],
        "findings": ["The filter UI is present, but rendered entries are not filtered by selected species."],
        "residual_risks": [],
        "recommendation": "redispatch_or_reject",
    }


def run(source_root: Path, scratch_root: Path, agent_root: Path) -> dict[str, object]:
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    from orchestration.harness import dispatch, runtime_support, session  # noqa: WPS433

    os.environ["ORCHESTRATION_SOURCE_ROOT"] = str(source_root)
    os.environ["ORCHESTRATION_REPO_ROOT"] = str(scratch_root)
    os.environ["ORCHESTRATION_AGENT_ROOT"] = str(agent_root)
    os.environ["ORCHESTRATION_TARGET_WORKSPACE_MODE"] = "scratch"
    os.environ["ORCHESTRATION_TEST_PROMPT_PRESET"] = "pet-life-diary-filter-review-retry"
    os.environ["ORCHESTRATION_APPROVED_PYTHON"] = str(Path(sys.executable).resolve())

    prompt = (
        "Add a simple species filter to the existing pet diary app so users can show all entries "
        "or only Corgi/Cat entries. Keep the UI simple and preserve the existing app structure."
    )

    with mock.patch.object(runtime_support, "APPROVED_PYTHON", Path(sys.executable).resolve()):
        model = session.dispatch_session_action(
            "submit_prompt",
            text=prompt,
            request_id="process-test:scratch-review-retry:submit",
            repo_root=scratch_root,
            **semantic_submit(),
        )
        if model.get("activeClarification"):
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep the existing static app and add only the species filter behavior.",
                request_id="process-test:scratch-review-retry:clarify",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=scratch_root,
            )
        with governor_reply(session, "Initial species-filter plan."):
            model = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="plan",
                request_id="process-test:scratch-review-retry:plan",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                repo_root=scratch_root,
            )
        initial_plan = model["planReadyRequest"]
        assert_condition(initial_plan, "initial plan-ready state missing")

        with (
            mock.patch.object(dispatch, "build_helper_review", side_effect=review_with_first_change),
            governor_reply(session, "Revised plan: complete the filter helper and render only visible entries."),
        ):
            model = session.dispatch_session_action(
                "execute_plan",
                request_id="process-test:scratch-review-retry:execute",
                context_ref=initial_plan["contextRef"],
                auto_consume_executor=True,
                repo_root=scratch_root,
            )

    assert_condition(
        model["snapshot"]["currentStage"] == "governor_decision_recorded",
        "state did not finish after automatic retry",
    )
    assert_condition(model["snapshot"]["latestReviewVerdict"] == "pass", "latest review did not pass")
    assert_condition(model["snapshot"]["latestGovernorDecision"] == "accept", "Governor did not accept")

    app_source = (scratch_root / "src" / "app.js").read_text(encoding="utf-8")
    index_source = (scratch_root / "index.html").read_text(encoding="utf-8")
    assert_condition('id="species-filter"' in index_source, "final index.html lacks species filter")
    assert_condition("function visibleEntries()" in app_source, "final app lacks visibleEntries helper")
    assert_condition(
        ".filter((entry) => entry.species === selectedSpecies)" in app_source,
        "final app does not filter entries by species",
    )

    work_index = load_json(agent_root / "work" / initial_plan["workRef"] / "work.json")
    assert_condition(work_index["status"] == "completed", "work index did not complete")
    assert_condition(work_index["current_plan_version"] == 2, "work index did not advance to plan v2")
    assert_condition(len(work_index["plans"]) == 2, "work index did not record two plans")
    assert_condition(len(work_index["attempts"]) == 2, "work index did not record two attempts")
    assert_condition(len(work_index["reviews"]) == 2, "work index did not record two reviews")
    assert_condition(len(work_index["decisions"]) == 2, "work index did not record two decisions")
    assert_condition(work_index["reviews"][0]["verdict"] == "request_changes", "attempt 1 review did not request changes")
    assert_condition(work_index["reviews"][1]["verdict"] == "pass", "attempt 2 review did not pass")
    assert_condition(work_index["decisions"][0]["decision"] == "reject", "attempt 1 decision was not reject")
    assert_condition(work_index["decisions"][1]["decision"] == "accept", "attempt 2 decision was not accept")

    plan_v1 = scratch_root / initial_plan["planRef"]
    revised_plan_entry = next(plan for plan in work_index["plans"] if plan["plan_version"] == 2)
    plan_v2 = scratch_root / revised_plan_entry["plan_ref"]
    assert_condition(plan_v1.exists() and plan_v2.exists(), "plan artifacts missing")
    assert_condition(plan_v1.parent == plan_v2.parent, "plan artifacts are not colocated")
    assert_condition(
        revised_plan_entry["revision_reason"] == "review_requested_changes",
        "revised plan reason did not reference reviewer feedback",
    )

    all_dispatches = dispatch_requests(agent_root)
    assert_condition(len(all_dispatches) == 2, "automatic retry did not create two dispatches")
    first_dispatch = next(request for request in all_dispatches if request["attempt_number"] == 1)
    second_dispatch = next(request for request in all_dispatches if request["attempt_number"] == 2)
    assert_condition(first_dispatch["work_ref"] == initial_plan["workRef"], "attempt 1 work_ref mismatch")
    assert_condition(second_dispatch["work_ref"] == initial_plan["workRef"], "attempt 2 work_ref mismatch")
    assert_condition(second_dispatch["plan_version"] == 2, "attempt 2 did not target plan v2")
    assert_condition(
        second_dispatch["revision_of_dispatch_ref"] == first_dispatch["dispatch_ref"],
        "attempt 2 did not link to attempt 1",
    )
    assert_condition("index.html" in first_dispatch["required_outputs"], "attempt 1 did not require index.html")
    assert_condition("src/app.js" in first_dispatch["required_outputs"], "attempt 1 did not require app.js")
    assert_condition(second_dispatch["required_outputs"] == ["src/app.js"], "attempt 2 should only require app.js mutation")
    assert_condition(
        output_signature_for(agent_root, first_dispatch, "index.html")["classification"] == "mutated",
        "attempt 1 index.html authorship was not mutated",
    )
    assert_condition(
        output_signature_for(agent_root, first_dispatch, "src/app.js")["classification"] == "mutated",
        "attempt 1 app.js authorship was not mutated",
    )
    assert_condition(
        output_signature_for(agent_root, second_dispatch, "src/app.js")["classification"] == "mutated",
        "attempt 2 app.js authorship was not mutated",
    )
    assert_condition(
        (scratch_root / ".agent" / "validations" / Path(second_dispatch["dispatch_ref"]) / "pet_diary_species_filter.json").exists(),
        "attempt 2 validation report missing",
    )

    return {
        "id": "module:scratch-review-retry-existing-app",
        "stage": "governor_decision_recorded",
        "permissionScope": "execute",
        "workRef": initial_plan["workRef"],
        "dispatchRef": second_dispatch["dispatch_ref"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the scratch project review-retry process benchmark.")
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
