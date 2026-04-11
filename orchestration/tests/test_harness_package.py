from __future__ import annotations

import os
import tempfile
import unittest
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


class HarnessPackageTests(unittest.TestCase):
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

    def test_session_module_preserves_current_model_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            model = session.dispatch_session_action(
                "submit_prompt",
                text="Build a compact execution window.",
                repo_root=repo_root,
            )
            self.assertEqual(model["snapshot"]["currentActor"], "intake_shell")
            self.assertEqual(model["snapshot"]["currentStage"], "clarification_needed")
            self.assertIsNotNone(model["activeClarification"])

            model = session.dispatch_session_action(
                "answer_clarification",
                text="Keep inline artifact actions visible.",
                repo_root=repo_root,
            )
            self.assertEqual(model["snapshot"]["currentActor"], "orchestration")
            self.assertEqual(model["snapshot"]["currentStage"], "ready_for_acceptance")
            self.assertIsNotNone(model["snapshot"]["pendingApproval"])

    def test_cli_routes_session_commands_through_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            previous = os.environ.get("ORCHESTRATION_REPO_ROOT")
            os.environ["ORCHESTRATION_REPO_ROOT"] = str(repo_root)
            try:
                result = cli.main(
                    ["session", "submit-prompt", "--text", "Build a compact execution window."]
                )
            finally:
                if previous is None:
                    os.environ.pop("ORCHESTRATION_REPO_ROOT", None)
                else:
                    os.environ["ORCHESTRATION_REPO_ROOT"] = previous

            self.assertEqual(result, 0)

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
