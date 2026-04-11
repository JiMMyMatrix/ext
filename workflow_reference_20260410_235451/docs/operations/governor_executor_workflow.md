# Governor / Executor Workflow

This repository uses a controlled Governor/Executor model for the current active lane on its dedicated branch.

Use this document as the concise architecture map.
Use `governor_workflow.md` for the canonical governor loop,
`governor_executor_dispatch_contract.md` for the request/state/result schema,
and `executor_runtime_bootstrap.md` for helper-runtime mechanics.

Roles:
- `agentA`: governor
- `agentB`: executor
- `agentR`: reviewer

Execution substrate:
- `.agent/runs/...`

Dispatch substrate:
- `.agent/dispatches/...`

Standard loop:
1. `agentA` reads current artifacts, validators, and governing docs.
2. `agentA` decides the next bounded lane-safe task.
3. `agentA` consults bounded advisors only when they materially reduce uncertainty.
4. `agentA` escalates to the human only for authority boundaries, safety boundaries, missing required inputs, or unresolved post-advisor deadlock.
5. `agentA` writes one bounded dispatch request and initializes `state.json` as `queued`.
   Direct in-session substantive lane work without a dispatch is a workflow violation.
   For small routine helper-backed substantive tasks, use the micro-dispatch helper instead of bypassing tracked execution.
6. `agentA` immediately calls the thin spawn bridge.
   - helper-backed modes stay on the helper runtime path
   - `guided_agent` and `strict_refactor` stay on the live chat-window subagent path
   - do not treat dispatch emission as proof that execution has already started
7. `agentB` executes exactly that task, validates outputs, and writes the dispatch result.
8. If review is required, `agentR` reads the executor package and returns structured review feedback.
   Helper-backed dispatch flows may satisfy this step through `scripts/reviewer_consume_dispatch.py`.
9. `agentA` reviews the executor package plus reviewer feedback and either accepts, revises into a new bounded task, or escalates.
   Helper-backed dispatch flows should persist that outcome through `scripts/governor_finalize_dispatch.py` and `governor_decision.json`.
10. If a dispatch has completed cleanly and no real blocker remains, `agentA`
    finalizes it before any human-facing pause and then either continues
    internally or escalates only at a material gate / merge-ready boundary.

Silent-by-default governor behavior:
- once branch work is authorized, routine internal workflow events do not require human interruption
- the human should hear only about material gates or a merge-ready branch
- if a tracked dispatch finishes cleanly, the governor should persist `governor_decision.json` before any human-facing pause, summary, or handoff
- context-window rollover or session handoff is an internal continuation point, not a human checkpoint by itself

Automatic dispatch is allowed for bounded lane-safe work such as:
- trace review or failure diagnosis inside the active lane
- narrow instrumentation tied to an explicit hypothesis
- narrow runtime or policy patch tied to explicit evidence
- sample-scoped or guard-set evaluation rerun
- narrow validator-backed artifact repair
- runtime/bootstrap maintenance for `.agent/`, dispatch scripts, validation helpers, or governance docs only

Automatic dispatch is not allowed for:
- lane changes without explicit authorization
- broad architecture work unrelated to the active bounded task
- generalized multi-sample campaigns outside the named guard or active lane surface
- policy changes that alter acceptance posture or authority boundaries

Execution modes:
- `command_chain` for deterministic helper-backed execution
- `guided_agent` for declared-file, stepwise subagent implementation
- `strict_refactor` for behavior-preserving subagent refactors validated by identical test results
- `manual_artifact_report` when the executor writes the bounded artifacts directly and the runtime only needs to finalize lifecycle state
- `sample_correctness_chain`, `aggregate_report_refresh`, and `report_only_demo` for helper-backed legacy/report-only workflows when explicitly in use

Tracked-path discipline:
- the only normal tracked paths for substantive lane work are explicit
  helper-backed dispatch and explicit live-subagent dispatch
- helper-backed work may remain non-spawn, but it still requires an explicit
  dispatch

Limited parallelism:
- keep same-lane active concurrency at 2 or fewer
- only start a second task when dependencies are already accepted and declared
  `scope_reservations` do not overlap
- if safety is unclear, serialize

Loop budget:
- if the governor has dispatched more than 5 consecutive cycles on the same bounded hypothesis without a `completed` result, stop, write a ceiling report, and escalate

Immediate escalation triggers:
- blocker that cannot be resolved inside scope
- authority boundary
- safety boundary
- missing required input
- conflicting governance rule
- proposed change would leave the active lane or change acceptance posture
- unresolved deadlock after advisor consultation

Strategic posture to preserve:
- the active lane is defined by `AGENTS.md` plus the current lane spec
- governor decides direction inside the lane
- reviewer verifies but does not decide
- advisors are advisory only
- executor remains the single writer

## Reviewer gate

Review should be the default for:
- `task_track = patch`
- medium/high-complexity tasks
- changes in runtime code, harness scripts, contracts, or prompts

Review may be skipped for:
- low-complexity docs-only tasks
- low-risk report-only artifact refreshes
- tiny governance/index alignment tasks with no runtime behavior change

Reviewer posture:
- read-only only
- structured verdict: `pass`, `request_changes`, or `inconclusive`
- advisory only; no merge, lane, or policy authority
- no dispatch/governor/state writes
- governor-only workflow transitions; reviewer overreach is a `reviewer_contract_violation`

## Disagreement handling

Decision rules:
- validator failure beats reviewer `pass`
- reviewer `request_changes` does not automatically reject the task, but the governor should usually redispatch or verify the finding
- reviewer `pass` does not bind the governor; the governor may still reject on lane, policy, or acceptance grounds
- reviewer `inconclusive` should trigger a bounded verification step instead of a guess
- when executor and reviewer disagree on facts, the governor should order a bounded reproduction or artifact check rather than choose by intuition

Runtime separation notes:
- dispatches live under `.agent/dispatches/...`
- executor runs live under `.agent/runs/...`
- `scripts/governor_emit_dispatch.py` initializes queued dispatches
- `scripts/governor_emit_micro_dispatch.py` emits low-friction helper-backed micro-dispatches
- `mcp/spawn_bridge_server.py` prepares and records the dispatch-to-live-spawn boundary
- `scripts/dispatch_start_guard.py` enforces dependency and scope-conflict checks before helper claim or live spawn
- `scripts/executor_consume_dispatch.py` consumes one queued helper-backed dispatch at a time and must ignore live-subagent modes before claim
- `scripts/reviewer_consume_dispatch.py` generates or validates review artifacts for reviewer-gated dispatches
- `scripts/reviewer_contract.py` fail-closes reviewer overreach outside the allowed review-artifact path
- `scripts/governor_finalize_dispatch.py` records the final governor decision for reviewer-gated dispatches
- `scripts/check_lane_merge_ready.py` is the lightweight branch gate before merge-ready notification or merge
- `scripts/validate_dispatch_contract.py` validates request/state/result/escalation integrity
- `docs/operations/runtime_bootstrap_guide.md` provides concrete command examples for the current runtime helper surface
