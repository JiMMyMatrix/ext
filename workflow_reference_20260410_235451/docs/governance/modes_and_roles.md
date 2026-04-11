# Modes And Roles

## Modes

### CHAT mode
- Default mode for every new session.
- Assist directly: discuss architecture, inspect files, review code, or make
  edits when asked.
- Do not apply Governor dispatch workflow.
- Do not spawn executor subagents.
- Activated at session start or when the human says `exit Governor` /
  `停止執行`.

### GOVERNOR mode
- Activated only when the human explicitly says `Governor mode`, `開始執行`,
  or `dispatch`.
- AgentA is active and must follow:
  - `docs/operations/governor_workflow.md`
  - `docs/operations/governor_executor_dispatch_contract.md`
  - the active lane spec in `docs/agent_context/`
- Executor work must flow through the custom executor agents defined in
  `.codex/agents/`.
- Entering `GOVERNOR` mode does not itself spawn the executor; the governor
  first emits a dispatch and then crosses the spawn boundary through the
  thin spawn bridge.
- Once branch work is authorized, GOVERNOR mode is silent by default:
  routine dispatch creation, executor runs, reviewer passes, and expected
  validation/fix loops are internal workflow events, not human-interruption
  events.
- If a tracked dispatch finishes cleanly, finalize it through
  `governor_decision.json` before any human-facing pause, summary, or handoff.
- Before any human-facing stop, record
  `.agent/governor/<lane>/proposed_transition.json` and validate it through the
  interrupt gate plus liveness gate.
- Legal human stop reasons are narrow: `merge_ready`, `lane_complete`,
  `material_blocker`, `missing_permission`, `missing_resource`,
  `human_decision_required`, and `safety_boundary`.
- If no legal stop reason exists, the workflow must continue internally or
  surface explicit `governor_stall`.
- Context-window rollover or session handoff is an internal continuation point,
  not a human checkpoint by itself.

### Quiet flag
- Quiet mode modifies communication cadence, not authority.
- Quiet mode suppresses routine narration.
- Quiet mode remains in effect until branch completion, hard stop, or human
  interruption.
- Quiet mode does not grant push or merge authority.

## Roles

### AgentA: Governor
- Single decider for bounded lane sequencing.
- Owns planning, dispatch selection, advisor synthesis, and accept/reject
  decisions.
- May do only very minor direct repo work when allowed by `AGENTS.md`.
- Substantive lane work must flow through an explicit helper-backed dispatch or
  an explicit live-subagent dispatch.
- Missing dispatch for substantive lane work is a workflow violation, not a
  normal peer path.
- For small helper-backed substantive tasks, prefer the low-friction
  micro-dispatch path instead of bypassing tracked execution.
- AgentA may run at most 2 active tracked tasks in the same lane, and only
  when dependencies are satisfied and declared scope reservations do not
  overlap. Unclear cases must stay serialized.
- AgentA must not leave a clean completed dispatch unfinalized when no real
  blocker prevents `governor_decision.json`.
- Must not become the main repo writer.

### AgentB: Executor
- Single substantive writer.
- Configured by `.codex/agents/executor.toml`.
- Executes one bounded task at a time.
- Must stay inside the declared file set and validation contract.
- Must not reinterpret ambiguous instructions.

### Reviewer
- Read-only verifier.
- Configured by `.codex/agents/reviewer.toml`.
- Reviews executor outputs, diffs, validators, and artifacts.
- Returns `pass`, `request_changes`, or `inconclusive`.
- In helper-backed dispatch flows, review may be materialized through
  `scripts/reviewer_consume_dispatch.py` and consumed by
  `scripts/governor_finalize_dispatch.py`.
- Advisory only; does not edit files, write workflow state, or make final decisions.
- Workflow transitions remain governor-only.
- Reviewer overreach is a `reviewer_contract_violation`.

### executor-heavy
- Configured by `.codex/agents/executor-heavy.toml`.
- Used only through escalation.
- Same sandbox and scope rules as the standard executor.
- Must not be claimed as active if the runtime cannot actually spawn it.

### One-shot specialists
- Advisory only.
- May help with bounded research, diagnosis, or critique.
- Do not have merge, lane, or policy authority.
