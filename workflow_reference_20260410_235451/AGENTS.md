# AGENTS.md

## Mission
This repository uses a Governor-led execution architecture for bounded system
and model development.

## Current posture
- `main` remains the integrated baseline reference branch.
- Current branch: `main`.
- Use `main` for integrated-baseline governance, validation-artifact review, documentation and audit alignment, merge/push housekeeping, and preparing the next dedicated lane when explicitly authorized.
- Do not use `main` for fresh sample-runtime patching or new substantive lane work without opening a dedicated branch first.

## Read next
- [Governance Overview](/workspace/esports_clipper/docs/governance/README.md) for policy, authority, next steps, and reference posture.
- [Operations README](/workspace/esports_clipper/docs/operations/README.md) for workflow, dispatch contract, helper-runtime docs, and prompts.
- [Operating Spec](/workspace/esports_clipper/docs/agent_context/operating_spec.md) and [Autonomous Execution Spec](/workspace/esports_clipper/docs/agent_context/autonomous_execution_spec.md) for operating rules and autonomous-phase behavior.
- Runtime source of truth: [.codex/config.toml](/workspace/esports_clipper/.codex/config.toml) and `.codex/agents/`.

## Mode summary
- Default mode is `CHAT`.
- Switch to `GOVERNOR` mode only when the human explicitly says so.
- In `CHAT` mode: assist directly; do not run Governor workflow or spawn executor subagents.
- In `GOVERNOR` mode: follow the governance and operations docs above and use the agents defined in `.codex/agents/`.
- `quiet mode` changes communication cadence only, not authority.

## Critical rules
- Do not push or merge unless the human explicitly authorizes it.
- Every substantive lane must live on its own dedicated branch.
- If branch or lane state is unclear, rediscover it from git and the docs before doing substantive work.
- In `GOVERNOR` mode, substantive lane work must begin with an explicit dispatch; direct in-session substantive lane work without a dispatch is a workflow violation.
- The only normal tracked paths for substantive lane work are explicit helper-backed dispatch and explicit live-subagent dispatch.
- Helper-backed work may remain non-spawn, but it still requires an explicit dispatch; `guided_agent` and `strict_refactor` must cross the live spawn boundary after dispatch emission.
- In `GOVERNOR` mode, routine dispatch/review/validation loops are internal; do not interrupt the human unless a material gate remains unresolved or the branch is merge-ready.
- `checkpoint != pause`: internal checkpoints and small completed subtasks do not by themselves justify a human-facing stop.
- If a tracked dispatch has a clean completed `result.json`, finalize it through `governor_decision.json` before any human-facing pause or status handoff.
- Before any human-facing stop in `GOVERNOR` mode, record `.agent/governor/<lane>/proposed_transition.json` and gate it through `scripts/check_governor_interrupt_gate.py` plus `scripts/check_governor_liveness.py`.
- Allowed human stop reasons are narrow and explicit: `merge_ready`, `lane_complete`, `material_blocker`, `missing_permission`, `missing_resource`, `human_decision_required`, and `safety_boundary`.
- If no legal stop reason exists, the workflow must continue internally or raise explicit `governor_stall`; it must not quietly hand control back to the human.
- Context-window rollover or session handoff is an internal continuation point, not a human checkpoint by itself.
- Prefer `scripts/governor_emit_micro_dispatch.py` only for clearly low-risk helper-backed docs/report/evidence maintenance. Do not use it for runtime/core patches, reviewer-gated work, or anything that would be medium/high complexity under normal dispatch rules.
- Parallel tracked work is conservative: at most 2 active same-lane tasks. Non-overlap uses the normal light path; explicit live-subagent patch dispatches may use optional git-worktree overlap isolation, but integration stays governor-only and stale candidates must not be silently integrated. If safety is unclear, serialize.
- A dependency counts as satisfied only when the upstream dispatch has an accepted `governor_decision.json`, a clean completed `result.json`, required outputs present, and non-empty validation evidence.
- For correctness-sensitive harness execution, use `abba/.venv/bin/python`.
- Store live eval and checkpoint artifacts under `.agent/runs/evals/...`; committed reports must not depend on `/tmp`.
- Executor-backed work must stay inside the declared file set; reviewer-backed work must stay read-only and advisory.
- Reviewer artifacts must stay advisory-only; reviewer overreach into repo/state/control writes is a `reviewer_contract_violation`.
- If executor runtime is uncertain, run a smoke test before substantive executor work.
- Before treating helper-backed substantive work as done, persist `governor_decision.json`; merge-ready requires tracked coverage plus no unresolved review/validation state.
- Before declaring a branch merge-ready or merging, run `scripts/check_lane_merge_ready.py` for the active lane.
- Do not claim heavy escalation unless the runtime can actually spawn the heavy executor model.

## Document precedence
When documents conflict, use this order:
1. `AGENTS.md`
2. files under `docs/governance/`
3. the active lane spec under `docs/agent_context/`
4. other operating specs under `docs/agent_context/`
5. files under `docs/operations/`
6. MCP runtime policy and hard platform limits
7. templates, handoffs, and historical artifacts

If a governance rule conflicts with runtime-enforced policy, respect the
runtime-enforced limit and record the blocker.

## Autonomous execution phase
Current phase: **Phase 1 — Supervised autonomous**

Use the [Autonomous Execution Spec](/workspace/esports_clipper/docs/agent_context/autonomous_execution_spec.md) for phase definitions and advancement criteria. Advancing to another phase still requires explicit human authorization.
