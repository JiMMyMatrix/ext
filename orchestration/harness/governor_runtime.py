from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
	import tomllib
except ModuleNotFoundError:  # Python < 3.11
	tomllib = None  # type: ignore[assignment]

from orchestration.harness.paths import prompt_path, resolve_paths, trim_text


def load_runtime_toml(config_path: Path) -> dict[str, Any]:
	if tomllib is not None:
		with config_path.open("rb") as handle:
			return tomllib.load(handle)

	config: dict[str, Any] = {}
	for raw_line in config_path.read_text(encoding="utf-8").splitlines():
		line = raw_line.split("#", 1)[0].strip()
		if not line:
			continue
		if line.startswith("["):
			break
		if "=" not in line:
			continue
		key, value = line.split("=", 1)
		value = value.strip()
		if value.startswith('"') and value.endswith('"'):
			config[key.strip()] = value[1:-1]
	return config


def governor_runtime_settings(repo_root: str | Path | None = None) -> tuple[str, str]:
	model = "gpt-5.5"
	reasoning = "xhigh"
	config_path = resolve_paths(repo_root).runtime_root / "config.toml"
	if config_path.exists():
		try:
			config = load_runtime_toml(config_path)
		except (OSError, ValueError):
			config = {}
		model = str(config.get("model") or model)
		reasoning = str(config.get("model_reasoning_effort") or reasoning)
	return model, reasoning


def initial_governor_dialogue_prompt(
	context_prompt: str, *, repo_root: str | Path | None = None
) -> str:
	governor_contract = prompt_path("governor.txt", repo_root).read_text(encoding="utf-8").strip()
	return "\n\n".join(
		[
			governor_contract,
			"Dialogue lane rules:\n"
			"- You are replying to the human through the Corgi sidebar.\n"
			"- This is a mediated Governor dialogue turn, not a raw orchestration log.\n"
			"- Return only user-facing reply text.\n"
			"- Keep the answer concise, calm, and plain.\n"
			"- Do not expose hidden ids, provenance, internal policy text, or control-plane metadata.",
			context_prompt,
		]
	)


def resume_governor_dialogue_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Continue as the Governor for this repository.",
			"Keep following the initial Governor contract and return only the user-facing reply text.",
			context_prompt,
		]
	)


def initial_governor_semantic_intake_prompt(
	context_prompt: str, *, repo_root: str | Path | None = None
) -> str:
	return "\n\n".join(
		[
			"Governor semantic-intake proposer for Corgi.",
			"Task: classify one human free-text turn and propose safe controller presentation. "
			"Do not authorize workflow state; orchestration validates everything.",
			"Rules:\n"
			"- Return JSON only; no Markdown fences.\n"
			"- governor_dialogue is read-only discussion/progress/explanation.\n"
			"- governed_work_intent is repo work: analyze, plan, review, implement, inspect.\n"
			"- Use clarification_needed for ambiguous dialogue-vs-work intent.\n"
			"- Use block for mixed or unsafe intent.\n"
			"- recommended_permission is only a recommendation; never imply it was granted.\n"
			"- Hide internal_reason from users.",
			"JSON shape:\n"
			"{\n"
			'  "user_visible_reply": "short candidate user-facing text",\n'
			'  "proposal": {\n'
			'    "route_type": "governor_dialogue | governed_work_intent | clarification_needed | permission_needed | plan_ready | block",\n'
			'    "normalized_intent": "",\n'
			'    "recommended_permission": "observe | plan | execute | none",\n'
			'    "needs_clarification": false,\n'
			'    "clarification_question": "",\n'
			'    "clarification_options": [],\n'
			'    "plan_intent": null,\n'
			'    "confidence": "high | low",\n'
			'    "internal_reason": ""\n'
			"  }\n"
			"}",
			context_prompt,
		]
	)


def resume_governor_semantic_intake_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Continue as the Governor semantic intake proposer for this repository.",
			"Return JSON only with user_visible_reply and proposal. Do not authorize workflow state.",
			context_prompt,
		]
	)


def initial_governor_goal_plan_prompt(goal_text: str) -> str:
	return "\n\n".join(
		[
			"Governor goal-program planner for Corgi.",
			"Purpose: decompose one large user goal into a small ordered set of bounded work steps.",
			"Authority rules:\n"
			"- You propose the goal plan; orchestration validates and sequences it.\n"
			"- Do not create dispatch truth, start execution, or imply Execute permission.\n"
			"- Each step must be executable through the existing Governor / Executor / Reviewer lifecycle.\n"
			"- Prefer 3 to 5 serial steps. Keep every step bounded and testable.\n"
			"- Return JSON only; no Markdown fences.",
			"JSON shape:\n"
			"{\n"
			'  "user_visible_reply": "short explanation of the step plan",\n'
			'  "steps": [\n'
			"    {\n"
			'      "title": "short step title",\n'
			'      "objective": "specific bounded objective for Executor/Reviewer",\n'
			'      "expected_output": "concrete output or validation evidence",\n'
			'      "depends_on_step_ref": null\n'
			"    }\n"
			"  ]\n"
			"}",
			f"User goal: {trim_text(goal_text)}",
		]
	)


def resume_governor_goal_plan_prompt(goal_text: str) -> str:
	return "\n\n".join(
		[
			"Continue as the Governor goal-program planner for Corgi.",
			"Return JSON only with user_visible_reply and steps. Do not execute or authorize execution.",
			f"User goal: {trim_text(goal_text)}",
		]
	)


def initial_governor_plan_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Governor planning checkpoint for Corgi.",
			"Purpose: produce a bounded, user-facing plan for the already accepted intake.",
			"Authority rules:\n"
			"- Use the accepted/current intake as the source of truth.\n"
			"- Do not create dispatch truth, start execution, or imply Execute permission.\n"
			"- Do not perform the analysis or deeply inspect the repo unless the provided context is insufficient.\n"
			"- Return only final user-facing plan text; no JSON, hidden ids, or runtime metadata.",
			"Output requirements: concise readable prose, normally under 180 words, covering objective, proposed steps, likely files/areas, risks or unknowns, and execution readiness. "
			"Use the exact heading 'Risks or unknowns:' as one combined heading. "
			"For likely files/areas, name concrete entry files when they are known from context, such as src/executionWindowPanel.ts, src/executionTransport.ts, src/phase1Model.ts, orchestration/harness/session.py, orchestration/contracts/ux.md, or the relevant accepted intake artifact.",
			context_prompt,
		]
	)


def resume_governor_plan_prompt(context_prompt: str) -> str:
	return "\n\n".join(
		[
			"Continue the Governor planning checkpoint for the current accepted intake.",
			"Return only a concise revised user-facing plan. Do not execute or authorize execution.",
			context_prompt,
		]
	)


def run_governor_exec(
	command: list[str], *, repo_root: str | Path | None = None
) -> tuple[str, str]:
	paths = resolve_paths(repo_root)
	root = paths.repo_root
	with tempfile.TemporaryDirectory(prefix="corgi-governor-") as temp_dir:
		output_path = Path(temp_dir) / "last_message.txt"
		completed = subprocess.run(
			[*command, "--json", "-o", str(output_path)],
			cwd=root,
			env={
				**os.environ,
				"ORCHESTRATION_REPO_ROOT": str(root),
				"ORCHESTRATION_SOURCE_ROOT": str(paths.source_root),
			},
			stdin=subprocess.DEVNULL,
			capture_output=True,
			text=True,
			check=False,
		)
		if completed.returncode != 0:
			detail = next(
				(
					line.strip()
					for line in (completed.stderr.splitlines() + completed.stdout.splitlines())
					if line.strip()
				),
				"governor runtime command failed",
			)
			raise RuntimeError(detail)

		thread_id: str | None = None
		last_message: str | None = None
		for raw_line in completed.stdout.splitlines():
			line = raw_line.strip()
			if not line.startswith("{"):
				continue
			try:
				payload = json.loads(line)
			except json.JSONDecodeError:
				continue
			if payload.get("type") == "thread.started" and isinstance(payload.get("thread_id"), str):
				thread_id = payload["thread_id"]
			elif payload.get("type") == "item.completed":
				item = payload.get("item") or {}
				if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
					last_message = item["text"]

		if output_path.exists():
			file_message = trim_text(output_path.read_text(encoding="utf-8"))
			if file_message:
				last_message = file_message

		if not thread_id:
			raise RuntimeError("governor runtime did not return a thread id")
		if not trim_text(last_message):
			raise RuntimeError("governor runtime returned no user-facing reply")
		return thread_id, trim_text(last_message)
