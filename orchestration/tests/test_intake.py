from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = ROOT / "orchestration" / "scripts"


def run_orchestrate(tmp_root: Path, *args: str) -> dict:
	env = os.environ.copy()
	env["ORCHESTRATION_REPO_ROOT"] = str(tmp_root)
	command = [sys.executable, str(SCRIPT_ROOT / "orchestrate.py"), *args]
	result = subprocess.run(
		command,
		check=True,
		capture_output=True,
		text=True,
		env=env,
		cwd=ROOT,
	)
	return json.loads(result.stdout)


class IntakeFlowTests(unittest.TestCase):
	def test_direct_ready_for_acceptance(self) -> None:
		with tempfile.TemporaryDirectory() as tmp_dir:
			tmp_root = Path(tmp_dir)
			payload = run_orchestrate(
				tmp_root,
				"intake",
				"start",
				"--text",
				"Implement the extension transport while keeping the composer compact and preserving artifact actions.",
			)
			self.assertEqual(payload["shell_state"], "ready_for_acceptance")
			self.assertEqual(payload["clarification_request"], None)

	def test_clarification_then_acceptance(self) -> None:
		with tempfile.TemporaryDirectory() as tmp_dir:
			tmp_root = Path(tmp_dir)
			start_payload = run_orchestrate(
				tmp_root,
				"intake",
				"start",
				"--text",
				"Build a compact execution window.",
			)
			self.assertEqual(start_payload["shell_state"], "clarification_needed")
			self.assertIsNotNone(start_payload["clarification_request"])

			answer_payload = run_orchestrate(
				tmp_root,
				"intake",
				"answer",
				"--intake-ref",
				start_payload["intake_ref"],
				"--text",
				"Keep inline artifact actions visible.",
			)
			self.assertEqual(answer_payload["shell_state"], "ready_for_acceptance")

			accepted_payload = run_orchestrate(
				tmp_root,
				"intake",
				"accept",
				"--intake-ref",
				start_payload["intake_ref"],
				"--lane",
				"lane/test",
				"--branch",
				"feature/test",
			)
			self.assertEqual(accepted_payload["lane"], "lane/test")
			self.assertTrue(
				(tmp_root / accepted_payload["accepted_intake_ref"]).exists()
			)
			self.assertFalse((tmp_root / "request.json").exists())

	def test_rejects_premature_acceptance(self) -> None:
		with tempfile.TemporaryDirectory() as tmp_dir:
			tmp_root = Path(tmp_dir)
			start_payload = run_orchestrate(
				tmp_root,
				"intake",
				"start",
				"--text",
				"Build a compact execution window.",
			)
			env = os.environ.copy()
			env["ORCHESTRATION_REPO_ROOT"] = str(tmp_root)
			command = [
				sys.executable,
				str(SCRIPT_ROOT / "orchestrate.py"),
				"intake",
				"accept",
				"--intake-ref",
				start_payload["intake_ref"],
				"--lane",
				"lane/test",
			]
			result = subprocess.run(
				command,
				check=False,
				capture_output=True,
				text=True,
				env=env,
				cwd=ROOT,
			)
			self.assertNotEqual(result.returncode, 0)
			self.assertIn("ready_for_acceptance", result.stderr or result.stdout)


if __name__ == "__main__":
	unittest.main()
