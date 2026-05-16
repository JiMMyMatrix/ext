from __future__ import annotations

import os
from typing import Any

from orchestration.harness.paths import trim_text

PET_DIARY_REAL_PROJECT_PRESET = "pet-life-diary-real-project"
PATCH_APP_SERVER_EXECUTOR_RUNTIME = "patch-app-server"

REAL_PROJECT_PATCH_CAPABILITIES: list[dict[str, str]] = [
	{
		"id": "baseline_inspection",
		"title": "Inspect project baseline",
		"purpose": "Produce a bounded .agent baseline note about current files, scripts, and testable surfaces without changing product files.",
	},
	{
		"id": "product_app_foundation",
		"title": "Create product app foundation",
		"purpose": "Create the first product-scale Pet Life Diary static app files, sample data, validation notes, and documentation.",
	},
	{
		"id": "care_routines",
		"title": "Add care routines",
		"purpose": "Mutate the existing product app with care-routine planning and validation evidence.",
	},
	{
		"id": "portfolio_handoff",
		"title": "Prepare portfolio handoff",
		"purpose": "Polish README, product spec, and validation notes for demo readiness.",
	},
]

CAPABILITY_IDS = {capability["id"] for capability in REAL_PROJECT_PATCH_CAPABILITIES}


def is_real_project_practical_exercise() -> bool:
	return (
		os.environ.get("ORCHESTRATION_TARGET_WORKSPACE_MODE") == "scratch"
		and os.environ.get("ORCHESTRATION_TEST_PROMPT_PRESET") == PET_DIARY_REAL_PROJECT_PRESET
	)


def selected_executor_runtime() -> str:
	return trim_text(os.environ.get("CORGI_EXECUTOR_RUNTIME")) or "unset"


def real_project_capability_summary() -> str:
	lines = [
		"Patch-app-server Executor capabilities for this practical exercise:",
	]
	for capability in REAL_PROJECT_PATCH_CAPABILITIES:
		lines.append(f"- {capability['id']}: {capability['purpose']}")
	lines.append("Use executor_capability on each step with exactly one listed id.")
	lines.append("If an important step does not fit these capabilities, choose a smaller supported step or explain the blocker.")
	return "\n".join(lines)


def capability_id(value: Any) -> str | None:
	candidate = trim_text(value).lower().replace(" ", "_").replace("-", "_")
	if candidate in CAPABILITY_IDS:
		return candidate
	return None


def step_text(step: dict[str, Any], *, accepted_ref: str | None = None) -> str:
	parts = [
		step.get("title"),
		step.get("objective"),
		step.get("expected_output"),
		step.get("task"),
		step.get("accepted_summary"),
		accepted_ref,
	]
	return " ".join(trim_text(part) for part in parts if trim_text(part)).lower()


def classify_real_project_step(
	step: dict[str, Any],
	*,
	step_index: int | None = None,
	accepted_ref: str | None = None,
) -> str | None:
	explicit = capability_id(step.get("executor_capability"))
	if explicit:
		return explicit
	text = step_text(step, accepted_ref=accepted_ref)
	if not text:
		return None
	if (
		("project structure" in text or "baseline" in text or "runnable/testable" in text)
		and ("without making product changes" in text or "inspect" in text)
	):
		return "baseline_inspection"
	if "pet life diary" in text and (
		"foundation" in text
		or "product-scale" in text
		or "local-first" in text
		or "app foundation" in text
		or "base app" in text
		or "initial app" in text
	):
		return "product_app_foundation"
	if "routine" in text and "pet life diary" in text:
		return "care_routines"
	if "pet life diary" in text and (
		"portfolio" in text
		or "demo readiness" in text
		or "readme" in text
		or "documentation" in text
		or "product spec" in text
	):
		return "portfolio_handoff"
	return None


def unsupported_real_project_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
	if not is_real_project_practical_exercise() or selected_executor_runtime() != PATCH_APP_SERVER_EXECUTOR_RUNTIME:
		return []
	unsupported: list[dict[str, Any]] = []
	for index, step in enumerate(steps, start=1):
		if classify_real_project_step(step, step_index=index) is None:
			unsupported.append(
				{
					"step_index": index,
					"title": trim_text(step.get("title")) or f"Step {index}",
					"objective": trim_text(step.get("objective")),
				}
			)
	return unsupported


def unsupported_steps_summary(unsupported_steps: list[dict[str, Any]]) -> str:
	parts = []
	for step in unsupported_steps:
		title = trim_text(step.get("title")) or f"Step {step.get('step_index')}"
		parts.append(f"step {step.get('step_index')}: {title}")
	return "; ".join(parts)
