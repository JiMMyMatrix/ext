from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = ROOT / "orchestration" / "scripts"
PY_RUNTIME_FILES = (
    list((ROOT / "orchestration" / "scripts").glob("*.py"))
    + list((ROOT / "orchestration" / "runtime").rglob("*.py"))
    + list((ROOT / "orchestration" / "harness").rglob("*.py"))
)


class StructureAuditTests(unittest.TestCase):
    def test_no_legacy_runtime_path_leakage(self) -> None:
        forbidden_literal_patterns = [
            re.compile(r"docs/(operations|agent_context|governance)/"),
            re.compile(r"\.codex/agents/"),
            re.compile(r"""["']scripts/[^"']+["']"""),
        ]

        findings: list[str] = []
        for path in PY_RUNTIME_FILES:
            text = path.read_text(encoding="utf-8")
            for pattern in forbidden_literal_patterns:
                for match in pattern.finditer(text):
                    findings.append(f"{path.relative_to(ROOT)}:{match.group(0)}")

        self.assertEqual(findings, [])

    def test_referenced_orchestration_surface_paths_exist(self) -> None:
        reference_pattern = re.compile(
            r"""["'](orchestration/(?:scripts|prompts|contracts|runtime/actors)/[^"']+)["']"""
        )

        missing: list[str] = []
        for path in PY_RUNTIME_FILES:
            text = path.read_text(encoding="utf-8")
            for match in reference_pattern.finditer(text):
                ref = match.group(1)
                if not (ROOT / ref).exists():
                    missing.append(f"{path.relative_to(ROOT)} -> {ref}")

        self.assertEqual(missing, [])

    def test_extension_uses_canonical_orchestrate_cli(self) -> None:
        transport = (ROOT / "src" / "executionTransport.ts").read_text(encoding="utf-8")

        self.assertIn("'orchestrate.py'", transport)
        self.assertIn("'session'", transport)
        self.assertNotIn("ui_session_action.py", transport)

    def test_public_wrappers_delegate_to_harness(self) -> None:
        wrappers = {
            "orchestration/scripts/orchestrate.py": "orchestration.harness.cli",
            "orchestration/scripts/intake_shell.py": "orchestration.harness.intake",
            "orchestration/scripts/orchestrator_accept_intake.py": "orchestration.harness.intake",
            "orchestration/scripts/validate_intake_contract.py": "orchestration.harness.contracts",
            "orchestration/scripts/validate_dispatch_contract.py": "orchestration.harness.dispatch_contracts",
            "orchestration/scripts/spawn_bridge_core.py": "orchestration.harness.spawn_bridge",
            "orchestration/scripts/executor_consume_dispatch.py": "orchestration.harness.executor_runtime",
            "orchestration/scripts/harness_runtime.py": "orchestration.harness.runtime_support",
            "orchestration/scripts/harness_artifacts.py": "orchestration.harness.artifacts",
            "orchestration/scripts/reviewer_contract.py": "orchestration.harness.reviewer",
            "orchestration/scripts/ui_session_action.py": "orchestration.harness.session",
            "orchestration/scripts/_common.py": "orchestration.harness.paths",
            "orchestration/scripts/surface_paths.py": "orchestration.harness.paths",
        }

        for rel_path, expected_import in wrappers.items():
            text = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn(expected_import, text, msg=rel_path)

    def test_unsupported_helper_mode_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            subprocess.run(
                ["git", "init", "-b", "main"],
                cwd=repo_root,
                check=True,
                capture_output=True,
                text=True,
            )
            (repo_root / "README.md").write_text("temporary repo\n", encoding="utf-8")

            dispatch_ref = "lane/test/dispatch-001"
            dispatch_dir = repo_root / ".agent" / "dispatches" / Path(dispatch_ref)
            dispatch_dir.mkdir(parents=True, exist_ok=True)
            request = {
                "dispatch_ref": dispatch_ref,
                "lane": "lane/test",
                "execution_mode": "report_only_demo",
                "scope": ["README.md"],
                "non_goals": [],
                "required_outputs": [],
                "executor_run": {
                    "run_ref": "cycle/type/ref/artifact/1",
                    "objective": "unsupported helper runtime smoke test",
                    "scope": "README.md",
                    "read_list": [],
                    "produce_list": [],
                    "planned_file_touch_list": ["README.md"],
                    "non_goals": [],
                    "stop_conditions": [],
                },
            }
            state = {
                "dispatch_ref": dispatch_ref,
                "status": "queued",
                "claimed_by": None,
                "claimed_at": None,
                "run_ref": request["executor_run"]["run_ref"],
                "result_ref": None,
                "last_transition_at": "2026-04-11T00:00:00Z",
                "transition_history": [],
            }
            (dispatch_dir / "request.json").write_text(
                json.dumps(request, indent=2) + "\n",
                encoding="utf-8",
            )
            (dispatch_dir / "state.json").write_text(
                json.dumps(state, indent=2) + "\n",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["ORCHESTRATION_APPROVED_PYTHON"] = sys.executable
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_ROOT / "orchestrate.py"),
                    "dispatch",
                    "consume-executor",
                    "--dispatch-dir",
                    str(dispatch_dir),
                    "--root",
                    str(repo_root),
                ],
                cwd=ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(result.returncode, 0)
            escalation_ref = result.stdout.strip().splitlines()[-1]
            escalation_path = repo_root / escalation_ref
            self.assertTrue(escalation_path.exists())

            escalation = json.loads(escalation_path.read_text(encoding="utf-8"))
            self.assertEqual(
                escalation.get("failure_category"),
                "unsupported_in_orchestration_port",
            )
            self.assertIn(
                "intentionally unavailable in the stabilized orchestration helper runtime",
                escalation.get("reason", ""),
            )


if __name__ == "__main__":
    unittest.main()
