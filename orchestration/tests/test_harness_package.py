from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from orchestration.harness import (
    artifacts,
    authorship_evidence,
    cli,
    contracts,
    dispatch,
    dispatch_contracts,
    dispatch_guards,
    executor_runtime,
    governor_runtime,
    intake,
    parallel_dispatch,
    patch_specs,
    reviewer,
    runtime_support,
    session,
    session_execution,
    session_state,
    spawn_bridge,
    start_guard,
    transition,
)
from orchestration.harness.paths import load_json, prompt_ref, resolve_paths, script_ref, write_json
from orchestration.harness.scenario_fixtures import (
    list_scenarios,
    materialize_scenario,
    temporary_scenario_repo,
)


class HarnessPackageTests(unittest.TestCase):
    def test_session_state_helpers_are_pure_policy_predicates(self) -> None:
        self.assertEqual(session_state.allowed_permission_scopes("plan"), ["plan", "execute"])
        self.assertTrue(session_state.scope_satisfies("execute", "plan"))
        self.assertFalse(session_state.scope_satisfies("observe", "plan"))
        self.assertTrue(
            session_state.is_snapshot_stale(
                {"snapshotFreshness": {"receivedAt": "2026-04-30T00:00:00Z"}},
                "2026-04-30T00:00:46Z",
            )
        )
        self.assertFalse(
            session_state.is_snapshot_stale(
                {"snapshotFreshness": {"receivedAt": "2026-04-30T00:00:00Z"}},
                "2026-04-30T00:00:45Z",
            )
        )

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

    def _parallel_request(
        self,
        dispatch_ref: str,
        *,
        lane: str = "lane/test",
        work_ref: str = "lane/test/work-001",
        scope: str = "src/app.js",
        parallel_set_ref: str | None = "lane/test/parallel-set-001",
        pre_review: bool = True,
        pre_review_path: str | None = None,
        resource_hints: dict | None = None,
        depends_on: list[str] | None = None,
        overlap_isolation: dict | None = None,
        execution_mode: str = "command_chain",
        task_track: str = "patch",
    ) -> dict:
        request = {
            "dispatch_ref": dispatch_ref,
            "from_role": "agentA",
            "to_role": "agentB",
            "task_kind": "bounded_task",
            "lane": lane,
            "objective": f"Run {dispatch_ref}",
            "scope": [scope],
            "non_goals": [],
            "inputs": [],
            "required_outputs": [f"reports/{dispatch_ref.replace('/', '-')}.json"],
            "acceptance_criteria": ["bounded result exists"],
            "required_validators": ["manual verification"],
            "stop_conditions": ["block on ambiguity"],
            "report_format": ["summary"],
            "work_ref": work_ref,
            "plan_ref": f"{work_ref}/plans/plan-v1.md",
            "plan_version": 1,
            "attempt_number": 1,
            "execution_mode": execution_mode,
            "task_track": task_track,
            "scope_reservations": [scope],
        }
        if parallel_set_ref is not None:
            request["parallel_set_ref"] = parallel_set_ref
            request["parallel_group"] = "group-a"
            request["parallel_intent"] = "run independent bounded tasks in parallel"
        if pre_review:
            request["pre_dispatch_review_required"] = True
            request["pre_dispatch_review_artifact_path"] = (
                pre_review_path
                or parallel_dispatch.default_pre_dispatch_review_artifact_path(dispatch_ref)
            )
        if resource_hints:
            request["resource_hints"] = resource_hints
        if depends_on:
            request["depends_on_dispatches"] = depends_on
        if overlap_isolation:
            request["overlap_isolation"] = overlap_isolation
        return request

    def _write_dispatch_request(self, repo_root: Path, request: dict, *, state: str = "queued") -> Path:
        dispatch_dir = repo_root / ".agent" / "dispatches" / request["dispatch_ref"]
        write_json(dispatch_dir / "request.json", request)
        write_json(
            dispatch_dir / "state.json",
            {
                "dispatch_ref": request["dispatch_ref"],
                "status": state,
                "claimed_by": "agentB" if state in {"claimed", "running", "validated", "completed"} else None,
                "claimed_at": "2026-04-10T10:00:00Z" if state in {"claimed", "running", "validated", "completed"} else None,
                "run_ref": None,
                "result_ref": None,
                "last_transition_at": "2026-04-10T10:00:00Z",
                "transition_history": [],
                "notes": [],
            },
        )
        return dispatch_dir

    def _write_pet_diary_patch_request(
        self,
        repo_root: Path,
        dispatch_ref: str = "lane/intake/dispatch-001",
        *,
        required_outputs: list[str] | None = None,
        planned_touches: list[str] | None = None,
    ) -> Path:
        outputs = required_outputs if required_outputs is not None else ["src/app.js"]
        touches = planned_touches if planned_touches is not None else ["src/app.js"]
        return self._write_dispatch_request(
            repo_root,
            {
                "dispatch_ref": dispatch_ref,
                "from_role": "agentA",
                "to_role": "agentB",
                "task_kind": "bounded_task",
                "lane": "lane/intake",
                "objective": "Fix the pet diary app so adding a diary entry updates the visible list.",
                "scope": ["src/app.js"],
                "non_goals": [],
                "inputs": [],
                "required_outputs": outputs,
                "acceptance_criteria": ["submitted diary entries update the visible list"],
                "required_validators": [],
                "stop_conditions": ["stop on stale patch proposal"],
                "report_format": ["summary"],
                "execution_mode": "command_chain",
                "executor_run": {
                    "run_ref": f"{dispatch_ref}/result/attempt-1",
                    "objective": "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "scope": "src/app.js",
                    "read_list": [],
                    "produce_list": outputs,
                    "planned_file_touch_list": touches,
                    "non_goals": [],
                    "stop_conditions": [],
                },
            },
        )

    def _write_minimal_buggy_pet_diary_app(self, repo_root: Path) -> Path:
        app_path = repo_root / "src" / "app.js"
        app_path.parent.mkdir(parents=True, exist_ok=True)
        app_path.write_text(
            '\n'.join(
                [
                    "const diaryEntries = [];",
                    'const form = document.querySelector("#diary-form");',
                    'const input = document.querySelector("#diary-entry-input");',
                    "function renderEntries() {}",
                    'form?.addEventListener("submit", (event) => {',
                    "\tevent.preventDefault();",
                    "\tconst text = input.value.trim();",
                    "\tif (!text) {",
                    "\t\treturn;",
                    "\t}",
                    '\tinput.value = "";',
                    "\trenderEntries();",
                    "});",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return app_path

    def _write_pre_dispatch_review(
        self,
        repo_root: Path,
        dispatch_ref: str,
        *,
        verdict: str = "pass",
        covered_dispatch_refs: list[str] | None = None,
    ) -> Path:
        review_path = repo_root / ".agent" / "reviews" / dispatch_ref / "pre_dispatch_review.json"
        payload = {
            "dispatch_ref": dispatch_ref,
            "review_phase": "pre_dispatch",
            "reviewer_role": "agentR-helper",
            "verdict": verdict,
            "validator_assessment": ["pre-dispatch scope reviewed"],
            "scope_assessment": ["scope is bounded"],
            "findings": [],
            "residual_risks": [],
            "recommendation": "parallel start is safe",
        }
        if covered_dispatch_refs is not None:
            payload["covered_dispatch_refs"] = covered_dispatch_refs
        write_json(review_path, payload)
        return review_path

    def _write_parallel_set(
        self,
        repo_root: Path,
        parallel_set_ref: str,
        dispatch_refs: list[str],
        *,
        lane: str = "lane/test",
        work_ref: str = "lane/test/work-001",
        max_active: int = 2,
    ) -> Path:
        set_path = parallel_dispatch.parallel_set_artifact_path(repo_root, parallel_set_ref)
        write_json(
            set_path,
            {
                "parallel_set_ref": parallel_set_ref,
                "work_ref": work_ref,
                "lane": lane,
                "dispatch_refs": dispatch_refs,
                "intent": "run independent bounded tasks in parallel",
                "max_active": max_active,
                "review_artifact_path": f".agent/reviews/{parallel_set_ref}/pre_dispatch_review.json",
                "created_at": "2026-04-10T10:00:00Z",
            },
        )
        return set_path

    def _assert_executor_readout(self, repo_root: Path, dispatch_dir: Path, model: dict) -> Path:
        request_payload = load_json(dispatch_dir / "request.json")
        state_payload = load_json(dispatch_dir / "state.json")
        agent_root = next(parent.parent for parent in dispatch_dir.parents if parent.name == "dispatches")
        run_dir = agent_root / "runs" / state_payload["run_ref"]
        report_payload = load_json(run_dir / "report.json")
        readout_refs = [
            output
            for output in report_payload["outputs"]
            if isinstance(output, str) and output.endswith("executor_readout.md")
        ]
        self.assertEqual(len(readout_refs), 1)
        readout_path = repo_root / readout_refs[0]
        self.assertTrue(readout_path.exists())
        self.assertIn("## Architecture Boundaries", readout_path.read_text(encoding="utf-8"))
        self.assertEqual(request_payload["execution_mode"], "command_chain")
        self.assertIn("artifact_only_executor_readout", request_payload["execution_payload"]["notes"])
        executor_items = [
            item for item in model["feed"] if item.get("title") == "Executor completed"
        ]
        self.assertTrue(executor_items)
        executor_item = executor_items[-1]
        self.assertEqual(executor_item["source_artifact_ref"], readout_refs[0])
        self.assertIn("## Architecture Boundaries", executor_item["body"])
        self.assertIn("## Execution Readiness", executor_item["body"])
        return readout_path

    def _assert_reviewer_readout(self, repo_root: Path, dispatch_dir: Path, model: dict) -> Path:
        request_payload = load_json(dispatch_dir / "request.json")
        review_ref = request_payload["review_artifact_path"]
        review_path = repo_root / review_ref
        self.assertTrue(review_path.exists())
        review_payload = load_json(review_path)
        self.assertEqual(review_payload["dispatch_ref"], request_payload["dispatch_ref"])
        self.assertIn(review_payload["verdict"], {"pass", "request_changes", "inconclusive"})
        reviewer_items = [
            item for item in model["feed"] if item.get("title") == "Reviewer completed"
        ]
        self.assertTrue(reviewer_items)
        reviewer_item = reviewer_items[-1]
        self.assertEqual(reviewer_item["source_artifact_ref"], review_ref)
        self.assertIn("# Reviewer Readout", reviewer_item["body"])
        self.assertIn("Verdict:", reviewer_item["body"])
        return review_path

    def _assert_governor_decision(self, repo_root: Path, dispatch_dir: Path, model: dict) -> Path:
        decision_path = dispatch_dir / "governor_decision.json"
        self.assertTrue(decision_path.exists())
        decision_payload = load_json(decision_path)
        self.assertEqual(decision_payload["dispatch_ref"], load_json(dispatch_dir / "request.json")["dispatch_ref"])
        self.assertIn(decision_payload["decision"], {"accept", "reject", "needs_review", "needs_verification"})
        decision_ref = str(decision_path.relative_to(repo_root))
        decision_items = [
            item for item in model["feed"] if item.get("title") == "Governor decision recorded"
        ]
        self.assertTrue(decision_items)
        decision_item = decision_items[-1]
        self.assertEqual(decision_item["source_artifact_ref"], decision_ref)
        self.assertEqual(decision_item["source_actor"], "governor")
        self.assertIn("# Governor Decision", decision_item["body"])
        return decision_path

    def _write_artifact_only_finalize_fixture(
        self,
        repo_root: Path,
        *,
        command_ref: str | None = None,
        output_ref: str | None = None,
    ) -> Path:
        (repo_root / ".git").mkdir(exist_ok=True)
        dispatch_ref = "lane/test/dispatch-artifact"
        run_ref = f"{dispatch_ref}/result/attempt-1"
        output_ref = output_ref or f".agent/runs/{run_ref}/executor_readout.md"
        command_ref = command_ref or script_ref("executor_write_readout.py", repo_root)
        dispatch_dir = repo_root / ".agent" / "dispatches" / dispatch_ref
        write_json(
            dispatch_dir / "request.json",
            {
                "dispatch_ref": dispatch_ref,
                "execution_mode": "command_chain",
                "execution_payload": {
                    "notes": ["artifact_only_executor_readout"],
                    "commands": [{"argv": [sys.executable, command_ref]}],
                },
                "required_outputs": [output_ref],
                "executor_run": {"run_ref": run_ref},
                "review_required": False,
            },
        )
        write_json(
            dispatch_dir / "result.json",
            {
                "dispatch_ref": dispatch_ref,
                "status": "completed",
                "blocker": None,
                "summary": "Executor artifact-only readout completed.",
                "executor_run_refs": [run_ref],
                "written_or_updated": [output_ref],
                "runtime_behavior_changed": False,
                "scope_respected": True,
            },
        )
        write_json(dispatch_dir / "state.json", {"status": "completed", "run_ref": run_ref})
        (repo_root / output_ref).parent.mkdir(parents=True, exist_ok=True)
        (repo_root / output_ref).write_text("# Executor Readout\n", encoding="utf-8")
        return dispatch_dir

    def test_post_execution_actor_stage_uses_structured_result(self) -> None:
        actor, stage = session._post_execution_actor_stage(
            {"ok": True, "actor": "executor", "stage": "executor_completed", "title": "Copy changed"},
            {"ok": True, "actor": "reviewer", "stage": "reviewer_completed", "title": "Copy changed again"},
            {
                "ok": True,
                "actor": "governor",
                "stage": "governor_decision_recorded",
                "title": "Localized title",
            },
        )

        self.assertEqual(actor, "governor")
        self.assertEqual(stage, "governor_decision_recorded")

    def test_finalize_allows_verified_artifact_only_executor_readout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            dispatch_dir = self._write_artifact_only_finalize_fixture(repo_root)

            with mock.patch.object(dispatch, "ensure_lane_worktree_tracked") as guard:
                self.assertEqual(dispatch.finalize_main(["--dispatch-dir", str(dispatch_dir)]), 0)

            guard.assert_not_called()
            self.assertTrue((dispatch_dir / "governor_decision.json").exists())

    def test_artifact_only_readout_guard_is_shared_by_finalizer_and_executor_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            dispatch_dir = self._write_artifact_only_finalize_fixture(repo_root)
            request_payload = load_json(dispatch_dir / "request.json")
            result_payload = load_json(dispatch_dir / "result.json")
            state_payload = load_json(dispatch_dir / "state.json")
            run_dir = repo_root / ".agent" / "runs" / state_payload["run_ref"]

            self.assertTrue(
                dispatch_guards.artifact_only_executor_readout_request(
                    repo_root,
                    request_payload,
                    result=result_payload,
                    state=state_payload,
                )
            )
            self.assertTrue(
                executor_runtime.is_artifact_only_executor_readout(
                    repo_root,
                    request_payload,
                    run_dir,
                    result_payload["written_or_updated"],
                )
            )

    def test_finalize_rejects_mistagged_artifact_only_executor_readout_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            dispatch_dir = self._write_artifact_only_finalize_fixture(
                repo_root,
                command_ref="orchestration/scripts/not_the_readout_helper.py",
            )

            with mock.patch.object(dispatch, "ensure_lane_worktree_tracked") as guard:
                self.assertEqual(dispatch.finalize_main(["--dispatch-dir", str(dispatch_dir)]), 0)

            guard.assert_called_once()
            self.assertTrue((dispatch_dir / "governor_decision.json").exists())

    def test_finalize_rejects_artifact_only_readout_outputs_outside_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            dispatch_dir = self._write_artifact_only_finalize_fixture(
                repo_root,
                output_ref=".agent/dispatches/lane/test/dispatch-artifact/executor_readout.md",
            )

            with mock.patch.object(dispatch, "ensure_lane_worktree_tracked") as guard:
                self.assertEqual(dispatch.finalize_main(["--dispatch-dir", str(dispatch_dir)]), 0)

            guard.assert_called_once()
            self.assertTrue((dispatch_dir / "governor_decision.json").exists())

    def test_configured_agent_root_is_used_by_runtime_path_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            runtime_agent_root = repo_root / ".agent-runtime"
            with mock.patch.dict(
                os.environ,
                {"ORCHESTRATION_AGENT_ROOT": str(runtime_agent_root)},
            ):
                dispatch_ref = "lane/main/dispatch-test"
                run_ref = "cycle/scope/ref/result/attempt"
                self.assertEqual(
                    dispatch.dispatch_dir_for_ref(repo_root, dispatch_ref),
                    runtime_agent_root / "dispatches" / Path(dispatch_ref),
                )
                self.assertEqual(
                    start_guard.dispatch_dir_for_ref(repo_root, dispatch_ref),
                    runtime_agent_root / "dispatches" / Path(dispatch_ref),
                )
                self.assertEqual(
                    spawn_bridge.dispatch_dir_for_ref(repo_root, dispatch_ref),
                    runtime_agent_root / "dispatches" / Path(dispatch_ref),
                )
                self.assertEqual(
                    executor_runtime.dispatch_dir_for_ref(repo_root, dispatch_ref),
                    runtime_agent_root / "dispatches" / Path(dispatch_ref),
                )
                self.assertEqual(
                    executor_runtime.run_dir_for_ref(repo_root, run_ref),
                    runtime_agent_root / "runs" / Path(run_ref),
                )
                self.assertEqual(
                    dispatch_contracts.run_dir_for_ref(repo_root, run_ref),
                    runtime_agent_root / "runs" / Path(run_ref),
                )
                self.assertEqual(
                    transition.governor_state_dir(repo_root, "lane/main"),
                    runtime_agent_root / "governor" / "lane/main",
                )
                review_path = reviewer.resolve_review_artifact_path(
                    repo_root,
                    dispatch_ref,
                    ".agent-runtime/reviews/lane/main/dispatch-test/review.json",
                )
                self.assertEqual(
                    review_path,
                    runtime_agent_root / "reviews" / Path(dispatch_ref) / "review.json",
                )

    def test_source_root_can_differ_from_target_repo_root_for_scratch_workspace(self) -> None:
        source_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            target_root = Path(tmp_dir).resolve()
            with mock.patch.dict(
                os.environ,
                {
                    "ORCHESTRATION_REPO_ROOT": str(target_root),
                    "ORCHESTRATION_SOURCE_ROOT": str(source_root),
                },
            ):
                paths = resolve_paths(target_root)

                self.assertEqual(paths.repo_root, target_root)
                self.assertEqual(paths.source_root, source_root)
                self.assertEqual(paths.orchestration_root, source_root / "orchestration")
                self.assertEqual(paths.agent_root, target_root / ".agent")
                self.assertTrue(Path(script_ref("orchestrate.py", target_root)).is_absolute())
                self.assertIn("orchestration/scripts/orchestrate.py", script_ref("orchestrate.py", target_root))
                self.assertIn("orchestration/prompts/governor.txt", prompt_ref("governor.txt", target_root))

    def test_static_pet_diary_executor_requires_explicit_scratch_test_metadata(self) -> None:
        objective = "Build a simple static pet life diary app from scratch."
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                session_execution.is_pet_diary_static_test_dispatch(
                    objective,
                    ".agent/intakes/20260507-pet-life-diary-static/accepted_intake.json",
                )
            )

        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATION_TARGET_WORKSPACE_MODE": "scratch",
                "ORCHESTRATION_TEST_PROMPT_PRESET": "pet-life-diary-static",
            },
            clear=True,
        ):
            self.assertTrue(
                session_execution.is_pet_diary_static_test_dispatch(
                    objective,
                    ".agent/intakes/20260507-pet-life-diary-static/accepted_intake.json",
                )
            )

    def test_static_pet_diary_dispatch_requires_authorship_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            paths = resolve_paths(repo_root)
            args: list[str] = []

            session_execution.extend_static_pet_diary_dispatch_args(
                args,
                paths,
                dispatch_ref="lane/intake/dispatch-001",
                objective="Build a simple static pet life diary app from scratch.",
                accepted_ref=".agent/intakes/pet/accepted_intake.json",
            )

            self.assertIn("--authorship-evidence-required", args)
            for output_ref in session_execution.PET_DIARY_OUTPUTS:
                self.assertIn(output_ref, args)

    def test_pet_diary_bugfix_executor_requires_explicit_scratch_test_metadata(self) -> None:
        objective = "Fix the pet diary app so adding a diary entry updates the visible list."
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                session_execution.is_pet_diary_bugfix_test_dispatch(
                    objective,
                    ".agent/intakes/20260510-pet-life-diary-bugfix/accepted_intake.json",
                )
            )

        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATION_TARGET_WORKSPACE_MODE": "scratch",
                "ORCHESTRATION_TEST_PROMPT_PRESET": "pet-life-diary-bugfix",
            },
            clear=True,
        ):
            self.assertTrue(
                session_execution.is_pet_diary_bugfix_test_dispatch(
                    objective,
                    ".agent/intakes/20260510-pet-life-diary-bugfix/accepted_intake.json",
                )
            )

    def test_pet_diary_bugfix_dispatch_requires_mutation_authorship_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            paths = resolve_paths(repo_root)
            args: list[str] = []

            session_execution.extend_pet_diary_bugfix_dispatch_args(
                args,
                paths,
                dispatch_ref="lane/intake/dispatch-001",
                objective="Fix the pet diary app so adding a diary entry updates the visible list.",
            )

            self.assertIn("--authorship-evidence-required", args)
            for output_ref in session_execution.PET_DIARY_BUGFIX_OUTPUTS:
                self.assertIn(output_ref, args)
            self.assertIn("--validator-command", args)
            self.assertIn("executor_propose_patch_spec.py", " ".join(args))
            self.assertIn("executor_apply_patch_spec.py", " ".join(args))
            self.assertNotIn("executor_fix_pet_diary_entry.py", " ".join(args))
            self.assertIn("validate_pet_diary_entry.py", " ".join(args))
            patch_spec_path = (
                paths.agent_root
                / "patch_specs"
                / "lane"
                / "intake"
                / "dispatch-001"
                / "pet_diary_entry_fix.json"
            )
            self.assertFalse(patch_spec_path.exists())

    def test_pet_diary_filter_executor_requires_explicit_scratch_test_metadata(self) -> None:
        objective = "Add a simple species filter to the existing pet diary app."
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                session_execution.is_pet_diary_filter_test_dispatch(
                    objective,
                    ".agent/intakes/20260511-pet-life-diary-filter/accepted_intake.json",
                )
            )

        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATION_TARGET_WORKSPACE_MODE": "scratch",
                "ORCHESTRATION_TEST_PROMPT_PRESET": "pet-life-diary-filter",
            },
            clear=True,
        ):
            self.assertTrue(
                session_execution.is_pet_diary_filter_test_dispatch(
                    objective,
                    ".agent/intakes/20260511-pet-life-diary-filter/accepted_intake.json",
                )
            )

    def test_pet_diary_filter_dispatch_requires_mutation_authorship_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            paths = resolve_paths(repo_root)
            args: list[str] = []

            session_execution.extend_pet_diary_filter_dispatch_args(
                args,
                paths,
                dispatch_ref="lane/intake/dispatch-001",
                objective="Add a simple species filter to the existing pet diary app.",
            )

            args_text = " ".join(args)
            self.assertIn("--authorship-evidence-required", args)
            for output_ref in session_execution.PET_DIARY_FILTER_OUTPUTS:
                self.assertIn(output_ref, args)
            self.assertIn("--validator-command", args)
            self.assertIn("executor_propose_patch_spec.py", args_text)
            self.assertIn("executor_apply_patch_spec.py", args_text)
            self.assertIn("validate_pet_diary_filter.py", args_text)
            self.assertIn("pet_diary_species_filter", args_text)
            self.assertIn("pet_diary_species_filter-index-html.patch", args_text)
            self.assertIn("pet_diary_species_filter-src-app-js.patch", args_text)
            self.assertIn("scratch_pet_diary_filter_feature", args)
            patch_spec_path = (
                paths.agent_root
                / "patch_specs"
                / "lane"
                / "intake"
                / "dispatch-001"
                / "pet_diary_species_filter.json"
            )
            self.assertFalse(patch_spec_path.exists())

    def test_pet_diary_filter_retry_requires_explicit_scratch_test_metadata(self) -> None:
        objective = "Add a simple species filter to the existing pet diary app."
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                session_execution.is_pet_diary_filter_retry_test_dispatch(
                    objective,
                    ".agent/intakes/20260511-pet-life-diary-filter-review-retry/accepted_intake.json",
                )
            )

        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATION_TARGET_WORKSPACE_MODE": "scratch",
                "ORCHESTRATION_TEST_PROMPT_PRESET": "pet-life-diary-filter-review-retry",
            },
            clear=True,
        ):
            self.assertTrue(
                session_execution.is_pet_diary_filter_retry_test_dispatch(
                    objective,
                    ".agent/intakes/20260511-pet-life-diary-filter-review-retry/accepted_intake.json",
                )
            )

    def test_pet_diary_filter_retry_first_attempt_uses_partial_patch_without_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            paths = resolve_paths(repo_root)
            args: list[str] = []

            session_execution.extend_pet_diary_filter_retry_dispatch_args(
                args,
                paths,
                dispatch_ref="lane/intake/dispatch-001",
                objective="Add a simple species filter to the existing pet diary app.",
                attempt_number=1,
            )

            args_text = " ".join(args)
            self.assertIn("--authorship-evidence-required", args)
            self.assertIn("index.html", args)
            self.assertIn("src/app.js", args)
            self.assertIn("pet_diary_species_filter_partial", args_text)
            self.assertIn("pet_diary_species_filter_partial-index-html.patch", args_text)
            self.assertIn("pet_diary_species_filter_partial-src-app-js.patch", args_text)
            self.assertIn("scratch_pet_diary_filter_review_retry", args)
            self.assertNotIn("--validator-command", args)
            self.assertNotIn("validate_pet_diary_filter.py", args_text)

    def test_pet_diary_filter_retry_helper_review_requests_changes_for_partial_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            (repo_root / "src").mkdir(parents=True)
            (repo_root / "index.html").write_text(
                '<form id="diary-form"><select id="species-filter"></select></form>',
                encoding="utf-8",
            )
            (repo_root / "src" / "app.js").write_text(
                '\n'.join(
                    [
                        'const speciesFilter = document.querySelector("#species-filter");',
                        "const diaryEntries = [];",
                        "function renderEntries() {",
                        "\tfor (const entry of diaryEntries) {",
                        "\t\tconsole.log(entry);",
                        "\t}",
                        "}",
                    ]
                ),
                encoding="utf-8",
            )
            request = {
                "dispatch_ref": "lane/intake/dispatch-001",
                "attempt_number": 1,
                "task_track": "patch",
            }
            result = {
                "status": "completed",
                "scope_respected": True,
                "written_or_updated": ["index.html", "src/app.js"],
                "auto_validated": [],
            }

            with mock.patch.dict(
                os.environ,
                {
                    "ORCHESTRATION_TARGET_WORKSPACE_MODE": "scratch",
                    "ORCHESTRATION_TEST_PROMPT_PRESET": "pet-life-diary-filter-review-retry",
                },
                clear=True,
            ):
                review = dispatch.build_helper_review(repo_root, request, result)

            self.assertEqual(review["verdict"], "request_changes")
            self.assertEqual(review["recommendation"], "redispatch_or_reject")
            self.assertTrue(any("visibleEntries" in finding for finding in review["findings"]))
            self.assertIn("pet_diary_filter_retry=partial_filter_detected", review["validator_assessment"])

    def test_pet_diary_filter_retry_second_attempt_uses_completion_patch_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            paths = resolve_paths(repo_root)
            args: list[str] = []

            session_execution.extend_pet_diary_filter_retry_dispatch_args(
                args,
                paths,
                dispatch_ref="lane/intake/dispatch-002",
                objective="Add a simple species filter to the existing pet diary app.",
                attempt_number=2,
            )

            args_text = " ".join(args)
            self.assertIn("--authorship-evidence-required", args)
            self.assertIn("src/app.js", args)
            self.assertIn("index.html", args)
            self.assertEqual(args.count("--required-output"), 1)
            self.assertIn("pet_diary_species_filter_complete", args_text)
            self.assertIn("pet_diary_species_filter_complete.patch", args_text)
            self.assertIn("--validator-command", args)
            self.assertIn("validate_pet_diary_filter.py", args_text)
            self.assertIn("pet_diary_species_filter.json", args_text)

    def test_patch_spec_proposer_writes_executor_proposal_artifact(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            app_path = scratch_root / "src" / "app.js"
            app_path.parent.mkdir(parents=True, exist_ok=True)
            app_path.write_text(
                '\n'.join(
                    [
                        "const diaryEntries = [];",
                        'const form = document.querySelector("#diary-form");',
                        'const input = document.querySelector("#diary-entry-input");',
                        "function renderEntries() {}",
                        'form?.addEventListener("submit", (event) => {',
                        "\tevent.preventDefault();",
                        "\tconst text = input.value.trim();",
                        "\tif (!text) {",
                        "\t\treturn;",
                        "\t}",
                        '\tinput.value = "";',
                        "\trenderEntries();",
                        "});",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self._write_pet_diary_patch_request(scratch_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_propose_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--objective",
                    "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "--recipe",
                    "pet_diary_entry_submit",
                    "--spec",
                    ".agent/patch_specs/lane/intake/dispatch-001/pet_diary_entry_fix.json",
                    "--patch-artifact",
                    ".agent/patches/lane/intake/dispatch-001/src-app-js.patch",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            patch_spec_path = (
                scratch_root
                / ".agent"
                / "patch_specs"
                / "lane"
                / "intake"
                / "dispatch-001"
                / "pet_diary_entry_fix.json"
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(patch_spec_path.exists())
            patch_spec = load_json(patch_spec_path)
            self.assertEqual(patch_spec["schema_version"], "corgi.patch-spec.v1")
            self.assertEqual(patch_spec["dispatch_ref"], "lane/intake/dispatch-001")
            self.assertEqual(patch_spec["proposed_by"], "executor")
            self.assertEqual(patch_spec["operations"][0]["path"], "src/app.js")

    def test_patch_spec_executor_writes_patch_artifact(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            app_path = scratch_root / "src" / "app.js"
            app_path.parent.mkdir(parents=True, exist_ok=True)
            app_path.write_text(
                '\n'.join(
                    [
                        "const diaryEntries = [];",
                        'const form = document.querySelector("#diary-form");',
                        'const input = document.querySelector("#diary-entry-input");',
                        "function renderEntries() {}",
                        'form?.addEventListener("submit", (event) => {',
                        "\tevent.preventDefault();",
                        "\tconst text = input.value.trim();",
                        "\tif (!text) {",
                        "\t\treturn;",
                        "\t}",
                        '\tinput.value = "";',
                        "\trenderEntries();",
                        "});",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self._write_pet_diary_patch_request(scratch_root)
            spec_result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_propose_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--objective",
                    "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "--recipe",
                    "pet_diary_entry_submit",
                    "--spec",
                    ".agent/patch_specs/lane/intake/dispatch-001/pet_diary_entry_fix.json",
                    "--patch-artifact",
                    ".agent/patches/lane/intake/dispatch-001/src-app-js.patch",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_apply_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--spec",
                    ".agent/patch_specs/lane/intake/dispatch-001/pet_diary_entry_fix.json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            patch_path = (
                scratch_root
                / ".agent"
                / "patches"
                / "lane"
                / "intake"
                / "dispatch-001"
                / "src-app-js.patch"
            )

            self.assertEqual(spec_result.returncode, 0, spec_result.stderr)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("diaryEntries.push", app_path.read_text(encoding="utf-8"))
            self.assertTrue(patch_path.exists())
            patch_source = patch_path.read_text(encoding="utf-8")
            self.assertIn("--- a/src/app.js", patch_source)
            self.assertIn("+++ b/src/app.js", patch_source)
            self.assertIn("+\tdiaryEntries.push({", patch_source)

    def test_patch_spec_executor_rejects_already_fixed_app(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            app_path = scratch_root / "src" / "app.js"
            app_path.parent.mkdir(parents=True, exist_ok=True)
            app_path.write_text(
                '\n'.join(
                    [
                        "const diaryEntries = [];",
                        'const form = document.querySelector("#diary-form");',
                        'const input = document.querySelector("#diary-entry-input");',
                        "function renderEntries() {}",
                        'form?.addEventListener("submit", (event) => {',
                        "\tevent.preventDefault();",
                        "\tconst text = input.value.trim();",
                        "\tif (!text) {",
                        "\t\treturn;",
                        "\t}",
                        "\tdiaryEntries.push({",
                        "\t\ttext,",
                        '\t\tcreatedAt: "Just now",',
                        "\t});",
                        '\tinput.value = "";',
                        "\trenderEntries();",
                        "});",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self._write_pet_diary_patch_request(scratch_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_propose_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--objective",
                    "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "--recipe",
                    "pet_diary_entry_submit",
                    "--spec",
                    ".agent/patch_specs/lane/intake/dispatch-001/pet_diary_entry_fix.json",
                    "--patch-artifact",
                    ".agent/patches/lane/intake/dispatch-001/src-app-js.patch",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already appends diary entries", result.stderr)

    def test_patch_spec_proposer_rejects_undeclared_target(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            self._write_minimal_buggy_pet_diary_app(scratch_root)
            self._write_pet_diary_patch_request(
                scratch_root,
                required_outputs=["README.md"],
                planned_touches=["README.md"],
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_propose_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--objective",
                    "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "--recipe",
                    "pet_diary_entry_submit",
                    "--spec",
                    ".agent/patch_specs/lane/intake/dispatch-001/pet_diary_entry_fix.json",
                    "--patch-artifact",
                    ".agent/patches/lane/intake/dispatch-001/src-app-js.patch",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not declared by dispatch", result.stderr)

    def test_patch_spec_proposer_rejects_unsafe_dispatch_ref(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            self._write_minimal_buggy_pet_diary_app(scratch_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_propose_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "../outside-dispatch",
                    "--objective",
                    "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "--recipe",
                    "pet_diary_entry_submit",
                    "--spec",
                    ".agent/patch_specs/outside-dispatch/pet_diary_entry_fix.json",
                    "--patch-artifact",
                    ".agent/patches/outside-dispatch/src-app-js.patch",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("dispatch_ref must not contain", result.stderr)

    def test_patch_spec_proposer_rejects_spec_outside_patch_spec_family(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            self._write_minimal_buggy_pet_diary_app(scratch_root)
            self._write_pet_diary_patch_request(scratch_root)

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_propose_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--objective",
                    "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "--recipe",
                    "pet_diary_entry_submit",
                    "--spec",
                    "src/app.js",
                    "--patch-artifact",
                    ".agent/patches/lane/intake/dispatch-001/src-app-js.patch",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("patch spec must live under", result.stderr)

    def test_patch_spec_apply_rejects_stale_proposal(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            app_path = self._write_minimal_buggy_pet_diary_app(scratch_root)
            self._write_pet_diary_patch_request(scratch_root)
            propose = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_propose_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--objective",
                    "Fix the pet diary app so adding a diary entry updates the visible list.",
                    "--recipe",
                    "pet_diary_entry_submit",
                    "--spec",
                    ".agent/patch_specs/lane/intake/dispatch-001/pet_diary_entry_fix.json",
                    "--patch-artifact",
                    ".agent/patches/lane/intake/dispatch-001/src-app-js.patch",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            app_path.write_text(app_path.read_text(encoding="utf-8") + "\n// unrelated drift\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_apply_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--spec",
                    ".agent/patch_specs/lane/intake/dispatch-001/pet_diary_entry_fix.json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(propose.returncode, 0, propose.stderr)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("is stale", result.stderr)

    def test_patch_spec_apply_rejects_malformed_noop_and_path_escape(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            app_path = self._write_minimal_buggy_pet_diary_app(scratch_root)
            self._write_pet_diary_patch_request(scratch_root)
            signature = patch_specs.file_signature(app_path)
            spec_ref = ".agent/patch_specs/lane/intake/dispatch-001/bad.json"
            spec_path = scratch_root / spec_ref
            write_json(
                spec_path,
                {
                    "schema_version": "corgi.patch-spec.v1",
                    "dispatch_ref": "lane/intake/dispatch-001",
                    "proposed_by": "executor",
                    "operations": [
                        {
                            "path": "src/app.js",
                            "old_text": "function renderEntries() {}",
                            "new_text": "function renderEntries() {}",
                            "expected_replacements": 1,
                            "patch_artifact": ".agent/patches/lane/intake/dispatch-001/bad.patch",
                            "before_sha256": signature["sha256"],
                            "before_size": signature["size"],
                        }
                    ],
                },
            )
            noop = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_apply_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--spec",
                    spec_ref,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            payload = load_json(spec_path)
            payload["operations"][0]["path"] = "../outside.js"
            payload["operations"][0]["new_text"] = "function renderEntries() { return true; }"
            write_json(spec_path, payload)
            escaping = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_apply_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--spec",
                    spec_ref,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(noop.returncode, 0)
            self.assertIn("no-op", noop.stderr)
            self.assertNotEqual(escaping.returncode, 0)
            self.assertIn("escapes repo root", escaping.stderr)

    def test_patch_spec_apply_rejects_spec_outside_patch_spec_family(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            self._write_minimal_buggy_pet_diary_app(scratch_root)
            self._write_pet_diary_patch_request(scratch_root)
            spec_ref = "bad_patch_spec.json"
            write_json(
                scratch_root / spec_ref,
                {
                    "schema_version": "corgi.patch-spec.v1",
                    "dispatch_ref": "lane/intake/dispatch-001",
                    "proposed_by": "executor",
                    "operations": [],
                },
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_apply_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--spec",
                    spec_ref,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("patch spec must live under", result.stderr)

    def test_patch_spec_apply_rejects_non_executor_and_bad_patch_artifact(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            app_path = self._write_minimal_buggy_pet_diary_app(scratch_root)
            self._write_pet_diary_patch_request(scratch_root)
            signature = patch_specs.file_signature(app_path)
            spec_ref = ".agent/patch_specs/lane/intake/dispatch-001/bad_authority.json"
            spec_path = scratch_root / spec_ref
            payload = {
                "schema_version": "corgi.patch-spec.v1",
                "dispatch_ref": "lane/intake/dispatch-001",
                "proposed_by": "governor",
                "operations": [
                    {
                        "path": "src/app.js",
                        "old_text": "function renderEntries() {}",
                        "new_text": "function renderEntries() { return true; }",
                        "expected_replacements": 1,
                        "patch_artifact": ".agent/patches/lane/intake/dispatch-001/bad.patch",
                        "before_sha256": signature["sha256"],
                        "before_size": signature["size"],
                    }
                ],
            }
            write_json(spec_path, payload)
            non_executor = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_apply_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--spec",
                    spec_ref,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            payload["proposed_by"] = "executor"
            payload["operations"][0]["patch_artifact"] = ".agent/patches/other-dispatch/bad.patch"
            write_json(spec_path, payload)
            bad_artifact = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "executor_apply_patch_spec.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--dispatch-ref",
                    "lane/intake/dispatch-001",
                    "--spec",
                    spec_ref,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(non_executor.returncode, 0)
            self.assertIn("proposed_by must be executor", non_executor.stderr)
            self.assertNotEqual(bad_artifact.returncode, 0)
            self.assertIn("patch_artifact must live under", bad_artifact.stderr)

    def test_pet_diary_validation_requires_append_inside_submit_handler(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as tmp_dir:
            scratch_root = Path(tmp_dir).resolve()
            (scratch_root / "src").mkdir(parents=True, exist_ok=True)
            (scratch_root / "index.html").write_text(
                '<form id="diary-form"><input id="diary-entry-input" /></form>\n',
                encoding="utf-8",
            )
            (scratch_root / "src" / "app.js").write_text(
                '\n'.join(
                    [
                        "const diaryEntries = [];",
                        "diaryEntries.push({ text: 'dead code', createdAt: 'Never' });",
                        'const form = document.querySelector("#diary-form");',
                        "function renderEntries() {}",
                        'form?.addEventListener("submit", (event) => {',
                        "\tevent.preventDefault();",
                        "\trenderEntries();",
                        "});",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            report_ref = ".agent/validations/lane/intake/dispatch-001/pet_diary_entry_fix.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "orchestration" / "scripts" / "validate_pet_diary_entry.py"),
                    "--repo-root",
                    str(scratch_root),
                    "--report",
                    report_ref,
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            report = load_json(scratch_root / report_ref)

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report["status"], "fail")
            self.assertFalse(report["checks"]["appends_entry_in_submit_handler"])

    def test_advisory_mcp_runtime_config_uses_repo_entrypoint(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        config_source = (repo_root / "orchestration" / "runtime" / "config.toml").read_text(
            encoding="utf-8"
        )

        self.assertIn("[mcp_servers.orchestration_advisory]", config_source)
        self.assertIn('command = "python3"', config_source)
        self.assertIn('args = ["mcp_server.py"]', config_source)
        self.assertNotIn(
            'args = ["orchestration/runtime/advisory/mcp_server.py"]',
            config_source,
        )

    def test_advisory_mcp_entrypoints_handle_python_environment(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        root_entrypoint = (repo_root / "mcp_server.py").read_text(encoding="utf-8")
        dev_entrypoint = (repo_root / "dev_mcp_server.py").read_text(encoding="utf-8")
        launcher_source = (
            repo_root / "orchestration" / "scripts" / "serve_advisory_mcp.py"
        ).read_text(encoding="utf-8")
        dev_launcher_source = (
            repo_root / "orchestration" / "scripts" / "serve_development_consulting_mcp.py"
        ).read_text(encoding="utf-8")
        setup_source = (
            repo_root / "orchestration" / "scripts" / "setup_advisory_mcp_env.py"
        ).read_text(encoding="utf-8")
        requirements_source = (
            repo_root / "orchestration" / "runtime" / "advisory" / "requirements.txt"
        ).read_text(encoding="utf-8")

        self.assertIn("serve_advisory_mcp.py", root_entrypoint)
        self.assertIn('os.environ["CORGI_ADVISORY_CONTEXT"] = "corgi-governor-runtime"', root_entrypoint)
        self.assertIn("serve_development_consulting_mcp.py", dev_entrypoint)
        self.assertIn("CORGI_ADVISORY_LAUNCH_PROFILE", dev_launcher_source)
        self.assertIn("corgi-development-consulting", dev_launcher_source)
        self.assertIn("CORGI_ADVISORY_CALLER_ROLE", dev_launcher_source)
        self.assertIn(".agent\" / \"development\" / \"advisory", dev_launcher_source)
        self.assertIn("MINIMAX_API_KEY_FILE", dev_launcher_source)
        self.assertIn("minimax_api_key", dev_launcher_source)
        for token in [
            "ORCHESTRATION_APPROVED_PYTHON",
            "CORGI_ADVISORY_MCP_PYTHON",
            "CORGI_PYTHON",
            "/opt/homebrew/bin/python3",
            "PYTHONPATH",
            "ORCHESTRATION_REPO_ROOT",
            "ORCHESTRATION_SOURCE_ROOT",
            "CORGI_ADVISORY_CONTEXT",
            "corgi-governor-runtime",
            "CORGI_ADVISORY_STATE_DIR",
            "requirements.txt",
            "runtime\" / \"advisory\" / \"mcp_server.py",
        ]:
            self.assertIn(token, launcher_source)
        self.assertIn("/opt/homebrew/bin/python3", setup_source)
        self.assertIn(".venv", setup_source)
        self.assertIn("requirements.txt", setup_source)
        self.assertIn("anthropic", requirements_source)
        self.assertIn("mcp", requirements_source)

    def test_advisory_mcp_runtime_and_development_surfaces_are_separate(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        config_source = (repo_root / "orchestration" / "runtime" / "config.toml").read_text(
            encoding="utf-8"
        )
        server_source = (
            repo_root / "orchestration" / "runtime" / "advisory" / "mcp_server.py"
        ).read_text(encoding="utf-8")
        advisory_doc = (repo_root / "orchestration" / "advisory.md").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("dev_mcp_server.py", config_source)
        self.assertIn("CORGI_RUNTIME_CONTEXT", server_source)
        self.assertIn("corgi-governor-runtime", server_source)
        self.assertIn("corgi-development-consulting", server_source)
        self.assertIn("Corgi_Governor_Advisor", server_source)
        self.assertIn("Corgi_Development_Consulting", server_source)
        self.assertIn("_authorize_tool_call", server_source)
        self.assertIn("ADVISORY_CALLER_ROLE != \"governor\"", server_source)
        self.assertIn("_runtime_prompt_boundary_error", server_source)
        self.assertIn("_resolve_context_path", server_source)
        self.assertIn("Runtime advisor file access is target-workspace scoped", advisory_doc)
        self.assertIn("for building Corgi itself", advisory_doc)

    def test_cli_advisory_serve_routes_through_launcher(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        cli_source = (repo_root / "orchestration" / "harness" / "cli.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("serve_advisory_mcp.py", cli_source)
        self.assertIn("ORCHESTRATION_REPO_ROOT", cli_source)
        self.assertIn("ORCHESTRATION_SOURCE_ROOT", cli_source)
        self.assertIn("CORGI_ADVISORY_CONTEXT", cli_source)
        self.assertIn("corgi-governor-runtime", cli_source)
        self.assertIn("PYTHONPATH", cli_source)
        self.assertNotIn('runtime_root / "advisory" / "mcp_server.py"', cli_source)

    def test_advisory_mcp_tools_have_matching_governor_skills(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        server_source = (
            repo_root / "orchestration" / "runtime" / "advisory" / "mcp_server.py"
        ).read_text(encoding="utf-8")
        skills_root = repo_root / "orchestration" / "skills"
        tool_skill_map = {
            "consult_claude_headless": "claude-headless",
            "consult_architect": "consult-architect",
            "routine_code_review": "routine-code-review",
            "consult_minimax": "minimax-advisor",
        }
        routing_source = (skills_root / "routing" / "SKILL.md").read_text(
            encoding="utf-8"
        )

        for tool_name, skill_name in tool_skill_map.items():
            with self.subTest(tool_name=tool_name):
                self.assertIn(f"async def {tool_name}(", server_source)
                skill_source = (skills_root / skill_name / "SKILL.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Use this only in Governor context.", skill_source)
                self.assertIn(tool_name, skill_source)
                self.assertIn(tool_name, routing_source)

        self.assertNotIn("consult_grok_advisor", server_source)
        self.assertNotIn("consult_grok_advisor", routing_source)

    def test_claude_headless_uses_opus_with_sonnet_annotation(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        server_source = (
            repo_root / "orchestration" / "runtime" / "advisory" / "mcp_server.py"
        ).read_text(encoding="utf-8")
        skill_source = (
            repo_root / "orchestration" / "skills" / "claude-headless" / "SKILL.md"
        ).read_text(encoding="utf-8")
        advisory_doc = (repo_root / "orchestration" / "advisory.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("CLAUDE_HEADLESS_MODEL", server_source)
        self.assertIn("claude-opus-4-7", server_source)
        self.assertIn("--model", server_source)
        self.assertIn("CLAUDE_HEADLESS_PREVIOUS_MODEL_ANNOTATION", server_source)
        self.assertIn("claude-sonnet-4-6", server_source)
        self.assertIn("Opus 4.7", skill_source)
        self.assertIn("Sonnet 4.6", skill_source)
        self.assertIn("Opus 4.7", advisory_doc)
        self.assertIn("Sonnet 4.6", advisory_doc)

    def test_minimax_advisor_prefers_direct_openai_compatible_api(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        server_source = (
            repo_root / "orchestration" / "runtime" / "advisory" / "mcp_server.py"
        ).read_text(encoding="utf-8")
        skill_source = (
            repo_root / "orchestration" / "skills" / "minimax-advisor" / "SKILL.md"
        ).read_text(encoding="utf-8")
        advisory_doc = (repo_root / "orchestration" / "advisory.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("MINIMAX_API_KEY", server_source)
        self.assertIn("https://api.minimax.io/v1", server_source)
        self.assertIn("urllib.request", server_source)
        self.assertIn("reasoning_split", server_source)
        self.assertIn("missing MINIMAX_API_KEY", server_source)
        self.assertIn("MINIMAX_API_KEY_FILE", server_source)
        self.assertIn("MINIMAX_DEFAULT_API_KEY_FILE", server_source)
        self.assertNotIn("MINIMAX_GROK_COMMAND", server_source)
        self.assertNotIn("@vibe-kit/grok-cli", server_source)
        self.assertNotIn("Grok CLI", server_source)
        self.assertIn("MINIMAX_API_KEY", skill_source)
        self.assertIn("MINIMAX_API_KEY", advisory_doc)
        self.assertNotIn("Grok", skill_source)
        self.assertNotIn("Grok", advisory_doc)

    def test_advisory_mcp_is_regular_but_cost_gated_governor_feature(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        governor_prompt = (repo_root / "orchestration" / "prompts" / "governor.txt").read_text(
            encoding="utf-8"
        )
        advisory_doc = (repo_root / "orchestration" / "advisory.md").read_text(
            encoding="utf-8"
        )
        workflow_doc = (repo_root / "orchestration" / "workflow.md").read_text(
            encoding="utf-8"
        )
        routing_skill = (
            repo_root / "orchestration" / "skills" / "routing" / "SKILL.md"
        ).read_text(encoding="utf-8")
        governor_skill = (
            repo_root / "orchestration" / "skills" / "governor-workflow" / "SKILL.md"
        ).read_text(encoding="utf-8")
        normalized_governor_prompt = " ".join(governor_prompt.split())
        normalized_workflow_doc = " ".join(workflow_doc.split())

        for source in [governor_prompt, advisory_doc, workflow_doc, routing_skill, governor_skill]:
            self.assertIn("cost-gated", source)

        self.assertIn("do not consult for routine work", governor_prompt)
        self.assertIn("default to no advisor", routing_skill.lower())
        self.assertIn("prefer one advisor", routing_skill.lower())
        self.assertIn(
            "wrong decision would cost more than two consultations",
            normalized_governor_prompt,
        )
        self.assertIn(
            "wrong decision would cost more than two consultations",
            normalized_workflow_doc,
        )
        self.assertIn("consult_minimax", governor_prompt)
        self.assertIn("consult_claude_headless", governor_prompt)

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

    def test_governor_first_governed_work_execute_recommendation_downgrades_to_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            self._write_governor_prompt(repo_root)

            prepared = self._governor_first_submit(repo_root, "build a static app")
            model = session.dispatch_session_action(
                "complete_governor_turn",
                runtime_request_id=prepared["request"]["runtimeRequestId"],
                runtime_body=self._governor_semantic_body(
                    "governed_work_intent",
                    reply="I can prepare a bounded plan.",
                    recommended_permission="execute",
                    extra={
                        "normalized_intent": "Build a simple static app.",
                        "internal_reason": "Obvious work request, but execution still needs a plan.",
                    },
                ),
                repo_root=repo_root,
            )

            self.assertIn(model["feed"][-1]["type"], {"clarification_request", "permission_request"})
            if model["snapshot"].get("pendingPermissionRequest"):
                self.assertEqual(model["snapshot"]["pendingPermissionRequest"]["recommendedScope"], "plan")
            else:
                self.assertIsNotNone(model["activeClarification"])
            self.assertEqual(model["snapshot"]["permissionScope"], "unset")
            self.assertIsNone(model["planReadyRequest"])
            self.assertFalse((repo_root / ".agent" / "dispatches").exists())

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
            with mock.patch.object(governor_runtime.subprocess, "run", side_effect=fake_run):
                with mock.patch.object(governor_runtime, "prompt_path", return_value=prompt_root):
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

    def test_session_execute_permission_sets_session_mode_and_queued_state(self) -> None:
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
            self.assertEqual(model["snapshot"]["runState"], "queued")
            self.assertEqual(model["snapshot"]["currentActor"], "orchestration")
            self.assertEqual(model["snapshot"]["currentStage"], "dispatch_queued")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIn("Execute permission", model["acceptedIntakeSummary"]["body"])
            dispatch_requests = sorted(
                (repo_root / ".agent" / "dispatches").glob("**/request.json")
            )
            self.assertEqual(len(dispatch_requests), 1)
            request_payload = load_json(dispatch_requests[0])
            self.assertEqual(request_payload["execution_mode"], "command_chain")
            self.assertIn("artifact_only_executor_readout", request_payload["execution_payload"]["notes"])
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

    def test_session_execute_plan_action_authorizes_execute_and_queues_dispatch(self) -> None:
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
            self.assertEqual(model["snapshot"]["permissionScope"], "execute")
            self.assertEqual(model["snapshot"]["currentActor"], "orchestration")
            self.assertEqual(model["snapshot"]["currentStage"], "dispatch_queued")
            self.assertEqual(model["snapshot"]["runState"], "queued")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIsNotNone(model["acceptedIntakeSummary"])
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
            self.assertEqual(request_payload["execution_mode"], "command_chain")
            self.assertIn("artifact_only_executor_readout", request_payload["execution_payload"]["notes"])
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

    def test_session_execute_plan_without_accepted_intake_fails_closed(self) -> None:
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

            state = session.load_session(repo_root)
            state["model"]["acceptedIntakeSummary"] = None
            session.save_session(state, repo_root=repo_root)
            model = session.dispatch_session_action(
                "execute_plan",
                request_id="corgi-request:missing-intake-execute",
                context_ref=model["planReadyRequest"]["contextRef"],
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["currentStage"], "plan_ready")
            self.assertEqual(model["snapshot"]["permissionScope"], "plan")
            self.assertIsNotNone(model["planReadyRequest"])
            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["feed"][-1]["title"], "Accepted intake missing")
            self.assertEqual(model["feed"][-1].get("presentation_key"), "error.plan_not_ready")
            self.assertEqual(
                model["feed"][-1].get("presentation_args"),
                {"reason": "missing_intake"},
            )

    def test_session_execute_plan_without_accepted_intake_artifact_fails_closed(self) -> None:
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

            state = session.load_session(repo_root)
            intake_ref = state["meta"]["activeIntakeRef"]
            intake.accepted_intake_path(intake_ref, repo_root=repo_root).unlink()
            session.save_session(state, repo_root=repo_root)
            model = session.dispatch_session_action(
                "execute_plan",
                request_id="corgi-request:missing-artifact-execute",
                context_ref=model["planReadyRequest"]["contextRef"],
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["currentStage"], "plan_ready")
            self.assertEqual(model["snapshot"]["permissionScope"], "plan")
            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["feed"][-1]["title"], "Accepted intake artifact missing")
            self.assertEqual(model["feed"][-1].get("presentation_key"), "error.plan_not_ready")
            self.assertFalse((repo_root / ".agent" / "dispatches").exists())

    def test_session_execute_plan_without_request_id_fails_closed(self) -> None:
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
                context_ref=model["planReadyRequest"]["contextRef"],
                repo_root=repo_root,
            )

            self.assertEqual(model["snapshot"]["currentStage"], "plan_ready")
            self.assertEqual(model["snapshot"]["permissionScope"], "plan")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIsNotNone(model["planReadyRequest"])
            self.assertFalse((repo_root / ".agent" / "dispatches").exists())
            self.assertEqual(model["feed"][-1]["type"], "error")
            self.assertEqual(model["feed"][-1]["title"], "Request id required")
            self.assertEqual(model["feed"][-1].get("presentation_key"), "error.stale_context")

    def test_session_execute_plan_uses_configured_agent_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            runtime_agent_root = repo_root / ".agent-runtime"
            with mock.patch.dict(
                os.environ,
                {"ORCHESTRATION_AGENT_ROOT": str(runtime_agent_root)},
            ):
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
                    request_id="corgi-request:do-it",
                    context_ref=model["planReadyRequest"]["contextRef"],
                    repo_root=repo_root,
                )

            request_ref = model["feed"][-1]["source_artifact_ref"]
            self.assertIsInstance(request_ref, str)
            self.assertTrue(request_ref.startswith(".agent-runtime/dispatches/"))
            self.assertTrue((repo_root / request_ref).exists())
            self.assertFalse((repo_root / ".agent" / "dispatches").exists())

    def test_session_execute_permission_can_auto_consume_executor(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                        "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                    },
                ),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Analyze the repo.",
                    request_id="corgi-request:auto-analyze",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                model = session.dispatch_session_action(
                    "answer_clarification",
                    text="Focus on architecture, structure, and subsystem boundaries.",
                    request_id="corgi-request:auto-clarify",
                    context_ref=model["activeClarification"]["contextRef"],
                    repo_root=repo_root,
                )
                model = session.dispatch_session_action(
                    "set_permission_scope",
                    permission_scope="execute",
                    request_id="corgi-request:auto-execute",
                    context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                    auto_consume_executor=True,
                    repo_root=repo_root,
                )

            runtime_root = Path(runtime_agent_root)
            dispatch_results = sorted(runtime_root.glob("dispatches/**/result.json"))
            self.assertEqual(len(dispatch_results), 1)
            dispatch_dir = dispatch_results[0].parent
            request_payload = load_json(dispatch_dir / "request.json")
            state_payload = load_json(dispatch_dir / "state.json")
            readout_path = self._assert_executor_readout(repo_root, dispatch_dir, model)
            review_path = self._assert_reviewer_readout(repo_root, dispatch_dir, model)
            decision_path = self._assert_governor_decision(repo_root, dispatch_dir, model)

            self.assertIn("executor_run", request_payload)
            self.assertEqual(state_payload["status"], "completed")
            self.assertEqual(model["snapshot"]["currentActor"], "governor")
            self.assertEqual(model["snapshot"]["currentStage"], "governor_decision_recorded")
            self.assertEqual(model["snapshot"]["runState"], "idle")
            self.assertEqual(model["snapshot"]["permissionScope"], "execute")
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertIsNone(model["planReadyRequest"])
            self.assertIsNone(model["activeForegroundRequestId"])
            self.assertEqual(model["feed"][-1]["title"], "Governor decision recorded")
            self.assertEqual(
                model["snapshot"]["recentArtifacts"][0]["path"],
                str(decision_path.relative_to(repo_root)),
            )
            self.assertEqual(
                model["snapshot"]["recentArtifacts"][1]["path"],
                str(review_path.relative_to(repo_root)),
            )
            self.assertEqual(
                model["snapshot"]["recentArtifacts"][2]["path"],
                str(readout_path.relative_to(repo_root)),
            )

    def test_session_execute_plan_auto_consume_flag_runs_executor(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                        "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                    },
                ),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Analyze the repo.",
                    request_id="corgi-request:plan-auto-analyze",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                model = session.dispatch_session_action(
                    "answer_clarification",
                    text="Focus on architecture, structure, and subsystem boundaries.",
                    request_id="corgi-request:plan-auto-clarify",
                    context_ref=model["activeClarification"]["contextRef"],
                    repo_root=repo_root,
                )
                prepared = session.dispatch_session_action(
                    "set_permission_scope",
                    permission_scope="plan",
                    request_id="corgi-request:plan-auto-plan",
                    context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                    governor_runtime="external",
                    repo_root=repo_root,
                )
                model = session.dispatch_session_action(
                    "complete_governor_turn",
                    runtime_request_id=prepared["request"]["runtimeRequestId"],
                    runtime_body=(
                        "Objective: analyze architecture. Proposed steps: inspect extension and "
                        "orchestration boundaries. Likely areas: src/ and orchestration/. "
                        "Risks or unknowns: scope may need narrowing. Execution readiness: ready."
                    ),
                    repo_root=repo_root,
                )
                model = session.dispatch_session_action(
                    "execute_plan",
                    request_id="corgi-request:plan-auto-execute-plan",
                    context_ref=model["planReadyRequest"]["contextRef"],
                    auto_consume_executor=True,
                    repo_root=repo_root,
                )

            runtime_root = Path(runtime_agent_root)
            dispatch_results = sorted(runtime_root.glob("dispatches/**/result.json"))
            self.assertEqual(len(dispatch_results), 1)
            dispatch_dir = dispatch_results[0].parent
            self._assert_executor_readout(repo_root, dispatch_dir, model)
            self._assert_reviewer_readout(repo_root, dispatch_dir, model)
            self._assert_governor_decision(repo_root, dispatch_dir, model)
            self.assertEqual(model["snapshot"]["currentActor"], "governor")
            self.assertEqual(model["snapshot"]["currentStage"], "governor_decision_recorded")
            self.assertEqual(model["snapshot"]["runState"], "idle")
            self.assertIsNone(model["activeForegroundRequestId"])
            self.assertEqual(model["feed"][-1]["title"], "Governor decision recorded")

    def test_session_reviewer_request_changes_creates_same_work_plan_revision(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                        "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                    },
                ),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Analyze the repo.",
                    request_id="corgi-request:revision-analyze",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                model = session.dispatch_session_action(
                    "answer_clarification",
                    text="Focus on architecture, structure, and subsystem boundaries.",
                    request_id="corgi-request:revision-clarify",
                    context_ref=model["activeClarification"]["contextRef"],
                    repo_root=repo_root,
                )
                with self._mock_governor_dialogue(body="Initial plan."):
                    model = session.dispatch_session_action(
                        "set_permission_scope",
                        permission_scope="plan",
                        request_id="corgi-request:revision-plan",
                        context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                        repo_root=repo_root,
                    )
                initial_plan = model["planReadyRequest"]

                def review_with_first_change(_repo_root: Path, request: dict, _result: dict) -> dict:
                    if request.get("attempt_number") != 1:
                        return {
                            "dispatch_ref": request["dispatch_ref"],
                            "reviewer_role": "agentR-helper",
                            "verdict": "pass",
                            "validator_assessment": ["second attempt passed"],
                            "scope_assessment": ["scope is bounded"],
                            "findings": [],
                            "residual_risks": [],
                            "recommendation": "accept",
                        }
                    return {
                        "dispatch_ref": request["dispatch_ref"],
                        "reviewer_role": "agentR-helper",
                        "verdict": "request_changes",
                        "validator_assessment": ["forced reviewer feedback"],
                        "scope_assessment": ["scope needs another pass"],
                        "findings": ["The plan needs a narrower second attempt."],
                        "residual_risks": [],
                        "recommendation": "redispatch_or_reject",
                    }

                with (
                    mock.patch.object(dispatch, "build_helper_review", side_effect=review_with_first_change),
                    self._mock_governor_dialogue(body="Revised plan from reviewer feedback."),
                ):
                    model = session.dispatch_session_action(
                        "execute_plan",
                        request_id="corgi-request:revision-execute",
                        context_ref=initial_plan["contextRef"],
                        auto_consume_executor=True,
                        repo_root=repo_root,
                    )

                self.assertEqual(model["snapshot"]["currentStage"], "governor_decision_recorded")
                self.assertEqual(model["snapshot"]["permissionScope"], "execute")
                self.assertIsNone(model["planReadyRequest"])

                work_dir = Path(runtime_agent_root) / "work" / initial_plan["workRef"]
                plan_v1 = repo_root / initial_plan["planRef"]
                self.assertTrue(plan_v1.exists())
                work_index = load_json(work_dir / "work.json")
                self.assertEqual(work_index["current_plan_version"], 2)
                self.assertEqual(work_index["status"], "completed")
                self.assertEqual(len(work_index["plans"]), 2)
                self.assertEqual(len(work_index["attempts"]), 2)
                self.assertEqual(len(work_index["reviews"]), 2)
                self.assertEqual(len(work_index["decisions"]), 2)
                self.assertEqual(work_index["reviews"][0]["verdict"], "request_changes")
                self.assertEqual(work_index["reviews"][0]["attempt_number"], 1)
                self.assertEqual(work_index["decisions"][0]["decision"], "reject")
                self.assertEqual(work_index["decisions"][0]["attempt_number"], 1)
                self.assertEqual(work_index["reviews"][1]["verdict"], "pass")
                self.assertEqual(work_index["decisions"][1]["decision"], "accept")
                self.assertEqual(model["snapshot"]["latestReviewVerdict"], "pass")
                self.assertEqual(model["snapshot"]["latestGovernorDecision"], "accept")
                self.assertEqual(model["snapshot"]["currentWorkRef"], initial_plan["workRef"])
                self.assertEqual(model["snapshot"]["currentAttemptNumber"], 2)
                self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
                self.assertIsNone(model.get("activeClarification"))
                revised_plan_entry = next(
                    plan for plan in work_index["plans"] if plan["plan_version"] == 2
                )
                self.assertEqual(revised_plan_entry["revision_reason"], "review_requested_changes")
                self.assertEqual(revised_plan_entry["latest_review_ref"], work_index["reviews"][0]["review_ref"])
                plan_v2 = repo_root / revised_plan_entry["plan_ref"]
                self.assertTrue(plan_v2.exists())
                self.assertEqual(plan_v1.parent, plan_v2.parent)
                plan_v2_text = plan_v2.read_text(encoding="utf-8")
                self.assertIn(f"- latest_review_ref: {work_index['reviews'][0]['review_ref']}", plan_v2_text)
                self.assertIn("- revision_reason: review_requested_changes", plan_v2_text)

                dispatch_requests = [
                    load_json(path)
                    for path in Path(runtime_agent_root).glob("dispatches/**/request.json")
                ]
                self.assertEqual(len(dispatch_requests), 2)
                first_request = next(
                    request for request in dispatch_requests if request["attempt_number"] == 1
                )
                second_request = next(
                    request for request in dispatch_requests if request["attempt_number"] == 2
                )
                self.assertEqual(first_request["work_ref"], initial_plan["workRef"])
                self.assertEqual(first_request["plan_ref"], initial_plan["planRef"])
                self.assertEqual(first_request["plan_version"], 1)
                self.assertNotIn("revision_of_dispatch_ref", first_request)
                self.assertEqual(second_request["attempt_number"], 2)
                self.assertEqual(second_request["work_ref"], initial_plan["workRef"])
                self.assertEqual(second_request["plan_ref"], revised_plan_entry["plan_ref"])
                self.assertEqual(second_request["plan_version"], 2)
                self.assertEqual(
                    second_request["revision_of_dispatch_ref"],
                    first_request["dispatch_ref"],
                )

    def test_session_reviewer_inconclusive_creates_same_work_plan_revision(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                        "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                    },
                ),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Analyze the repo.",
                    request_id="corgi-request:inconclusive-analyze",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                model = session.dispatch_session_action(
                    "answer_clarification",
                    text="Focus on architecture, structure, and subsystem boundaries.",
                    request_id="corgi-request:inconclusive-clarify",
                    context_ref=model["activeClarification"]["contextRef"],
                    repo_root=repo_root,
                )
                with self._mock_governor_dialogue(body="Initial plan."):
                    model = session.dispatch_session_action(
                        "set_permission_scope",
                        permission_scope="plan",
                        request_id="corgi-request:inconclusive-plan",
                        context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                        repo_root=repo_root,
                    )
                initial_plan = model["planReadyRequest"]

                def review_inconclusive_then_pass(_repo_root: Path, request: dict, _result: dict) -> dict:
                    if request.get("attempt_number") != 1:
                        return {
                            "dispatch_ref": request["dispatch_ref"],
                            "reviewer_role": "agentR-helper",
                            "verdict": "pass",
                            "validator_assessment": ["second attempt passed"],
                            "scope_assessment": ["scope is bounded"],
                            "findings": [],
                            "residual_risks": [],
                            "recommendation": "accept",
                        }
                    return {
                        "dispatch_ref": request["dispatch_ref"],
                        "reviewer_role": "agentR-helper",
                        "verdict": "inconclusive",
                        "validator_assessment": ["needs bounded verification"],
                        "scope_assessment": ["scope is bounded"],
                        "findings": [],
                        "residual_risks": ["Reviewer could not validate the artifact confidently."],
                        "recommendation": "bounded_verification_or_reviewer_subagent",
                    }

                with (
                    mock.patch.object(dispatch, "build_helper_review", side_effect=review_inconclusive_then_pass),
                    self._mock_governor_dialogue(body="Revised plan after inconclusive review."),
                ):
                    model = session.dispatch_session_action(
                        "execute_plan",
                        request_id="corgi-request:inconclusive-execute",
                        context_ref=initial_plan["contextRef"],
                        auto_consume_executor=True,
                        repo_root=repo_root,
                    )

                self.assertEqual(model["snapshot"]["currentStage"], "governor_decision_recorded")
                self.assertEqual(model["snapshot"]["latestReviewVerdict"], "pass")
                self.assertEqual(model["snapshot"]["latestGovernorDecision"], "accept")
                work_index = load_json(Path(runtime_agent_root) / "work" / initial_plan["workRef"] / "work.json")
                self.assertEqual(work_index["reviews"][0]["verdict"], "inconclusive")
                self.assertEqual(work_index["decisions"][0]["decision"], "needs_verification")
                self.assertEqual(work_index["plans"][1]["revision_reason"], "review_inconclusive")
                dispatch_requests = [
                    load_json(path)
                    for path in Path(runtime_agent_root).glob("dispatches/**/request.json")
                ]
                self.assertEqual(len(dispatch_requests), 2)
                self.assertEqual(
                    next(request for request in dispatch_requests if request["attempt_number"] == 2)["work_ref"],
                    initial_plan["workRef"],
                )

    def test_session_work_review_decision_preserves_legacy_refs(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with mock.patch.dict(
                os.environ,
                {
                    "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                    "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                },
            ):
                work_ref = "lane/work-legacy"
                work_path = Path(runtime_agent_root) / "work" / work_ref / "work.json"
                write_json(
                    work_path,
                    {
                        "work_ref": work_ref,
                        "status": "needs_replan",
                        "reviews": ["legacy/review.json"],
                        "decisions": ["legacy/governor_decision.json"],
                    },
                )
                dispatch_ref = "lane/work-legacy/dispatch-001"
                dispatch_dir = Path(runtime_agent_root) / "dispatches" / dispatch_ref
                review_path = Path(runtime_agent_root) / "reviews" / dispatch_ref / "review.json"
                write_json(
                    review_path,
                    {
                        "dispatch_ref": dispatch_ref,
                        "reviewer_role": "agentR-helper",
                        "verdict": "pass",
                        "validator_assessment": [],
                        "scope_assessment": [],
                        "findings": [],
                        "residual_risks": [],
                        "recommendation": "accept",
                    },
                )
                write_json(
                    dispatch_dir / "governor_decision.json",
                    {
                        "dispatch_ref": dispatch_ref,
                        "decision": "accept",
                        "result_ref": ".agent/runs/lane/work-legacy/dispatch-001/result.json",
                        "reason": "reviewer passed",
                        "recommended_next_action": "governor_may_accept",
                    },
                )
                session_payload = session.load_session(repo_root=repo_root)
                session._record_work_review_and_decision(
                    session_payload,
                    {
                        "work_ref": work_ref,
                        "dispatch_ref": dispatch_ref,
                        "dispatch_dir": str(dispatch_dir),
                        "attempt_number": 1,
                        "review_ref": str(review_path.relative_to(repo_root)),
                    },
                    {"ok": True, "artifacts": []},
                    "2026-05-06T00:00:00Z",
                    repo_root=repo_root,
                )

                work_index = load_json(work_path)
                self.assertEqual(work_index["reviews"][0]["review_ref"], "legacy/review.json")
                self.assertEqual(work_index["reviews"][0]["migrated_at"], "2026-05-06T00:00:00Z")
                self.assertEqual(
                    work_index["decisions"][0]["decision_ref"],
                    "legacy/governor_decision.json",
                )
                self.assertEqual(work_index["reviews"][1]["verdict"], "pass")
                self.assertEqual(work_index["decisions"][1]["decision"], "accept")

    def test_session_reviewer_replan_stops_at_revision_limit(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                        "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                    },
                ),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Analyze the repo.",
                    request_id="corgi-request:limit-analyze",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                model = session.dispatch_session_action(
                    "answer_clarification",
                    text="Focus on architecture, structure, and subsystem boundaries.",
                    request_id="corgi-request:limit-clarify",
                    context_ref=model["activeClarification"]["contextRef"],
                    repo_root=repo_root,
                )
                with self._mock_governor_dialogue(body="Initial plan."):
                    model = session.dispatch_session_action(
                        "set_permission_scope",
                        permission_scope="plan",
                        request_id="corgi-request:limit-plan",
                        context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                        repo_root=repo_root,
                    )
                initial_plan = model["planReadyRequest"]

                def review_always_requests_changes(_repo_root: Path, request: dict, _result: dict) -> dict:
                    return {
                        "dispatch_ref": request["dispatch_ref"],
                        "reviewer_role": "agentR-helper",
                        "verdict": "request_changes",
                        "validator_assessment": [f"forced failure attempt {request.get('attempt_number')}"],
                        "scope_assessment": ["scope needs another pass"],
                        "findings": ["The work still needs correction."],
                        "residual_risks": [],
                        "recommendation": "redispatch_or_reject",
                    }

                with (
                    mock.patch.object(dispatch, "build_helper_review", side_effect=review_always_requests_changes),
                    self._mock_governor_dialogue(body="Revised plan from reviewer feedback."),
                ):
                    model = session.dispatch_session_action(
                        "execute_plan",
                        request_id="corgi-request:limit-execute",
                        context_ref=initial_plan["contextRef"],
                        auto_consume_executor=True,
                        repo_root=repo_root,
                    )

                self.assertEqual(model["snapshot"]["currentStage"], "blocked")
                self.assertEqual(model["snapshot"]["permissionScope"], "execute")
                self.assertEqual(model["snapshot"]["runState"], "idle")
                self.assertIsNone(model["planReadyRequest"])
                self.assertIsNone(model["activeForegroundRequestId"])
                self.assertEqual(model["feed"][-1]["title"], "Revision limit reached")
                self.assertEqual(model["feed"][-1]["presentation_key"], "error.revision_limit")

                work_index = load_json(Path(runtime_agent_root) / "work" / initial_plan["workRef"] / "work.json")
                self.assertEqual(work_index["current_plan_version"], 3)
                self.assertEqual(work_index["revision_count"], 2)
                self.assertEqual(work_index["status"], "blocked")
                self.assertEqual(work_index["blocked_reason"], "revision_limit_reached")
                self.assertEqual(len(work_index["plans"]), 3)
                self.assertEqual(len(work_index["attempts"]), 3)
                self.assertEqual(len(work_index["reviews"]), 3)
                self.assertEqual(len(work_index["decisions"]), 3)

                dispatch_requests = [
                    load_json(path)
                    for path in Path(runtime_agent_root).glob("dispatches/**/request.json")
                ]
                self.assertEqual(len(dispatch_requests), 3)
                by_attempt = {request["attempt_number"]: request for request in dispatch_requests}
                self.assertEqual(by_attempt[1]["plan_version"], 1)
                self.assertEqual(by_attempt[2]["plan_version"], 2)
                self.assertEqual(by_attempt[3]["plan_version"], 3)
                self.assertEqual(by_attempt[1]["work_ref"], initial_plan["workRef"])
                self.assertEqual(by_attempt[2]["work_ref"], initial_plan["workRef"])
                self.assertEqual(by_attempt[3]["work_ref"], initial_plan["workRef"])
                self.assertNotIn("revision_of_dispatch_ref", by_attempt[1])
                self.assertEqual(by_attempt[2]["revision_of_dispatch_ref"], by_attempt[1]["dispatch_ref"])
                self.assertEqual(by_attempt[3]["revision_of_dispatch_ref"], by_attempt[2]["dispatch_ref"])

    def test_session_new_intake_resets_previous_work_bundle_state(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with mock.patch.dict(
                os.environ,
                {
                    "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                    "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                },
            ):
                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Analyze the repo.",
                    request_id="corgi-request:reset-work-analyze",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                model = session.dispatch_session_action(
                    "answer_clarification",
                    text="Focus on architecture, structure, and subsystem boundaries.",
                    request_id="corgi-request:reset-work-clarify",
                    context_ref=model["activeClarification"]["contextRef"],
                    repo_root=repo_root,
                )
                with self._mock_governor_dialogue(body="First plan."):
                    model = session.dispatch_session_action(
                        "set_permission_scope",
                        permission_scope="plan",
                        request_id="corgi-request:reset-work-plan",
                        context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                        repo_root=repo_root,
                    )
                first_plan = model["planReadyRequest"]
                self.assertEqual(first_plan["planVersion"], 1)
                self.assertTrue(first_plan["workRef"])

                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Build a compact execution window.",
                    request_id="corgi-request:reset-work-new",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                payload = session.load_session(repo_root)
                self.assertIsNone(payload["meta"].get("activeWorkRef"))
                self.assertIsNone(payload["model"].get("currentWorkRef"))
                self.assertIsNone(payload["model"].get("currentPlanRef"))
                self.assertEqual(payload["model"].get("currentAttemptNumber"), 0)
                self.assertEqual(payload["model"].get("planVersion"), 0)

                with self._mock_governor_dialogue(body="Second plan."):
                    model = session.dispatch_session_action(
                        "answer_clarification",
                        text="Preserve visible UX.",
                        request_id="corgi-request:reset-work-new-clarify",
                        context_ref=model["activeClarification"]["contextRef"],
                        repo_root=repo_root,
                    )
                second_plan = model["planReadyRequest"]
                self.assertEqual(second_plan["planVersion"], 1)
                self.assertNotEqual(second_plan["workRef"], first_plan["workRef"])
                self.assertNotEqual(second_plan["planRef"], first_plan["planRef"])

    def test_session_review_replan_uses_external_governor_runtime_when_selected(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                        "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                    },
                ),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                model = session.dispatch_session_action(
                    "submit_prompt",
                    text="Analyze the repo.",
                    request_id="corgi-request:external-replan-analyze",
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )
                model = session.dispatch_session_action(
                    "answer_clarification",
                    text="Focus on architecture, structure, and subsystem boundaries.",
                    request_id="corgi-request:external-replan-clarify",
                    context_ref=model["activeClarification"]["contextRef"],
                    repo_root=repo_root,
                )
                with self._mock_governor_dialogue(body="Initial plan."):
                    model = session.dispatch_session_action(
                        "set_permission_scope",
                        permission_scope="plan",
                        request_id="corgi-request:external-replan-plan",
                        context_ref=model["snapshot"]["pendingPermissionRequest"]["contextRef"],
                        repo_root=repo_root,
                    )
                initial_plan = model["planReadyRequest"]

                def review_with_first_change(_repo_root: Path, request: dict, _result: dict) -> dict:
                    if request.get("attempt_number") != 1:
                        return {
                            "dispatch_ref": request["dispatch_ref"],
                            "reviewer_role": "agentR-helper",
                            "verdict": "pass",
                            "validator_assessment": ["second attempt passed"],
                            "scope_assessment": ["scope is bounded"],
                            "findings": [],
                            "residual_risks": [],
                            "recommendation": "accept",
                        }
                    return {
                        "dispatch_ref": request["dispatch_ref"],
                        "reviewer_role": "agentR-helper",
                        "verdict": "request_changes",
                        "validator_assessment": ["forced reviewer feedback"],
                        "scope_assessment": ["scope needs another pass"],
                        "findings": ["The plan needs a narrower second attempt."],
                        "residual_risks": [],
                        "recommendation": "redispatch_or_reject",
                    }

                with mock.patch.object(dispatch, "build_helper_review", side_effect=review_with_first_change):
                    prepared = session.dispatch_session_action(
                        "execute_plan",
                        request_id="corgi-request:external-replan-execute",
                        context_ref=initial_plan["contextRef"],
                        auto_consume_executor=True,
                        governor_runtime="external",
                        repo_root=repo_root,
                    )

                self.assertEqual(prepared["kind"], "governor_runtime_request")
                self.assertEqual(prepared["request"]["runtimeKind"], "plan")
                self.assertEqual(prepared["request"]["resultStage"], "plan_ready")
                prepared_model = prepared["model"]
                self.assertEqual(prepared_model["snapshot"]["currentStage"], "waiting_for_governor")
                self.assertIsNone(prepared_model["planReadyRequest"])

                model = session.dispatch_session_action(
                    "complete_governor_turn",
                    runtime_request_id=prepared["request"]["runtimeRequestId"],
                    runtime_body="Revised plan from app-server Governor.",
                    repo_root=repo_root,
                )
                self.assertEqual(model["snapshot"]["currentStage"], "governor_decision_recorded")
                self.assertEqual(model["snapshot"]["permissionScope"], "execute")
                self.assertIsNone(model["planReadyRequest"])
                dispatch_requests = [
                    load_json(path)
                    for path in Path(runtime_agent_root).glob("dispatches/**/request.json")
                ]
                self.assertEqual(len(dispatch_requests), 2)
                second_request = next(
                    request for request in dispatch_requests if request["attempt_number"] == 2
                )
                self.assertEqual(second_request["work_ref"], initial_plan["workRef"])
                self.assertEqual(second_request["plan_version"], 2)
                work_index = load_json(Path(runtime_agent_root) / "work" / initial_plan["workRef"] / "work.json")
                self.assertEqual(work_index["status"], "completed")
                self.assertEqual(work_index["current_plan_version"], 2)

    def test_executor_test_fixture_starts_at_plan_ready_execution_checkpoint(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            env = {
                **os.environ,
                "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
            }
            subprocess.run(
                [
                    sys.executable,
                    "orchestration/scripts/seed_executor_test_session.py",
                    "--root",
                    str(repo_root),
                    "--scenario",
                    "execute-permission",
                ],
                check=True,
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
            )
            with (
                mock.patch.dict(os.environ, env),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                seeded = session.load_session(repo_root)["model"]
                pending_permission = seeded["snapshot"]["pendingPermissionRequest"]
                self.assertIsNone(pending_permission)
                self.assertIsNotNone(seeded["planReadyRequest"])
                self.assertEqual(seeded["snapshot"]["currentStage"], "plan_ready")
                self.assertEqual(seeded["snapshot"]["permissionScope"], "plan")
                self.assertIsNone(seeded["activeClarification"])

                model = session.dispatch_session_action(
                    "execute_plan",
                    request_id="corgi-request:fixture-execute",
                    session_ref=seeded["snapshot"]["sessionRef"],
                    context_ref=seeded["planReadyRequest"]["contextRef"],
                    auto_consume_executor=True,
                    repo_root=repo_root,
                )

            runtime_root = Path(runtime_agent_root)
            dispatch_results = sorted(runtime_root.glob("dispatches/**/result.json"))
            self.assertEqual(len(dispatch_results), 1)
            dispatch_dir = dispatch_results[0].parent
            self._assert_executor_readout(repo_root, dispatch_dir, model)
            self._assert_reviewer_readout(repo_root, dispatch_dir, model)
            self._assert_governor_decision(repo_root, dispatch_dir, model)
            self.assertEqual(model["snapshot"]["currentStage"], "governor_decision_recorded")
            self.assertEqual(model["snapshot"]["runState"], "idle")

    def test_reviewer_test_fixture_can_start_ready_and_complete_reviewer(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)

        def run_fixture(scenario: str) -> None:
            with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
                env = {
                    **os.environ,
                    "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                    "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                }
                subprocess.run(
                    [
                        sys.executable,
                        "orchestration/scripts/seed_reviewer_test_session.py",
                        "--root",
                        str(repo_root),
                        "--scenario",
                        scenario,
                    ],
                    check=True,
                    cwd=repo_root,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                with (
                    mock.patch.dict(os.environ, env),
                    mock.patch.object(
                        runtime_support,
                        "APPROVED_PYTHON",
                        Path(sys.executable).resolve(),
                    ),
                ):
                    seeded = session.load_session(repo_root)["model"]
                    dispatch_results = sorted(Path(runtime_agent_root).glob("dispatches/**/result.json"))
                    self.assertEqual(len(dispatch_results), 1)
                    dispatch_dir = dispatch_results[0].parent
                    request_payload = load_json(dispatch_dir / "request.json")
                    review_path = repo_root / request_payload["review_artifact_path"]
                    self._assert_executor_readout(repo_root, dispatch_dir, seeded)

                    if scenario == "reviewer-ready":
                        self.assertEqual(seeded["snapshot"]["currentActor"], "reviewer")
                        self.assertEqual(seeded["snapshot"]["currentStage"], "reviewer_ready")
                        self.assertEqual(seeded["snapshot"]["runState"], "idle")
                        self.assertEqual(seeded["activeForegroundRequestId"], "corgi-fixture:reviewer")
                        self.assertFalse(review_path.exists())
                        self.assertFalse((dispatch_dir / "governor_decision.json").exists())
                    else:
                        self._assert_reviewer_readout(repo_root, dispatch_dir, seeded)
                        self.assertEqual(seeded["snapshot"]["currentActor"], "reviewer")
                        self.assertEqual(seeded["snapshot"]["currentStage"], "reviewer_completed")
                        self.assertEqual(seeded["snapshot"]["runState"], "idle")
                        self.assertIsNone(seeded["activeForegroundRequestId"])
                        self.assertFalse((dispatch_dir / "governor_decision.json").exists())

        run_fixture("reviewer-ready")
        run_fixture("reviewer-completed")

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

    def test_session_auto_accepted_execute_prompt_can_auto_consume_executor(self) -> None:
        repo_root = Path.cwd()
        agent_parent = repo_root / ".agent"
        agent_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=agent_parent) as runtime_agent_root:
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "ORCHESTRATION_AGENT_ROOT": runtime_agent_root,
                        "ORCHESTRATION_APPROVED_PYTHON": str(Path(sys.executable).resolve()),
                    },
                ),
                mock.patch.object(
                    runtime_support,
                    "APPROVED_PYTHON",
                    Path(sys.executable).resolve(),
                ),
            ):
                saved = session.load_session(repo_root)
                saved["model"]["snapshot"]["permissionScope"] = "execute"
                session.save_session(saved, repo_root=repo_root)

                model = session.dispatch_session_action(
                    "submit_prompt",
                    text=(
                        "Implement a quieter Chat transcript while keeping the VS Code Chat host, "
                        "preserving inline artifact actions, and replacing visible hold and reconnect "
                        "controls with cleaner approval affordances."
                    ),
                    request_id="corgi-request:auto-accepted-execute",
                    auto_consume_executor=True,
                    repo_root=repo_root,
                    **self._semantic_submit(),
                )

            runtime_root = Path(runtime_agent_root)
            dispatch_results = sorted(runtime_root.glob("dispatches/**/result.json"))
            self.assertEqual(len(dispatch_results), 1)
            dispatch_dir = dispatch_results[0].parent
            self._assert_executor_readout(repo_root, dispatch_dir, model)
            self._assert_reviewer_readout(repo_root, dispatch_dir, model)
            self._assert_governor_decision(repo_root, dispatch_dir, model)
            self.assertIsNone(model["snapshot"]["pendingPermissionRequest"])
            self.assertEqual(model["snapshot"]["permissionScope"], "execute")
            self.assertEqual(model["snapshot"]["currentActor"], "governor")
            self.assertEqual(model["snapshot"]["currentStage"], "governor_decision_recorded")
            self.assertEqual(model["snapshot"]["runState"], "idle")
            self.assertIsNone(model["activeForegroundRequestId"])

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
            self.assertEqual(model["snapshot"]["runState"], "queued")
            payload = session.load_session(repo_root)
            model["snapshot"]["runState"] = "running"
            model["snapshot"]["currentActor"] = "executor"
            payload["model"] = model
            session.save_session(payload, repo_root=repo_root)
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

    def test_start_guard_ignores_test_workspace_marker_but_blocks_real_uncovered_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True)
            (repo_root / "THIS_IS_A_CORGI_TEST_WORKSPACE.md").write_text(
                "Corgi test workspace marker.\n",
                encoding="utf-8",
            )
            (repo_root / "src").mkdir(parents=True, exist_ok=True)
            (repo_root / "src" / "app.js").write_text("console.log('ok');\n", encoding="utf-8")
            (repo_root / "notes.txt").write_text("unplanned\n", encoding="utf-8")

            blockers = start_guard.worktree_coverage_blockers(
                repo_root,
                {
                    "dispatch_ref": "lane/test/dispatch-001",
                    "lane": "lane/test",
                    "required_outputs": ["src/app.js"],
                },
                include_current_request_scope=True,
            )

            self.assertIn("uncovered_worktree_change:notes.txt", blockers)
            self.assertNotIn(
                "uncovered_worktree_change:THIS_IS_A_CORGI_TEST_WORKSPACE.md",
                blockers,
            )
            self.assertNotIn("uncovered_worktree_change:src/app.js", blockers)

    def test_authorship_evidence_classifies_created_and_mutated_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            before_created = authorship_evidence.capture_signatures(repo_root, ["README.md"])
            (repo_root / "README.md").write_text("created by executor\n", encoding="utf-8")
            after_created = authorship_evidence.capture_signatures(repo_root, ["README.md"])
            created = authorship_evidence.build_evidence_payload(
                repo_root,
                {"required_outputs": ["README.md"], "authorship_evidence": {"required": True}},
                before_created,
                after_created,
            )

            self.assertTrue(created["verified"])
            self.assertEqual(
                created["required_outputs"]["README.md"]["classification"],
                "created",
            )

            before_mutated = authorship_evidence.capture_signatures(repo_root, ["README.md"])
            (repo_root / "README.md").write_text("mutated by executor\n", encoding="utf-8")
            after_mutated = authorship_evidence.capture_signatures(repo_root, ["README.md"])
            mutated = authorship_evidence.build_evidence_payload(
                repo_root,
                {"required_outputs": ["README.md"], "authorship_evidence": {"required": True}},
                before_mutated,
                after_mutated,
            )

            self.assertTrue(mutated["verified"])
            self.assertEqual(
                mutated["required_outputs"]["README.md"]["classification"],
                "mutated",
            )

    def test_authorship_evidence_blocks_unchanged_and_dirty_at_claim_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            (repo_root / "README.md").write_text("pre-existing content\n", encoding="utf-8")
            before = authorship_evidence.capture_signatures(repo_root, ["README.md"])
            after = authorship_evidence.capture_signatures(repo_root, ["README.md"])

            unchanged = authorship_evidence.build_evidence_payload(
                repo_root,
                {"required_outputs": ["README.md"], "authorship_evidence": {"required": True}},
                before,
                after,
            )
            self.assertFalse(unchanged["verified"])
            self.assertIn("unchanged_required_output:README.md", unchanged["blockers"])

            dirty = authorship_evidence.build_evidence_payload(
                repo_root,
                {"required_outputs": ["README.md"], "authorship_evidence": {"required": True}},
                before,
                after,
                baseline_status={"README.md": "??"},
            )
            self.assertFalse(dirty["verified"])
            self.assertIn("dirty_at_claim:README.md", dirty["blockers"])

    def test_authorship_evidence_allows_explicit_idempotent_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            (repo_root / "README.md").write_text("stable generated content\n", encoding="utf-8")
            before = authorship_evidence.capture_signatures(repo_root, ["README.md"])
            after = authorship_evidence.capture_signatures(repo_root, ["README.md"])

            evidence = authorship_evidence.build_evidence_payload(
                repo_root,
                {
                    "required_outputs": ["README.md"],
                    "authorship_evidence": {
                        "required": True,
                        "idempotent_output_allowed": ["README.md"],
                    },
                },
                before,
                after,
            )

            self.assertTrue(evidence["verified"])
            self.assertEqual(evidence["blockers"], [])

    def test_authorship_evidence_rejects_boolean_idempotent_allowance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            (repo_root / "README.md").write_text("stable generated content\n", encoding="utf-8")
            before = authorship_evidence.capture_signatures(repo_root, ["README.md"])
            after = authorship_evidence.capture_signatures(repo_root, ["README.md"])

            request = {
                "required_outputs": ["README.md"],
                "authorship_evidence": {
                    "required": True,
                    "idempotent_output_allowed": True,
                },
            }
            evidence = authorship_evidence.build_evidence_payload(
                repo_root,
                request,
                before,
                after,
            )
            failures: list[str] = []
            dispatch_contracts.validate_authorship_evidence_request(request, failures)

            self.assertFalse(evidence["verified"])
            self.assertIn("unchanged_required_output:README.md", evidence["blockers"])
            self.assertIn(
                "request.json authorship_evidence.idempotent_output_allowed must be a string list when present",
                failures,
            )

    def test_result_contract_requires_output_signatures_for_authorship_dispatch(self) -> None:
        request = {
            "required_outputs": ["README.md"],
            "authorship_evidence": {
                "schema_version": "corgi.executor-authorship.v1",
                "required": True,
                "idempotent_output_allowed": [],
            },
        }
        result = {
            "dispatch_ref": "lane/test/dispatch-001",
            "status": "completed",
            "executor_run_refs": ["lane/test/dispatch-001"],
            "written_or_updated": ["README.md"],
            "auto_validated": ["validator"],
            "blocker": None,
            "recommended_next_bounded_task": "Governor should decide.",
            "runtime_behavior_changed": False,
            "scope_respected": True,
            "notes": [],
        }
        failures: list[str] = []

        dispatch_contracts.validate_result(result, failures, request=request)

        self.assertIn(
            "result.json missing output_signatures for authorship-evidence dispatch",
            failures,
        )

    def test_result_contract_accepts_verified_created_authorship_evidence(self) -> None:
        request = {
            "required_outputs": ["README.md"],
            "authorship_evidence": {
                "schema_version": "corgi.executor-authorship.v1",
                "required": True,
                "idempotent_output_allowed": [],
            },
        }
        result = {
            "dispatch_ref": "lane/test/dispatch-001",
            "status": "completed",
            "executor_run_refs": ["lane/test/dispatch-001"],
            "written_or_updated": ["README.md"],
            "auto_validated": ["validator"],
            "blocker": None,
            "recommended_next_bounded_task": "Governor should decide.",
            "runtime_behavior_changed": False,
            "scope_respected": True,
            "notes": [],
            "output_signatures": {
                "schema_version": "corgi.executor-authorship.v1",
                "baseline_ref": ".agent/runs/lane/test/dispatch-001/baseline_signatures.json",
                "after_ref": ".agent/runs/lane/test/dispatch-001/output_signatures.json",
                "required_outputs": {
                    "README.md": {
                        "classification": "created",
                        "dirty_at_claim": False,
                        "idempotent_allowed": False,
                    }
                },
                "summary": {"created": 1, "mutated": 0, "unchanged": 0, "missing": 0},
                "verified": True,
                "blockers": [],
            },
        }
        failures: list[str] = []

        dispatch_contracts.validate_result(result, failures, request=request)

        self.assertEqual(failures, [])

    def test_result_contract_validates_authorship_signature_artifact_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            refs = self._write_matching_authorship_refs(repo_root)
            request = self._authorship_request()
            result = self._authorship_result(
                baseline_ref=refs["baseline_ref"],
                after_ref=refs["after_ref"],
            )
            failures: list[str] = []

            dispatch_contracts.validate_result(
                result,
                failures,
                request=request,
                repo_root=repo_root,
            )

            self.assertEqual(failures, [])

    def test_result_contract_rejects_missing_or_tampered_authorship_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            refs = self._write_matching_authorship_refs(repo_root)
            request = self._authorship_request()
            result = self._authorship_result(
                baseline_ref=refs["baseline_ref"],
                after_ref=".agent/runs/lane/test/dispatch-001/missing.json",
            )
            failures: list[str] = []

            dispatch_contracts.validate_result(
                result,
                failures,
                request=request,
                repo_root=repo_root,
            )

            self.assertIn(
                "result.json output_signatures.after_ref does not exist: .agent/runs/lane/test/dispatch-001/missing.json",
                failures,
            )

            tampered_after = refs["after_payload"] | {"summary": {"created": 0, "mutated": 1}}
            (repo_root / refs["after_ref"]).write_text(
                json.dumps(tampered_after, indent=2),
                encoding="utf-8",
            )
            result = self._authorship_result(
                baseline_ref=refs["baseline_ref"],
                after_ref=refs["after_ref"],
            )
            failures = []

            dispatch_contracts.validate_result(
                result,
                failures,
                request=request,
                repo_root=repo_root,
            )

            self.assertIn(
                "result.json output_signatures.after_ref does not match embedded summary",
                failures,
            )

    def _authorship_request(self) -> dict:
        return {
            "required_outputs": ["README.md"],
            "authorship_evidence": {
                "schema_version": "corgi.executor-authorship.v1",
                "required": True,
                "idempotent_output_allowed": [],
            },
        }

    def _authorship_result(self, *, baseline_ref: str, after_ref: str) -> dict:
        return {
            "dispatch_ref": "lane/test/dispatch-001",
            "status": "completed",
            "executor_run_refs": ["lane/test/dispatch-001"],
            "written_or_updated": ["README.md"],
            "auto_validated": ["validator"],
            "blocker": None,
            "recommended_next_bounded_task": "Governor should decide.",
            "runtime_behavior_changed": False,
            "scope_respected": True,
            "notes": [],
            "output_signatures": {
                "schema_version": "corgi.executor-authorship.v1",
                "baseline_ref": baseline_ref,
                "after_ref": after_ref,
                "required_outputs": {
                    "README.md": {
                        "classification": "created",
                        "dirty_at_claim": False,
                        "idempotent_allowed": False,
                    }
                },
                "summary": {"created": 1, "mutated": 0, "unchanged": 0, "missing": 0},
                "verified": True,
                "blockers": [],
            },
        }

    def _write_matching_authorship_refs(self, repo_root: Path) -> dict:
        baseline_ref = ".agent/runs/lane/test/dispatch-001/baseline_signatures.json"
        after_ref = ".agent/runs/lane/test/dispatch-001/output_signatures.json"
        baseline_path = repo_root / baseline_ref
        after_path = repo_root / after_ref
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_payload = {
            "schema_version": "corgi.executor-authorship.v1",
            "dispatch_ref": "lane/test/dispatch-001",
            "executor_run_ref": "lane/test/dispatch-001",
            "required_outputs": ["README.md"],
            "signatures": {"README.md": {"present": False}},
        }
        after_payload = {
            "created_at": "2026-05-10T00:00:00Z",
            "dispatch_ref": "lane/test/dispatch-001",
            "executor_run_ref": "lane/test/dispatch-001",
            "baseline_signatures_ref": baseline_ref,
            "schema_version": "corgi.executor-authorship.v1",
            "required_outputs": {
                "README.md": {
                    "classification": "created",
                    "dirty_at_claim": False,
                    "idempotent_allowed": False,
                }
            },
            "summary": {"created": 1, "mutated": 0, "unchanged": 0, "missing": 0},
            "verified": True,
            "blockers": [],
        }
        baseline_path.write_text(json.dumps(baseline_payload, indent=2), encoding="utf-8")
        after_path.write_text(json.dumps(after_payload, indent=2), encoding="utf-8")
        return {
            "baseline_ref": baseline_ref,
            "after_ref": after_ref,
            "after_payload": after_payload,
        }

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
            repo_root = Path(tmp_dir).resolve()
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

    def test_parallel_request_metadata_requires_reviewed_scope(self) -> None:
        failures: list[str] = []
        request = self._parallel_request(
            "cycle/test/parallel/task/a01",
            scope="src/a.js",
            pre_review=False,
        )
        request.pop("scope_reservations")

        dispatch_contracts.validate_request(request, failures)

        self.assertIn(
            "request.json pre_dispatch_review_required must be true when parallel_set_ref is set",
            failures,
        )
        self.assertIn("request.json parallel_set_ref requires non-empty scope_reservations", failures)

    def test_parallel_set_start_guard_allows_reviewed_non_overlapping_second_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-001"
            first_ref = "cycle/test/parallel/task/a01"
            second_ref = "cycle/test/parallel/task/a02"
            first = self._parallel_request(first_ref, scope="src/a.js", parallel_set_ref=parallel_set_ref)
            second = self._parallel_request(second_ref, scope="src/b.js", parallel_set_ref=parallel_set_ref)
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref])
            self._write_pre_dispatch_review(repo_root, first_ref)
            self._write_pre_dispatch_review(repo_root, second_ref)
            self._write_pre_dispatch_review(
                repo_root,
                parallel_set_ref,
                covered_dispatch_refs=[first_ref, second_ref],
            )

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertEqual(blockers, [])

    def test_same_lane_parallel_start_requires_parallel_set_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            first_ref = "cycle/test/serial/task/a01"
            second_ref = "cycle/test/serial/task/a02"
            first = self._parallel_request(first_ref, scope="src/a.js", parallel_set_ref=None)
            second = self._parallel_request(second_ref, scope="src/b.js", parallel_set_ref=None)
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_pre_dispatch_review(repo_root, second_ref)

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertIn("parallel_set_ref_required_for_same_lane_parallel_start", blockers)

    def test_parallel_set_start_guard_enforces_set_max_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-001-max-one"
            first_ref = "cycle/test/parallel/task/a01"
            second_ref = "cycle/test/parallel/task/a02"
            first = self._parallel_request(first_ref, scope="src/a.js", parallel_set_ref=parallel_set_ref)
            second = self._parallel_request(second_ref, scope="src/b.js", parallel_set_ref=parallel_set_ref)
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref], max_active=1)
            self._write_pre_dispatch_review(
                repo_root,
                parallel_set_ref,
                covered_dispatch_refs=[first_ref, second_ref],
            )

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertIn(f"parallel_set_limit_reached:{parallel_set_ref}:1", blockers)

    def test_session_snapshot_reports_authoritative_parallel_activity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-001"
            first_ref = "cycle/test/parallel/task/snapshot-a01"
            second_ref = "cycle/test/parallel/task/snapshot-a02"
            first = self._parallel_request(first_ref, scope="src/a.js", parallel_set_ref=parallel_set_ref)
            second = self._parallel_request(second_ref, scope="src/b.js", parallel_set_ref=parallel_set_ref)
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="running")
            payload = {
                "meta": {},
                "model": session._initial_model(
                    "2026-04-10T10:00:00Z",
                    repo_root=repo_root,
                ),
            }
            payload["model"]["snapshot"]["lane"] = "lane/test"

            session._normalize_session(
                payload,
                "2026-04-10T10:00:01Z",
                repo_root=repo_root,
            )

            self.assertEqual(payload["model"]["snapshot"]["activeParallelDispatchCount"], 2)
            self.assertEqual(payload["model"]["snapshot"]["currentParallelSetRef"], parallel_set_ref)

    def test_parallel_set_start_guard_blocks_missing_set_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-002"
            first_ref = "cycle/test/parallel/task/b01"
            second_ref = "cycle/test/parallel/task/b02"
            first = self._parallel_request(first_ref, scope="src/a.js", parallel_set_ref=parallel_set_ref)
            second = self._parallel_request(second_ref, scope="src/b.js", parallel_set_ref=parallel_set_ref)
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref])

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertTrue(any(blocker.startswith("pre_dispatch_review_missing:") for blocker in blockers))

    def test_parallel_set_start_guard_blocks_missing_member_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-002-member-review"
            first_ref = "cycle/test/parallel/task/member-review-a01"
            second_ref = "cycle/test/parallel/task/member-review-a02"
            first = self._parallel_request(first_ref, scope="src/a.js", parallel_set_ref=parallel_set_ref)
            second = self._parallel_request(second_ref, scope="src/b.js", parallel_set_ref=parallel_set_ref)
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref])
            self._write_pre_dispatch_review(
                repo_root,
                parallel_set_ref,
                covered_dispatch_refs=[first_ref, second_ref],
            )

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertIn(
                f"pre_dispatch_review_missing:{second_ref}:"
                f".agent/reviews/{second_ref}/pre_dispatch_review.json",
                blockers,
            )

    def test_parallel_set_start_guard_blocks_overlapping_member_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-003"
            first_ref = "cycle/test/parallel/task/c01"
            second_ref = "cycle/test/parallel/task/c02"
            first = self._parallel_request(first_ref, scope="src/app.js", parallel_set_ref=parallel_set_ref)
            second = self._parallel_request(second_ref, scope="src", parallel_set_ref=parallel_set_ref)
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref])
            self._write_pre_dispatch_review(repo_root, first_ref)
            self._write_pre_dispatch_review(repo_root, second_ref)
            self._write_pre_dispatch_review(
                repo_root,
                parallel_set_ref,
                covered_dispatch_refs=[first_ref, second_ref],
            )

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertIn(
                f"parallel_set_scope_conflict:{first_ref}:{second_ref}",
                blockers,
            )
            self.assertIn(f"scope_conflict:{first_ref}", blockers)

    def test_parallel_set_start_guard_allows_matching_overlap_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-004"
            first_ref = "cycle/test/parallel/task/d01"
            second_ref = "cycle/test/parallel/task/d02"
            overlap = {
                "mode": "git_worktree",
                "overlap_group": "app-overlap",
                "integration_policy": "choose_one",
            }
            first = self._parallel_request(
                first_ref,
                scope="src/app.js",
                parallel_set_ref=parallel_set_ref,
                overlap_isolation=overlap,
                execution_mode="guided_agent",
            )
            second = self._parallel_request(
                second_ref,
                scope="src",
                parallel_set_ref=parallel_set_ref,
                overlap_isolation=overlap,
                execution_mode="guided_agent",
            )
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref])
            self._write_pre_dispatch_review(repo_root, first_ref)
            self._write_pre_dispatch_review(repo_root, second_ref)
            self._write_pre_dispatch_review(
                repo_root,
                parallel_set_ref,
                covered_dispatch_refs=[first_ref, second_ref],
            )

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertEqual(blockers, [])

    def test_parallel_set_start_guard_blocks_gpu_exclusive_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-005"
            first_ref = "cycle/test/parallel/task/e01"
            second_ref = "cycle/test/parallel/task/e02"
            first = self._parallel_request(
                first_ref,
                scope="src/a.js",
                parallel_set_ref=parallel_set_ref,
                resource_hints={"gpu": "exclusive"},
            )
            second = self._parallel_request(
                second_ref,
                scope="src/b.js",
                parallel_set_ref=parallel_set_ref,
                resource_hints={"gpu": "shared"},
            )
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref])
            self._write_pre_dispatch_review(
                repo_root,
                parallel_set_ref,
                covered_dispatch_refs=[first_ref, second_ref],
            )

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertIn(
                f"parallel_set_resource_conflict:{first_ref}:{second_ref}:gpu_exclusive",
                blockers,
            )
            self.assertIn(f"resource_conflict:{first_ref}:gpu_exclusive", blockers)

    def test_parallel_set_start_guard_blocks_stale_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir).resolve()
            parallel_set_ref = "lane/test/parallel-set-006"
            first_ref = "cycle/test/parallel/task/f01"
            second_ref = "cycle/test/parallel/task/f02"
            stale_dependency = "cycle/test/parallel/task/upstream"
            first = self._parallel_request(first_ref, scope="src/a.js", parallel_set_ref=parallel_set_ref)
            second = self._parallel_request(
                second_ref,
                scope="src/b.js",
                parallel_set_ref=parallel_set_ref,
                depends_on=[stale_dependency],
            )
            self._write_dispatch_request(repo_root, first, state="claimed")
            self._write_dispatch_request(repo_root, second, state="queued")
            self._write_parallel_set(repo_root, parallel_set_ref, [first_ref, second_ref])
            self._write_pre_dispatch_review(
                repo_root,
                parallel_set_ref,
                covered_dispatch_refs=[first_ref, second_ref],
            )

            blockers = start_guard.find_start_blockers(repo_root, second)

            self.assertIn(f"unsatisfied_dependency:{stale_dependency}", blockers)
            self.assertIn(
                f"parallel_set_unsatisfied_dependency:{second_ref}:{stale_dependency}",
                blockers,
            )

    def test_parallel_set_contract_rejects_too_many_active_members(self) -> None:
        failures: list[str] = []
        parallel_dispatch.validate_parallel_set_payload(
            {
                "parallel_set_ref": "lane/test/parallel-set-007",
                "work_ref": "lane/test/work-001",
                "lane": "lane/test",
                "dispatch_refs": ["cycle/test/parallel/task/g01", "cycle/test/parallel/task/g02"],
                "intent": "unsafe wide fan-out",
                "max_active": 3,
                "review_artifact_path": ".agent/reviews/lane/test/parallel-set-007/pre_dispatch_review.json",
                "created_at": "2026-04-10T10:00:00Z",
            },
            failures,
        )

        self.assertIn("parallel_dispatch_set.json max_active must be an integer between 1 and 2", failures)
