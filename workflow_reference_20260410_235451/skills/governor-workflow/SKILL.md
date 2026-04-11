---
name: governor-workflow
description: Governor dispatch loop, advisor-first consultation, panel consultation protocol, pre-flight review, and post-execution verification.
---

# Governor Workflow Skill

Use this skill only in `GOVERNOR` mode. Treat the governor as a quiet branch
orchestrator, not as a normal peer execution path for substantive lane work.

For detailed mechanics and artifact shapes, use:
- `docs/operations/governor_workflow.md`
- `docs/operations/governor_executor_dispatch_contract.md`
- `docs/governance/lane_and_authority.md`

## Core rules
- Once branch work is authorized, continue silently through routine dispatch,
  execution, review, and validation loops.
- Interrupt the human only for a real material gate or when the branch becomes
  merge-ready.
- `checkpoint != pause`; internal checkpoints and completed subtasks do not by
  themselves justify a human-facing stop.
- If a tracked dispatch completes cleanly, finalize it through
  `governor_decision.json` before any human-facing pause or status handoff.
- Before any human-facing stop, record
  `.agent/governor/<lane>/proposed_transition.json` and validate it through
  `scripts/check_governor_interrupt_gate.py` plus
  `scripts/check_governor_liveness.py`.
- Legal stop reasons are narrow: `merge_ready`, `lane_complete`,
  `material_blocker`, `missing_permission`, `missing_resource`,
  `human_decision_required`, and `safety_boundary`.
- If no legal stop reason exists, the workflow must continue internally or
  surface explicit `governor_stall`.
- Context-window rollover or session handoff is an internal continuation
  point, not a human checkpoint by itself.
- Substantive lane work must begin with an explicit dispatch. Missing dispatch
  is a workflow violation.
- The only normal tracked paths for substantive lane work are:
  - explicit helper-backed dispatch
  - explicit live-subagent dispatch
- Helper-backed work may remain non-spawn, but it still requires an explicit
  dispatch.
- `guided_agent` and `strict_refactor` must cross the live spawn boundary after
  dispatch emission.
- Do not treat direct in-session substantive lane work as a normal peer path.

## Low-friction tracked path
For small routine helper-backed substantive tasks, prefer:
- `python3 scripts/governor_emit_micro_dispatch.py ...`

Micro-dispatch is allowed only for clearly low-risk helper-backed maintenance
on:
- `docs/`
- `reports/`
- `evidence/`
- `.agent/`
- top-level operator docs such as `AGENTS.md`, `PROJECT_MEMORY.md`, and
  `README.md`

Do not use micro-dispatch for:
- runtime/core patches
- reviewer-gated work
- medium/high-complexity work
- anything that should be `guided_agent` or `strict_refactor`

## Default loop
1. inspect current lane artifacts, validator state, and branch posture
2. choose one bounded task that remains inside lane authority
3. consult advisors when useful; use panel mode for high-stakes decisions
4. emit a normal dispatch or an eligible micro-dispatch
5. call the thin spawn bridge immediately after dispatch emission
6. if the bridge resolves `helper_runtime`, continue helper-backed execution
7. if the bridge resolves `live_subagent`, use the prepared handoff and spawn
   the executor in the live chat window
8. inspect results, validation artifacts, and reviewer output when required
9. finalize through `governor_decision.json` before any human-facing pause
10. if a human-facing stop is proposed, record the structured transition and
    pass the interrupt/liveness gates first
11. continue quietly unless a material gate remains unresolved
12. before notifying the human that the branch is ready, run
    `python3 scripts/check_lane_merge_ready.py --lane <active-lane>`

## Limited safe parallelism
Default to serialization when safety is unclear.

At most 2 same-lane tracked tasks may be active at once, and a new task may
start only when:
- every `depends_on_dispatches` ref already has:
  - accepted `governor_decision.json`
  - completed `result.json` with no blocker
  - required outputs present
  - non-empty validation evidence
- the candidate task declares non-empty `scope_reservations`
- those reservations do not overlap active same-lane scope

Optional overlap isolation:
- keep the normal lightweight path for clearly non-overlapping work
- use git-worktree overlap isolation only as an explicit opt-in for
  overlapping live-subagent `patch` candidates
- small-batch limit remains 2 active same-lane tasks
- overlapping candidates may run in parallel only when they declare matching
  `overlap_isolation` metadata for the same overlap group and policy
- the safe default integration policy remains `choose_one`
- worktree isolation prevents direct write collisions; it does not remove
  semantic conflicts, dependency mistakes, or stale-base risk
- isolated candidate packaging must fail closed on out-of-scope substantive
  changes or workflow-state drift inside the isolated worktree
- executors must not integrate isolated candidates directly into the lane
  branch
- the governor remains the only integration authority and must integrate
  accepted candidates serially on the lane branch
- isolated integration requires a completed `result.json` plus an accepted
  `governor_decision.json`; the overlap sidecar alone is not enough authority
- if the lane branch moved after an isolated candidate was created, mark the
  candidate `stale`, `rebase_needed`, or `superseded` instead of silently
  integrating it

## Early enforcement
- helper-backed tasks must pass the start guard before queued discovery or
  explicit `--dispatch-dir` claim
- live-subagent tasks must pass the same start guard before
  `prepare_executor_spawn`
- helper-backed substantive work must pass the early worktree guard before
  `result.json` is written
- finalization must fail if uncovered substantive worktree changes remain

## Reviewer and validation rules
- Use the reviewer by default for:
  - `task_track = patch`
  - medium/high-complexity work
  - runtime code, harness/runtime scripts, contracts, or prompts
- Reviewer remains read-only and advisory.
- Validator failure still beats reviewer `pass`.
- For live-subagent dispatches with `review_required = true`, call the bridge
  again for reviewer handoff after executor completion.
- If live review is still missing, finalization must remain `needs_review`.

## Diagnosis, escalation, and smoke tests
- Prefer `diagnosis` until the exact failure surface is isolated.
- Do not dispatch a non-mechanical patch until the failure contract is exact.
- Run an executor smoke test before the first substantive executor dispatch in
  a fresh or uncertain session.
- Do not claim heavy escalation unless `.codex/agents/executor-heavy.toml`
  points to a model the runtime can actually use.

## Human escalation gates
Escalate only for:
- a real scope, policy, or architecture conflict not resolved by repo guidance
- missing permissions, credentials, or external blockers
- materially different unresolved options with different branch or product
  consequences
- final human review or merge once the branch is actually merge-ready

Do not escalate for:
- routine planning
- helper-vs-live path choice
- normal dispatch creation
- normal executor/reviewer cycles
- expected validation/fix loops
- routine reprioritization within the authorized branch goal
