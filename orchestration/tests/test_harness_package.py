from __future__ import annotations

import os
import json
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from orchestration.harness import (
    artifacts,
    cli,
    contracts,
    executor_runtime,
    intake,
    reviewer,
    runtime_support,
    session,
    spawn_bridge,
    start_guard,
    transition,
)
from orchestration.harness.paths import load_json
from orchestration.harness.scenario_fixtures import (
    list_scenarios,
    materialize_scenario,
    temporary_scenario_repo,
)


class HarnessPackageTests(unittest.TestCase):
    def _mock_governor_dialogue(
        self,
        *,
        body: str = "Governor interactive reply.",
        primary_ref: str | None = None,
    ) -> mock._patch:
        return mock.patch.object(
            session,
            "_continue_governor_dialogue",
            return_value=(body, ["Governor interactive thread"], primary_ref),
        )

    def _semantic_submit(self, route_type: str = "governed_work_intent") -> dict[str, str]:
        return {
            "turn_type": route_type,
            "semantic_route_type": route_type,
            "semantic_confidence": "high",
        }

    def _governor_first_submit(self, repo_root: Path, text: str = "hello!") -> dict:
        return session.dispatch_session_action(
            "submit_prompt",
            text=text,
            request_id="req-governor-first",
            semantic_mode="governor-first",
            governor_runtime="external",
            repo_root=repo_root,
        )

    def _governor_semantic_body(
        self,
        route_type: str,
        *,
        reply: str = "Candidate reply.",
        recommended_permission: str = "none",
        confidence: str = "high",
        extra: dict | None = None,
    ) -> str:
        proposal = {
            "route_type": route_type,
            "normalized_intent": "Normalized request.",
            "recommended_permission": recommended_permission,
            "needs_clarification": route_type == "clarification_needed",
            "clarification_question": "What should Corgi focus on?",
            "clarification_options": [
                {"label": "Architecture", "value": "Focus on architecture."}
            ],
            "plan_intent": {},
            "confidence": confidence,
            "internal_reason": "test-only internal reason",
        }
        if extra:
            proposal.update(extra)
        return json.dumps({"user_visible_reply": reply, "proposal": proposal})

    def _write_governor_prompt(self, repo_root: Path) -> None:
        prompt_dir = repo_root / "orchestration" / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        (prompt_dir / "governor.txt").write_text(
            "You are the Governor. Return only user-facing text.",
            encoding="utf-8",
        )

    def test_intake_module_ready_and_acceptance_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            envelope = intake.start_intake(
                "Implement the harness package while preserving the Codex-like sidebar.",
                repo_root=repo_root,
            )
            self.assertEqual(envelope["shell_state"], "ready_for_acceptance")

            draft = load_json(
                intake.request_draft_path(envelope["intake_ref"], repo_root=repo_root)
            )
            contracts.validate_request_draft(draft, require_ready=True)

            accepted = intake.accept_intake(
                envelope["intake_ref"],
                lane="lane/test",
                branch="feature/test",
                repo_root=repo_root,
            )
            self.assertTrue((repo_root / accepted["accepted_intake_ref"]).exists())

    def test_intake_preserves_raw_text_but_uses_normalized_text_for_draft(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            envelope = intake.start_intake(
                "analyze the repo",
                normalized_text="Analyze the repo while focusing on architecture, structure, and subsystem boundaries.",
                repo_root=repo_root,
            )

            raw_request = intake.raw_request_path(envelope["intake_ref"], repo_root=repo_root).read_text(
                encoding="utf-8"
            )
            draft = load_json(
                intake.request_draft_path(envelope["intake_ref"], repo_root=repo_root)
            )

            self.assertEqual(raw_request.strip(), "analyze the repo")
            self.assertEqual(
                draft["normalized_goal"],
                "Analyze the repo while focusing on architecture, structure, and subsystem boundaries.",
            )
            self.assertIn("architecture", draft["draft_summary"].lower())

    def test_session_module_preserves_current_model_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            self.assertEqual(model["snapshot"]["currentActor"], "intake_shell")
            self.assertEqual(model["snapshot"]["currentStage"], "clarification_needed")
            self.assertIsNotNone(model["activeClarification"])

            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep inline artifact actions visible.",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            self.assertEqual(model["snapshot"]["currentActor"], "orchestration")
            self.assertEqual(model["snapshot"]["currentStage"], "permission_needed")
            self.assertIsNotNone(model["snapshot"]["pendingPermissionRequest"])

    def test_session_governor_dialogue_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="What is the current progress?",
                repo_root=repo_root,
                **self._semantic_submit("governor_dialogue"),
            )

            self.assertEqual(model["snapshot"]["currentActor"], "orchestration")
            self.assertEqual(model["snapshot"]["currentStage"], "permission_needed")
            self.assertIsNone(model["activeClarification"])
            self.assertIsNotNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertFalse((repo_root / ".agent" / "intakes").exists())

    def test_session_natural_follow_up_questions_route_to_governor_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="what happen?",
                repo_root=repo_root,
                **self._semantic_submit("governor_dialogue"),
            )

            self.assertEqual(model["snapshot"]["currentStage"], "permission_needed")
            self.assertIsNone(model["activeClarification"])
            self.assertIsNotNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertFalse((repo_root / ".agent" / "intakes").exists())

    def test_session_observe_permission_resumes_pending_governor_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="hello!",
                turn_type="governor_dialogue",
                semantic_route_type="governor_dialogue",
                semantic_confidence="high",
                request_id="req-hello",
                repo_root=repo_root,
            )

            self.assertEqual(
                model["snapshot"]["pendingPermissionRequest"]["continuationKind"],
                "governor_dialogue",
            )
            self.assertIsNone(session.load_session(repo_root)["meta"]["activeIntakeRef"])

            with self._mock_governor_dialogue(body="Hello from the interactive governor."):
                model = session.dispatch_session_action(
                    "set_permission_scope",
                    permission_scope="observe",
                    request_id="req-observe-click",
                    context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                    repo_root=repo_root,
                )

            self.assertEqual(model["snapshot"]["permissionScope"], "observe")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertEqual(model["snapshot"]["currentActor"], "governor")
            self.assertEqual(model["snapshot"]["currentStage"], "dialogue_ready")
            self.assertEqual(model["feed"][-1]["type"], "actor_event")
            self.assertEqual(model["feed"][-1]["title"], "Governor response")
            self.assertEqual(model["feed"][-1]["body"], "Hello from the interactive governor.")
            self.assertEqual(model["feed"][-1]["in_response_to_request_id"], "req-hello")

    def test_external_governor_prepare_and_complete_appends_real_governor_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="hello!",
                request_id="req-hello",
                repo_root=repo_root,
                **self._semantic_submit("governor_dialogue"),
            )

            prepared = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="observe",
                request_id="req-observe",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                governor_runtime="external",
                repo_root=repo_root,
            )

            self.assertEqual(prepared["kind"], "governor_runtime_request")
            runtime_request = prepared["request"]
            self.assertEqual(runtime_request["requestId"], "req-hello")
            self.assertIn("initialPrompt", runtime_request)
            self.assertIn("resumePrompt", runtime_request)
            self.assertEqual(prepared["model"]["snapshot"]["currentStage"], "waiting_for_governor")
            payload = session.load_session(repo_root)
            self.assertEqual(
                payload["meta"]["pendingGovernorRuntimeRequest"]["runtimeRequestId"],
                runtime_request["runtimeRequestId"],
            )

            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=runtime_request["runtimeRequestId"],
                runtime_body="Hello from app-server Governor.",
                runtime_thread_id="thread-app-1",
                runtime_turn_id="turn-app-1",
                runtime_item_id="item-app-1",
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["currentStage"], "dialogue_ready")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertEqual(model["feed"][-1]["type"], "actor_event")
            self.assertEqual(model["feed"][-1]["source_actor"], "governor")
            self.assertEqual(model["feed"][-1]["body"], "Hello from app-server Governor.")
            payload = session.load_session(repo_root)
            self.assertIsNone(payload["meta"].get("pendingGovernorRuntimeRequest"))
            self.assertEqual(
                payload["meta"]["governorDialogue"]["appServerThreadId"],
                "thread-app-1",
            )

    def test_external_governor_plan_completion_creates_plan_ready_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="analyze the repo",
                request_id="req-analyze",
                repo_root=repo_root,
                **self._semantic_submit("governed_work_intent"),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Focus on architecture.",
                request_id="req-clarify",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            prepared = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="plan",
                request_id="req-plan",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                governor_runtime="external",
                repo_root=repo_root,
            )

            self.assertEqual(prepared["kind"], "governor_runtime_request")
            runtime_request = prepared["request"]
            self.assertEqual(runtime_request["runtimeKind"], "plan")
            self.assertEqual(runtime_request["resultStage"], "plan_ready")
            self.assertIn("Governor planning checkpoint", runtime_request["initialPrompt"])
            self.assertNotIn("Read first:", runtime_request["initialPrompt"])

            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=runtime_request["runtimeRequestId"],
                runtime_body="Objective: inspect the repo. Steps: map extension and orchestration.",
                runtime_thread_id="thread-plan-1",
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["currentStage"], "plan_ready")
            self.assertIsNotNone(model["planReadyRequest"])
            self.assertEqual(
                model["planReadyRequest"]["allowedActions"],
                ["execute_plan", "revise_plan"],
            )

    def test_external_governor_unknown_runtime_request_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id="missing",
                runtime_body="Should not be accepted.",
                repo_root=repo_root,
            )

            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["feed"][-1]["title"], "Governor runtime request changed")

    def test_governor_first_semantic_intake_prepares_hidden_runtime_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)

            prepared = self._governor_first_submit(repo_root, "what happened?")

            self.assertEqual(prepared["kind"], "governor_runtime_request")
            self.assertEqual(prepared["request"]["runtimeKind"], "semantic_intake")
            self.assertIn("Governor semantic-intake proposer", prepared["request"]["initialPrompt"])
            self.assertNotIn("Read first:", prepared["request"]["initialPrompt"])
            self.assertEqual(prepared["model"]["snapshot"]["currentStage"], "semantic_intake")
            self.assertEqual(prepared["model"]["feed"][-1]["type"], "user_message")
            self.assertNotIn("proposal", json.dumps(prepared["model"]))

    def test_governor_first_dialogue_commits_only_after_read_only_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)
            payload = session.load_session(repo_root)
            payload["model"]["snapshot"]["permissionScope"] = "observe"
            session.save_session(payload, repo_root=repo_root)

            prepared = self._governor_first_submit(repo_root, "what happened?")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "governor_dialogue",
                    reply="Here is the current status.",
                ),
                runtime_thread_id="thread-semantic-1",
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["currentStage"], "dialogue_ready")
            self.assertEqual(model["feed"][-1]["type"], "actor_event")
            self.assertEqual(model["feed"][-1]["body"], "Here is the current status.")

    def test_governor_first_high_confidence_clarification_reply_without_active_clarification_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)

            prepared = self._governor_first_submit(repo_root, "architecture")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "clarification_reply",
                    reply="I can use that clarification.",
                ),
                repo_root=repo_root,
            )

            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertIsNone(model["activeClarification"])
            self.assertEqual(model["snapshot"]["permissionScope"], "unset")

    def test_governor_first_plan_ready_without_accepted_intake_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)

            prepared = self._governor_first_submit(repo_root, "make a plan")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "plan_ready",
                    reply="Plan: inspect the repo.",
                    extra={"plan_intent": {"objective": "Inspect repo"}},
                ),
                repo_root=repo_root,
            )

            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertIsNone(model["planReadyRequest"])
            self.assertFalse((repo_root / ".agent" / "dispatches").exists())

    def test_governor_first_execute_permission_without_plan_context_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)

            prepared = self._governor_first_submit(repo_root, "execute this")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "permission_needed",
                    reply="Execution is ready.",
                    recommended_permission="execute",
                ),
                repo_root=repo_root,
            )

            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertEqual(model["snapshot"]["permissionScope"], "unset")
            self.assertEqual(model["snapshot"]["runState"], "idle")

    def test_governor_first_state_changing_dialogue_proposal_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)
            payload = session.load_session(repo_root)
            payload["model"]["snapshot"]["permissionScope"] = "observe"
            session.save_session(payload, repo_root=repo_root)

            prepared = self._governor_first_submit(repo_root, "what happened?")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "governor_dialogue",
                    reply="I will start planning.",
                    recommended_permission="plan",
                ),
                repo_root=repo_root,
            )

            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertIsNone(model["planReadyRequest"])
            self.assertEqual(model["snapshot"]["permissionScope"], "observe")
            self.assertFalse((repo_root / ".agent" / "intakes").exists())

    def test_governor_first_direct_permission_scope_mutation_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)

            prepared = self._governor_first_submit(repo_root, "please continue")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "permission_needed",
                    reply="Permission is granted.",
                    recommended_permission="plan",
                    extra={"permission_scope": "plan"},
                ),
                repo_root=repo_root,
            )

            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["snapshot"]["permissionScope"], "unset")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])

    def test_governor_first_dispatch_like_proposal_without_execute_permission_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)

            prepared = self._governor_first_submit(repo_root, "dispatch and execute")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "dispatch",
                    reply="I will dispatch execution now.",
                    recommended_permission="execute",
                ),
                repo_root=repo_root,
            )

            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["snapshot"]["runState"], "idle")
            self.assertFalse((repo_root / ".agent" / "dispatches").exists())

    def test_external_governor_fallback_uses_exec_path_with_governor_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="hello!",
                request_id="req-hello",
                repo_root=repo_root,
                **self._semantic_submit("governor_dialogue"),
            )
            prepared = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="observe",
                request_id="req-observe",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                governor_runtime="external",
                repo_root=repo_root,
            )
            runtime_request_id = prepared["request"]["runtimeRequestId"]

            with mock.patch.object(
                session,
                "_run_governor_exec",
                return_value=("thread-exec-1", "Fallback Governor reply."),
            ):
                model = session.dispatch_session_action(
                    "fallback_governor_turn",
                    runtime_request_id=runtime_request_id,
                    fallback_reason="app-server failed in test",
                    repo_root=repo_root,
                )

            self.assertEqual(model["feed"][-1]["type"], "actor_event")
            self.assertEqual(model["feed"][-1]["source_actor"], "governor")
            self.assertEqual(model["feed"][-1]["body"], "Fallback Governor reply.")
            payload = session.load_session(repo_root)
            self.assertEqual(payload["meta"]["governorDialogue"]["threadId"], "thread-exec-1")
            self.assertEqual(
                payload["meta"]["governorDialogue"]["lastRuntimeSource"],
                "exec-fallback",
            )

    def test_external_governor_fail_fast_records_error_without_exec_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="hello!",
                request_id="req-hello",
                repo_root=repo_root,
                **self._semantic_submit("governor_dialogue"),
            )
            prepared = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="observe",
                request_id="req-observe",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                governor_runtime="external",
                repo_root=repo_root,
            )

            with mock.patch.object(session, "_run_governor_exec") as exec_mock:
                model = session.dispatch_session_action(
                    "fail_governor_turn",
                    runtime_request_id=prepared["request"]["runtimeRequestId"],
                    fallback_reason="app-server timed out",
                    repo_root=repo_root,
                )

            exec_mock.assert_not_called()
            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["feed"][-1]["title"], "Governor unavailable")
            self.assertEqual(model["snapshot"]["currentStage"], "dialogue_failed")
            payload = session.load_session(repo_root)
            self.assertIsNone(payload["meta"].get("pendingGovernorRuntimeRequest"))
            self.assertEqual(
                payload["meta"]["governorDialogue"]["lastAppServerFailureReason"],
                "app-server timed out",
            )

    def test_scenario_fixture_loader_materializes_checked_in_state(self) -> None:
        self.assertIn("accepted_idle", list_scenarios())
        self.assertIn("completed_with_governor_decision", list_scenarios())

        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = materialize_scenario("accepted_idle", tmp_dir)
            self.assertTrue(
                (repo_root / ".agent" / "orchestration" / "ui_session.json").exists()
            )
            self.assertTrue(
                (repo_root / ".agent" / "intakes" / "fixture-accepted-idle" / "accepted_intake.json").exists()
            )

    def test_governor_dialogue_context_includes_accepted_intake_artifact(self) -> None:
        with temporary_scenario_repo("accepted_idle") as repo_root:
            payload = session.load_session(repo_root)
            payload["model"]["snapshot"]["permissionScope"] = "observe"
            session.save_session(payload, repo_root=repo_root)
            context = session._governor_dialogue_context(
                session.load_session(repo_root),
                "What is the current progress?",
                repo_root=repo_root,
            )
            self.assertIn("accepted_intake_ref:", context["prompt"])
            self.assertIn("accepted intake is bound", context["prompt"])
            self.assertTrue(str(context["primary_ref"]).endswith("accepted_intake.json"))

    def test_governor_dialogue_context_includes_dispatch_and_transition_artifacts(self) -> None:
        with temporary_scenario_repo("completed_with_governor_decision") as repo_root:
            payload = session.load_session(repo_root)
            payload["model"]["snapshot"]["permissionScope"] = "observe"
            session.save_session(payload, repo_root=repo_root)
            context = session._governor_dialogue_context(
                session.load_session(repo_root),
                "What is the current progress?",
                repo_root=repo_root,
            )
            self.assertIn("latest_dispatch_request_ref: .agent/dispatches/lane/intake/dispatch-001/request.json", context["prompt"])
            self.assertIn("Result status is completed", context["prompt"])
            self.assertEqual(
                context["primary_ref"],
                ".agent/dispatches/lane/intake/dispatch-001/governor_decision.json",
            )
            self.assertTrue(any("Proposed transition:" in detail for detail in context.get("details", [])))

    def test_session_state_reads_ready_for_acceptance_fixture(self) -> None:
        with temporary_scenario_repo("ready_for_acceptance") as repo_root:
            model = session.dispatch_session_action("state", repo_root=repo_root)
            self.assertEqual(model["snapshot"]["currentStage"], "ready_for_acceptance")
            self.assertIsNotNone(model["snapshot"].get("pendingPermissionRequest") or model["snapshot"].get("pendingApproval"))
            self.assertIsNone(model["activeClarification"])

    def test_session_state_reads_running_dispatch_fixture(self) -> None:
        with temporary_scenario_repo("running_dispatch") as repo_root:
            model = session.dispatch_session_action("state", repo_root=repo_root)
            self.assertEqual(model["snapshot"]["runState"], "running")
            self.assertEqual(model["snapshot"]["currentActor"], "governor")

            with self._mock_governor_dialogue(
                body="Interactive governor progress reply.",
                primary_ref=".agent/dispatches/lane/intake/dispatch-001/state.json",
            ):
                progress_model = session.dispatch_session_action(
                    "submit_prompt",
                    text="What is the current progress?",
                    repo_root=repo_root,
                    **self._semantic_submit("governor_dialogue"),
                )
            actor_events = [item for item in progress_model["feed"] if item["type"] == "actor_event"]
            latest = actor_events[-1]
            self.assertEqual(latest["body"], "Interactive governor progress reply.")
            self.assertEqual(
                latest["source_artifact_ref"],
                ".agent/dispatches/lane/intake/dispatch-001/state.json",
            )

    def test_governor_dialogue_runner_reuses_persistent_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            payload = session.load_session(repo_root)
            calls: list[list[str]] = []

            def fake_run(*args, **kwargs):
                command = list(args[0])
                calls.append(command)
                if "resume" in command:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=(
                            '{"type":"thread.started","thread_id":"thread-1"}\n'
                            '{"type":"item.completed","item":{"type":"agent_message","text":"follow-up reply"}}\n'
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=(
                        '{"type":"thread.started","thread_id":"thread-1"}\n'
                        '{"type":"item.completed","item":{"type":"agent_message","text":"first reply"}}\n'
                    ),
                    stderr="",
                )

            prompt_root = Path(__file__).resolve().parents[2] / "orchestration" / "prompts" / "governor.txt"
            with mock.patch.object(session.subprocess, "run", side_effect=fake_run):
                with mock.patch.object(session, "prompt_path", return_value=prompt_root):
                    first = session._continue_governor_dialogue(
                        payload, "hello!", repo_root=repo_root
                    )
                    second = session._continue_governor_dialogue(
                        payload, "what happened?", repo_root=repo_root
                    )

            self.assertEqual(first[0], "first reply")
            self.assertEqual(second[0], "follow-up reply")
            self.assertEqual(payload["meta"]["governorDialogue"]["threadId"], "thread-1")
            self.assertTrue(any(command[:3] == ["codex", "exec", "resume"] for command in calls))

    def test_session_analysis_prompt_returns_structured_clarification_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze this folder.",
                repo_root=repo_root,
                **self._semantic_submit(),
            )

            self.assertEqual(model["snapshot"]["currentStage"], "clarification_needed")
            self.assertEqual(model["activeClarification"]["kind"], "analysis_focus")
            self.assertEqual(len(model["activeClarification"]["options"]), 3)
            self.assertTrue(model["activeClarification"]["allowFreeText"])

            model = session.dispatch_session_action(
                "answer_clarification",
                text=model["activeClarification"]["options"][0]["answer"],
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            self.assertEqual(model["snapshot"]["currentStage"], "permission_needed")
            self.assertIsNotNone(model["snapshot"]["pendingPermissionRequest"])

    def test_session_execute_permission_sets_session_mode_and_running_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            clarification_model = session.load_session(repo_root)["model"]
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep inline artifact actions visible.",
                context_ref=clarification_model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            self.assertIsNotNone(model["snapshot"]["pendingPermissionRequest"])

            model = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="execute",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["permissionScope"], "execute")
            self.assertEqual(model["snapshot"]["runState"], "running")
            self.assertEqual(model["snapshot"]["currentActor"], "executor")
            self.assertEqual(model["snapshot"]["currentStage"], "dispatch_queued")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIn("Execute permission", model["acceptedIntakeSummary"]["body"])
            dispatch_requests = sorted(
                (repo_root / ".agent" / "dispatches").glob("**/request.json")
            )
            self.assertEqual(len(dispatch_requests), 1)
            request_payload = load_json(dispatch_requests[0])
            self.assertEqual(request_payload["execution_mode"], "manual_artifact_report")
            self.assertTrue(request_payload["review_required"])
            self.assertEqual(
                model["feed"][-1]["source_artifact_ref"],
                str(dispatch_requests[0].relative_to(repo_root)),
            )

    def test_session_plan_permission_returns_governor_planning_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze the repo.",
                request_id="corgi-request:plan-submit",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Focus on architecture, structure, and subsystem boundaries.",
                request_id="corgi-request:plan-clarification",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            self.assertIsNotNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertEqual(
                model["snapshot"]["pendingPermissionRequest"]["allowedScopes"],
                ["plan", "execute"],
            )

            with self._mock_governor_dialogue(body="Here is the architecture planning response."):
                model = session.dispatch_session_action(
                    "set_permission_scope",
                    permission_scope="plan",
                    request_id="corgi-request:plan-click",
                    context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                    repo_root=repo_root,
                )

            self.assertEqual(model["snapshot"]["permissionScope"], "plan")
            self.assertEqual(model["snapshot"]["runState"], "idle")
            self.assertEqual(model["snapshot"]["currentActor"], "governor")
            self.assertEqual(model["snapshot"]["currentStage"], "plan_ready")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIsNotNone(model["acceptedIntakeSummary"])
            self.assertIsNotNone(model["planReadyRequest"])
            self.assertEqual(
                model["planReadyRequest"]["foregroundRequestId"],
                "corgi-request:plan-submit",
            )
            self.assertEqual(
                model["planReadyRequest"]["allowedActions"],
                ["execute_plan", "revise_plan"],
            )
            self.assertEqual(model["feed"][-1]["type"], "actor_event")
            self.assertEqual(model["feed"][-1]["source_actor"], "governor")
            self.assertEqual(model["feed"][-1]["body"], "Here is the architecture planning response.")
            self.assertEqual(
                model["feed"][-1]["in_response_to_request_id"],
                "corgi-request:plan-submit",
            )

    def test_session_rejects_permission_scope_below_recommended_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze the repo.",
                request_id="corgi-request:weaker-submit",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Focus on architecture, structure, and subsystem boundaries.",
                request_id="corgi-request:weaker-answer",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            self.assertEqual(
                model["snapshot"]["pendingPermissionRequest"]["recommendedScope"],
                "plan",
            )

            model = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="observe",
                request_id="corgi-request:weaker-observe",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["permissionScope"], "unset")
            self.assertIsNotNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIsNone(model["acceptedIntakeSummary"])
            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["feed"][-1]["title"], "Permission scope too low")
            self.assertEqual(
                model["feed"][-1].get("presentation_key"),
                "error.permission_scope_too_low",
            )

    def test_session_execute_plan_action_requests_execute_permission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze the repo.",
                request_id="corgi-request:analyze",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Focus on bugs, regressions, and architectural risks.",
                request_id="corgi-request:clarify",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            with self._mock_governor_dialogue(body="Planning response."):
                model = session.dispatch_session_action(
                    "set_permission_scope",
                    permission_scope="plan",
                    request_id="corgi-request:plan",
                    context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                    repo_root=repo_root,
                )

            model = session.dispatch_session_action(
                "execute_plan",
                request_id="corgi-request:do-it",
                context_ref=model["planReadyRequest"]["contextRef"],
                repo_root=repo_root,
            )

            self.assertIsNone(model["activeClarification"])
            self.assertEqual(model["snapshot"]["currentActor"], "orchestration")
            self.assertEqual(model["snapshot"]["currentStage"], "permission_needed")
            self.assertEqual(
                model["snapshot"]["pendingPermissionRequest"]["recommendedScope"],
                "execute",
            )
            self.assertEqual(
                model["snapshot"]["pendingPermissionRequest"]["foregroundRequestId"],
                "corgi-request:do-it",
            )
            self.assertIsNotNone(model["acceptedIntakeSummary"])
            self.assertIsNotNone(model["planReadyRequest"])
            self.assertEqual(model["feed"][-1]["type"], "permission_request")
            self.assertEqual(
                model["feed"][-1]["in_response_to_request_id"],
                "corgi-request:do-it",
            )

            model = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="execute",
                request_id="corgi-request:execute-click",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["permissionScope"], "execute")
            self.assertEqual(model["snapshot"]["currentActor"], "executor")
            self.assertEqual(model["snapshot"]["currentStage"], "dispatch_queued")
            self.assertEqual(model["snapshot"]["runState"], "running")
            self.assertIsNone(model["planReadyRequest"])
            self.assertEqual(model["feed"][-1]["type"], "system_status")
            self.assertEqual(model["feed"][-1]["title"], "Dispatch queued")
            self.assertEqual(
                model["feed"][-1]["in_response_to_request_id"],
                "corgi-request:do-it",
            )

            dispatch_requests = sorted(
                (repo_root / ".agent" / "dispatches").glob("**/request.json")
            )
            self.assertEqual(len(dispatch_requests), 1)
            request_payload = load_json(dispatch_requests[0])
            self.assertEqual(
                request_payload["execution_mode"],
                "manual_artifact_report",
            )
            self.assertTrue(request_payload["review_required"])
            self.assertIn("review_artifact_path", request_payload)
            self.assertEqual(
                model["feed"][-1]["source_artifact_ref"],
                str(dispatch_requests[0].relative_to(repo_root)),
            )
            self.assertTrue(
                any(
                    input_ref.endswith("/accepted_intake.json")
                    for input_ref in request_payload["inputs"]
                )
            )
            self.assertTrue(
                any(
                    input_ref.startswith("plan_context_ref:")
                    for input_ref in request_payload["inputs"]
                )
            )
            state_payload = load_json(dispatch_requests[0].parent / "state.json")
            self.assertEqual(state_payload["status"], "queued")

    def test_session_execute_plan_stale_context_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze the repo.",
                request_id="corgi-request:analyze",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Focus on architecture, structure, and subsystem boundaries.",
                request_id="corgi-request:clarify",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            with self._mock_governor_dialogue(body="Planning response."):
                model = session.dispatch_session_action(
                    "set_permission_scope",
                    permission_scope="plan",
                    request_id="corgi-request:plan",
                    context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                    repo_root=repo_root,
                )

            model = session.dispatch_session_action(
                "execute_plan",
                request_id="corgi-request:stale-execute",
                context_ref="stale-plan-context",
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["currentStage"], "plan_ready")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIsNotNone(model["planReadyRequest"])
            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["feed"][-1].get("presentation_key"), "error.stale_context")

    def test_session_plan_revision_keeps_plan_ready_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze the repo.",
                request_id="corgi-request:analyze",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Focus on architecture, structure, and subsystem boundaries.",
                request_id="corgi-request:clarify",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            with self._mock_governor_dialogue(body="Initial planning response."):
                model = session.dispatch_session_action(
                    "set_permission_scope",
                    permission_scope="plan",
                    request_id="corgi-request:plan",
                    context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                    repo_root=repo_root,
                )
            initial_plan_version = model["planReadyRequest"]["planVersion"]

            with self._mock_governor_dialogue(body="Revised planning response."):
                model = session.dispatch_session_action(
                    "revise_plan",
                    text="Also explain the testing risks before execution.",
                    request_id="corgi-request:revise-plan",
                    context_ref=model["planReadyRequest"]["contextRef"],
                    repo_root=repo_root,
                )

            self.assertEqual(model["snapshot"]["permissionScope"], "plan")
            self.assertEqual(model["snapshot"]["currentActor"], "governor")
            self.assertEqual(model["snapshot"]["currentStage"], "plan_ready")
            self.assertEqual(model["snapshot"]["runState"], "idle")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIsNotNone(model["planReadyRequest"])
            self.assertEqual(model["planReadyRequest"]["planVersion"], initial_plan_version + 1)
            self.assertEqual(model["feed"][-1]["type"], "actor_event")
            self.assertEqual(model["feed"][-1]["source_actor"], "governor")
            self.assertEqual(model["feed"][-1]["body"], "Revised planning response.")

    def test_session_auto_accepts_later_requests_after_execute_permission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            session.dispatch_session_action(
                "answer_clarification",
                text="Keep inline artifact actions visible.",
                context_ref=session.load_session(repo_root)["model"]["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            approval_model = session.load_session(repo_root)["model"]
            session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="execute",
                context_ref=approval_model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                repo_root=repo_root,
            )

            model = session.dispatch_session_action(
                "submit_prompt",
                text="Implement a quieter Chat transcript while keeping the VS Code Chat host, preserving inline artifact actions, and replacing visible hold and reconnect controls with cleaner approval affordances.",
                repo_root=repo_root,
                **self._semantic_submit(),
            )

            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertEqual(model["snapshot"]["permissionScope"], "execute")
            self.assertEqual(model["snapshot"]["runState"], "running")
            self.assertTrue((repo_root / ".agent" / "intakes").exists())

    def test_cli_routes_session_commands_through_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            previous = os.environ.get("ORCHESTRATION_REPO_ROOT")
            os.environ["ORCHESTRATION_REPO_ROOT"] = str(repo_root)
            try:
                result = cli.main(
                    [
                        "session",
                        "submit-prompt",
                        "--text",
                        "Build a compact execution window.",
                        "--turn-type",
                        "governed_work_intent",
                        "--semantic-route-type",
                        "governed_work_intent",
                        "--semantic-confidence",
                        "high",
                    ]
                )
            finally:
                if previous is None:
                    os.environ.pop("ORCHESTRATION_REPO_ROOT", None)
                else:
                    os.environ["ORCHESTRATION_REPO_ROOT"] = previous

            self.assertEqual(result, 0)

    def test_session_feed_items_include_internal_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze this folder.",
                repo_root=repo_root,
                **self._semantic_submit(),
            )

            clarification_items = [
                item for item in model["feed"] if item["type"] == "clarification_request"
            ]
            self.assertEqual(len(clarification_items), 1)
            self.assertEqual(clarification_items[0]["source_layer"], "intake")
            self.assertEqual(clarification_items[0]["source_actor"], "intake_shell")
            self.assertEqual(clarification_items[0]["turn_type"], "governed_work_intent")

    def test_session_uses_semantic_normalized_text_but_preserves_raw_human_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="analyze the repo",
                turn_type="governed_work_intent",
                normalized_text="Analyze the repo while focusing on architecture, structure, and subsystem boundaries.",
                paraphrase="Ask Corgi to analyze the repo with an architecture focus.",
                semantic_input_version="corgi-semantic-sidecar.v1",
                semantic_summary_ref="semantic-summary:test",
                semantic_context_flags={
                    "used_controller_summary": True,
                    "used_accepted_intake_summary": False,
                    "used_dialogue_summary": False,
                    "had_active_clarification": False,
                    "had_pending_permission_request": False,
                    "had_pending_interrupt": False,
                },
                semantic_route_type="governed_work_intent",
                semantic_confidence="high",
                repo_root=repo_root,
            )

            user_items = [item for item in model["feed"] if item["type"] == "user_message"]
            self.assertEqual(user_items[-1]["body"], "analyze the repo")
            self.assertEqual(
                user_items[-1]["semantic_normalized_text"],
                "Analyze the repo while focusing on architecture, structure, and subsystem boundaries.",
            )

            active_intake_ref = session.load_session(repo_root)["meta"]["activeIntakeRef"]
            draft = load_json(
                intake.request_draft_path(active_intake_ref, repo_root=repo_root)
            )
            self.assertEqual(
                draft["normalized_goal"],
                "Analyze the repo while focusing on architecture, structure, and subsystem boundaries.",
            )

    def test_session_rejects_stale_clarification_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                request_id="corgi-request:clarification-submit",
                repo_root=repo_root,
                **self._semantic_submit(),
            )

            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep inline artifact actions visible.",
                request_id="corgi-request:clarification-answer",
                context_ref="clarification-context-stale",
                repo_root=repo_root,
            )

            last_item = model["feed"][-1]
            self.assertEqual(last_item["type"], "error")
            self.assertEqual(
                last_item["in_response_to_request_id"],
                "corgi-request:clarification-answer",
            )
            self.assertIn("Clarification changed", last_item["title"])
            self.assertEqual(last_item.get("presentation_key"), "error.stale_context")

    def test_session_rejects_duplicate_request_id_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze this folder.",
                request_id="corgi-request:duplicate",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            initial_clarifications = [
                item for item in model["feed"] if item["type"] == "clarification_request"
            ]

            replay_model = session.dispatch_session_action(
                "submit_prompt",
                text="Analyze this folder.",
                request_id="corgi-request:duplicate",
                repo_root=repo_root,
                **self._semantic_submit(),
            )

            replay_clarifications = [
                item for item in replay_model["feed"] if item["type"] == "clarification_request"
            ]
            last_item = replay_model["feed"][-1]
            self.assertEqual(last_item["type"], "error")
            self.assertEqual(last_item["title"], "Duplicate request")
            self.assertEqual(
                last_item["in_response_to_request_id"],
                "corgi-request:duplicate",
            )
            self.assertEqual(last_item.get("presentation_key"), "error.duplicate_request")
            self.assertEqual(len(replay_clarifications), len(initial_clarifications))

    def test_submit_prompt_without_session_ref_bootstraps_normally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="analyze the repo",
                request_id="corgi-request:no-session-ref",
                repo_root=repo_root,
                **self._semantic_submit(),
            )

            self.assertNotEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["snapshot"]["currentStage"], "clarification_needed")

    def test_submit_prompt_without_semantic_routing_metadata_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="what happened?",
                request_id="corgi-request:missing-semantic-route",
                repo_root=repo_root,
            )

            last_item = model["feed"][-1]
            self.assertEqual(last_item["type"], "error")
            self.assertEqual(last_item["title"], "Semantic route required")
            self.assertEqual(last_item.get("presentation_key"), "error.semantic_route_required")
            self.assertEqual(
                last_item["in_response_to_request_id"],
                "corgi-request:missing-semantic-route",
            )
            self.assertIsNone(model["snapshot"].get("pendingPermissionRequest"))
            self.assertIsNone(model.get("activeClarification"))

    def test_submit_prompt_with_wrong_session_ref_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="hello",
                session_ref="session-wrong",
                request_id="corgi-request:wrong-session-ref",
                repo_root=repo_root,
                **self._semantic_submit("governor_dialogue"),
            )

            last_item = model["feed"][-1]
            self.assertEqual(last_item["type"], "error")
            self.assertEqual(last_item["title"], "Session changed")
            self.assertEqual(last_item.get("presentation_key"), "error.session_changed")

    def test_session_rejects_stale_permission_scope_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                request_id="corgi-request:permission-submit",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep the scope minimal.",
                request_id="corgi-request:permission-answer",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            model = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="plan",
                request_id="corgi-request:permission-stale",
                context_ref="permission-context-stale",
                repo_root=repo_root,
            )

            last_item = model["feed"][-1]
            self.assertEqual(last_item["type"], "error")
            self.assertEqual(last_item["title"], "Permission changed")
            self.assertEqual(last_item.get("presentation_key"), "error.stale_context")

    def test_session_rejects_stale_decline_permission_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                request_id="corgi-request:decline-submit",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep the scope minimal.",
                request_id="corgi-request:decline-answer",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            model = session.dispatch_session_action(
                "decline_permission",
                request_id="corgi-request:decline-stale",
                context_ref="permission-context-stale",
                repo_root=repo_root,
            )

            last_item = model["feed"][-1]
            self.assertEqual(last_item["type"], "error")
            self.assertEqual(last_item["title"], "Permission changed")
            self.assertEqual(last_item.get("presentation_key"), "error.stale_context")

    def test_session_rejects_stale_interrupt_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                request_id="corgi-request:interrupt-submit",
                repo_root=repo_root,
                **self._semantic_submit(),
            )
            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep the scope minimal.",
                request_id="corgi-request:interrupt-answer",
                context_ref=model["activeClarification"]["contextRef"],
                repo_root=repo_root,
            )
            model = session.dispatch_session_action(
                "set_permission_scope",
                permission_scope="execute",
                request_id="corgi-request:interrupt-execute",
                context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                repo_root=repo_root,
            )
            model = session.dispatch_session_action(
                "interrupt_run",
                request_id="corgi-request:interrupt-stale",
                context_ref="interrupt-context-stale",
                repo_root=repo_root,
            )

            last_item = model["feed"][-1]
            self.assertEqual(last_item["type"], "error")
            self.assertEqual(last_item["title"], "Interrupt state changed")
            self.assertEqual(last_item.get("presentation_key"), "error.stale_context")

    def test_initial_state_persists_session_ref_for_first_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            state_model = session.dispatch_session_action("state", repo_root=repo_root)
            session_ref = state_model["snapshot"]["sessionRef"]

            next_model = session.dispatch_session_action(
                "submit_prompt",
                text="analyze the repo",
                session_ref=session_ref,
                request_id="corgi-request:first-request",
                repo_root=repo_root,
                **self._semantic_submit(),
            )

            self.assertNotEqual(next_model["feed"][-1]["type"], "error")
            self.assertEqual(next_model["snapshot"]["sessionRef"], session_ref)
            self.assertEqual(next_model["snapshot"]["currentStage"], "clarification_needed")

    def test_transition_module_records_and_loads_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            payload = transition.build_transition_payload(
                repo_root=repo_root,
                lane="lane/test",
                source="governor",
                transition="continue_internal",
                next_action_kind="emit_dispatch",
                next_action_summary="Continue dispatch flow.",
            )
            path = transition.record_transition(repo_root, payload)

            self.assertTrue(path.exists())
            loaded = transition.load_transition(repo_root, "lane/test")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["transition"], "continue_internal")

    def test_dispatch_emit_module_writes_request_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            from orchestration.harness import dispatch

            result = dispatch.emit_main(
                [
                    "--dispatch-ref",
                    "lane/test/dispatch-001",
                    "--objective",
                    "Refactor orchestration harness internals.",
                    "--lane",
                    "lane/test",
                    "--root",
                    str(repo_root),
                ]
            )
            self.assertEqual(result, 0)
            dispatch_dir = repo_root / ".agent" / "dispatches" / "lane" / "test" / "dispatch-001"
            self.assertTrue((dispatch_dir / "request.json").exists())
            self.assertTrue((dispatch_dir / "state.json").exists())

    def test_start_guard_module_allows_clean_dispatch_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            dispatch_dir = repo_root / ".agent" / "dispatches" / "lane" / "test" / "dispatch-001"
            dispatch_dir.mkdir(parents=True, exist_ok=True)
            (dispatch_dir / "request.json").write_text(
                '{\n  "dispatch_ref": "lane/test/dispatch-001",\n  "lane": "lane/test",\n  "scope": ["README.md"],\n  "required_outputs": [],\n  "execution_mode": "manual_artifact_report"\n}\n',
                encoding="utf-8",
            )

            result = start_guard.main(
                ["--dispatch-dir", str(dispatch_dir), "--root", str(repo_root)]
            )
            self.assertEqual(result, 0)

    def test_dispatch_validator_runs_from_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            from orchestration.harness import dispatch

            emit_result = dispatch.emit_main(
                [
                    "--dispatch-ref",
                    "cycle/test/scope/task/dispatch-002",
                    "--objective",
                    "Validate the package-backed dispatch contract path.",
                    "--lane",
                    "lane/test",
                    "--root",
                    str(repo_root),
                ]
            )
            self.assertEqual(emit_result, 0)

            dispatch_dir = (
                repo_root
                / ".agent"
                / "dispatches"
                / "cycle"
                / "test"
                / "scope"
                / "task"
                / "dispatch-002"
            )
            validate_result = contracts.run_dispatch_validator([str(dispatch_dir)])
            self.assertEqual(validate_result, 0)

    def test_spawn_bridge_module_resolves_helper_runtime_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            dispatch_ref = "cycle/test/scope/task/dispatch-003"
            dispatch_dir = repo_root / ".agent" / "dispatches" / "cycle" / "test" / "scope" / "task" / "dispatch-003"
            dispatch_dir.mkdir(parents=True, exist_ok=True)
            (dispatch_dir / "request.json").write_text(
                '{\n'
                '  "dispatch_ref": "cycle/test/scope/task/dispatch-003",\n'
                '  "execution_mode": "manual_artifact_report",\n'
                '  "review_required": false\n'
                '}\n',
                encoding="utf-8",
            )

            payload = spawn_bridge.resolve_dispatch_path_for_ref(repo_root, dispatch_ref)

            self.assertEqual(payload["resolved_path"], spawn_bridge.HELPER_RUNTIME_PATH)
            self.assertFalse(payload["spawn_required"])

    def test_executor_runtime_module_blocks_subagent_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            dispatch_dir = repo_root / ".agent" / "dispatches" / "cycle" / "test" / "scope" / "task" / "dispatch-004"
            dispatch_dir.mkdir(parents=True, exist_ok=True)

            with self.assertRaises(SystemExit):
                executor_runtime.ensure_helper_runtime_dispatch(
                    dispatch_dir,
                    {"execution_mode": "guided_agent"},
                )

    def test_reviewer_module_resolves_default_artifact_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            path = reviewer.resolve_review_artifact_path(
                repo_root,
                "cycle/test/scope/task/dispatch-005",
                None,
            )
            self.assertEqual(
                path,
                repo_root / ".agent" / "reviews" / "cycle" / "test" / "scope" / "task" / "dispatch-005" / "review.json",
            )

    def test_runtime_support_scope_audit_flags_undeclared_untracked_files(self) -> None:
        report = runtime_support.scope_audit(
            before={},
            after={"reports/output.json": "??"},
            declared_files=["README.md"],
        )
        self.assertEqual(report["undeclared_untracked"], ["reports/output.json"])

    def test_artifacts_module_rejects_control_fields_in_review_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            review_path = Path(tmp_dir) / "review.json"
            review_path.write_text(
                '{\n'
                '  "dispatch_ref": "cycle/test/scope/task/dispatch-006",\n'
                '  "reviewer_role": "agentR",\n'
                '  "verdict": "pass",\n'
                '  "validator_assessment": [],\n'
                '  "scope_assessment": [],\n'
                '  "findings": [],\n'
                '  "residual_risks": [],\n'
                '  "recommendation": "Looks good.",\n'
                '  "decision": "accept"\n'
                '}\n',
                encoding="utf-8",
            )

            with self.assertRaises(artifacts.ArtifactContractError):
                artifacts.load_review_artifact(review_path)
