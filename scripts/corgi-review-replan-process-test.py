#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestration.harness import dispatch, runtime_support, session  # noqa: E402
from orchestration.harness.paths import load_json  # noqa: E402


def assert_condition(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def semantic_submit(route_type: str = "governed_work_intent") -> dict[str, str]:
    return {
        "turn_type": route_type,
        "semantic_route_type": route_type,
        "semantic_confidence": "high",
    }


def governor_reply(body: str) -> mock._patch:
    return mock.patch.object(
        session,
        "_continue_governor_dialogue",
        return_value=(body, ["process-test Governor"], None),
    )


def request_changes_review(_repo_root: Path, request: dict, _result: dict) -> dict:
    return {
        "dispatch_ref": request["dispatch_ref"],
        "reviewer_role": "agentR-helper",
        "verdict": "request_changes",
        "validator_assessment": ["forced process-test reviewer feedback"],
        "scope_assessment": ["scope needs another pass"],
        "findings": ["The plan needs a narrower second attempt."],
        "residual_risks": [],
        "recommendation": "redispatch_or_reject",
    }


def dispatch_requests(agent_root: Path) -> list[dict]:
    return [
        load_json(path)
        for path in sorted((agent_root / "dispatches").glob("**/request.json"))
    ]


def run(repo_root: Path, agent_root: Path) -> dict[str, object]:
    os.environ["ORCHESTRATION_AGENT_ROOT"] = str(agent_root)
    os.environ["ORCHESTRATION_APPROVED_PYTHON"] = str(Path(sys.executable).resolve())

    with mock.patch.object(runtime_support, "APPROVED_PYTHON", Path(sys.executable).resolve()):
        model = session.dispatch_session_action(
            "submit_prompt",
            text="Analyze the repo.",
            request_id="process-test:review-replan:submit",
            repo_root=repo_root,
            **semantic_submit(),
        )
        model = session.dispatch_session_action(
            "answer_clarification",
            text="Focus on architecture, structure, and subsystem boundaries.",
            request_id="process-test:review-replan:clarify",
            context_ref=model["activeClarification"]["contextRef"],
            repo_root=repo_root,
        )
        with governor_reply("Initial process-test plan."):
            model = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="plan",
                request_id="process-test:review-replan:plan",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                repo_root=repo_root,
            )
        initial_plan = model["planReadyRequest"]
        assert_condition(initial_plan, "initial plan-ready state missing")

        with (
            mock.patch.object(dispatch, "build_helper_review", side_effect=request_changes_review),
            governor_reply("Revised plan from reviewer feedback."),
        ):
            model = session.dispatch_session_action(
                "execute_plan",
                request_id="process-test:review-replan:execute",
                context_ref=initial_plan["contextRef"],
                auto_consume_executor=True,
                repo_root=repo_root,
            )

        revised_plan = model["planReadyRequest"]
        assert_condition(model["snapshot"]["currentStage"] == "plan_ready", "state did not return to plan_ready")
        assert_condition(revised_plan, "revised plan-ready request missing")
        assert_condition(revised_plan["workRef"] == initial_plan["workRef"], "revised plan changed work folder")
        assert_condition(
            revised_plan["planVersion"] == initial_plan["planVersion"] + 1,
            "plan version did not increment",
        )
        assert_condition(
            revised_plan["revisionReason"] == "review_requested_changes",
            "revision reason was not reviewer feedback",
        )

        initial_plan_path = repo_root / initial_plan["planRef"]
        revised_plan_path = repo_root / revised_plan["planRef"]
        assert_condition(initial_plan_path.exists(), "initial plan artifact missing")
        assert_condition(revised_plan_path.exists(), "revised plan artifact missing")
        assert_condition(initial_plan_path.parent == revised_plan_path.parent, "plan artifacts are not colocated")

        work_index = load_json(agent_root / "work" / revised_plan["workRef"] / "work.json")
        assert_condition(work_index["current_plan_version"] == 2, "work index did not advance plan version")
        assert_condition(work_index["status"] == "plan_ready", "work index is not plan_ready")
        assert_condition(len(work_index["plans"]) == 2, "work index did not record two plans")
        assert_condition(len(work_index["attempts"]) == 1, "work index did not record first attempt")
        assert_condition(len(work_index["reviews"]) == 1, "work index did not record reviewer artifact")
        assert_condition(len(work_index["decisions"]) == 1, "work index did not record Governor decision")

        first_dispatches = dispatch_requests(agent_root)
        assert_condition(len(first_dispatches) == 1, "expected one dispatch before re-execute")
        first_dispatch = first_dispatches[0]
        assert_condition(first_dispatch["work_ref"] == revised_plan["workRef"], "first dispatch work_ref mismatch")
        assert_condition(first_dispatch["plan_version"] == 1, "first dispatch was not plan v1")

        model = session.dispatch_session_action(
            "execute_plan",
            request_id="process-test:review-replan:execute-again",
            context_ref=revised_plan["contextRef"],
            repo_root=repo_root,
        )

        second_dispatches = dispatch_requests(agent_root)
        assert_condition(len(second_dispatches) == 2, "second dispatch was not created")
        second_dispatch = next(
            (request for request in second_dispatches if request.get("attempt_number") == 2),
            None,
        )
        assert_condition(second_dispatch is not None, "second attempt request missing")
        assert_condition(second_dispatch["work_ref"] == initial_plan["workRef"], "second attempt changed work folder")
        assert_condition(second_dispatch["plan_version"] == 2, "second attempt did not target latest plan")
        assert_condition(
            second_dispatch["revision_of_dispatch_ref"] == first_dispatch["dispatch_ref"],
            "second attempt did not link to first dispatch",
        )
        assert_condition(model["snapshot"]["currentStage"] == "dispatch_queued", "second dispatch did not queue")

    return {
        "id": "module:review-replan",
        "stage": "plan_ready",
        "permissionScope": "execute",
        "dispatchRef": first_dispatch["dispatch_ref"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the command-only review replan process test.")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--agent-root", required=True)
    args = parser.parse_args(argv)

    result = run(Path(args.repo_root).resolve(), Path(args.agent_root).resolve())
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
