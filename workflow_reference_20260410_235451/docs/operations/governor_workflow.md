# Governor Workflow

This is the canonical governor sequencing document.
Use it for the active loop, spawn-boundary timing, and reviewer handoff rules.
Use `governor_executor_dispatch_contract.md` for artifact fields and
`executor_runtime_bootstrap.md` / `runtime_bootstrap_guide.md` for helper-runtime mechanics.

## Pre-session audit (optional)

At the start of an autonomous session, the governor may run the
`$architecture-audit` skill to verify the system is correctly configured.

If the audit reports CRITICAL or HIGH issues, the governor must stop
and escalate to the human before proceeding with lane work.

Before substantive work, verify the active branch and lane state from git
if there is any doubt; a new chat window does not reset branch obligations.

This step is optional for routine sessions but recommended after:
- merging a structural branch
- container rebuild or restart
- modifying governance docs, config files, or TOML agents
- the previous session ended with unexpected failures

The governor may also trigger a targeted partial audit by asking Codex
to check only a specific section (e.g., "Run architecture audit step 3
only — check model name consistency").

## Executor availability smoke test (session-level)

Before the first substantive executor dispatch in a fresh session, after a
container restart, after modifying `.codex/agents/*.toml`, or whenever
executor trust is uncertain, run a bounded executor smoke test from the repo
root.

Smoke-test procedure:
1. dispatch a tiny artifact-only task to the standard executor
2. declare one scratch file under `.agent/smoke/`
3. verify post-hoc that only declared files were touched
4. if the prompt intentionally tempts an undeclared-path write, verify the executor refuses it rather than guessing

If the smoke test fails, treat the executor path as unavailable for
substantive work in that session and stop until runtime alignment is repaired.

## Harness runtime preflight (session-level)

Before correctness-sensitive harness work, confirm:
- `abba/.venv/bin/python` exists and is the interpreter the harness runner will use
- the current task's declared-file scope can be audited post-hoc against both tracked and untracked file changes
- the required durable artifact root under `.agent/runs/evals/...` is writable

If any of these checks fail:
- record `invalid_runtime_environment`, `scope_violation`, or `undeclared_untracked_output` as applicable
- stop before eval/acceptance work runs

## Durable eval and checkpoint storage

For live harness reruns:
- write eval outputs and checkpoint artifacts to repo-local durable storage
- default root: `.agent/runs/evals/<flow>/<run_ref-or-timestamp>/...`
- committed reports may summarize those reruns, but must not depend on `/tmp` paths

Use `/tmp` only for scratch work that will not be referenced by committed artifacts.

## Default loop
1. inspect current artifacts and validator state
2. choose one bounded lane-safe task
3. if necessary, consult bounded advisors and synthesize their advice
4. for any substantive lane task, emit an explicit dispatch before work starts
5. call the thin spawn bridge immediately after dispatch emission
   - if the bridge resolves a helper-backed path, no live spawn is needed
   - if the bridge resolves a live-subagent path, prepare the handoff and then spawn the executor in the live chat window
   - do not treat work as started until the bridge has prepared that boundary
6. let `agentB` execute exactly that task
7. consume run/result artifacts
8. if the task requires review, collect structured reviewer feedback
   - use the reviewer subagent when available for semantic review
   - for live-subagent dispatches, call the bridge again before reviewer handoff
   - in helper-backed dispatch flows, run `scripts/governor_finalize_dispatch.py` to trigger reviewer handling and write `governor_decision.json`
9. decide whether to continue autonomously or escalate

## Silent-by-default branch behavior

Once the human authorizes branch work in `GOVERNOR` mode:
- continue autonomously through routine dispatch, execution, review, and
  validation loops
- do not interrupt the human for routine workflow events
- interrupt only at a material gate or when the branch becomes merge-ready
- `checkpoint != pause`: internal checkpoints and small completed subtasks do
  not by themselves justify a human-facing stop
- if a tracked dispatch finishes cleanly, persist `governor_decision.json`
  before any human-facing pause, summary, or handoff
- treat context-window rollover or session handoff as an internal continuation
  point, not as a human checkpoint by itself

Routine internal workflow events include:
- choosing helper-backed vs live-subagent execution
- normal dispatch creation
- normal executor/reviewer cycles
- expected validation/fix loops
- routine reprioritization inside the authorized branch goal
- context rollover after a clean completed dispatch when finalization and the
  next bounded step can still be determined from repo guidance

## Tracked-path discipline

For substantive lane work, the only normal tracked paths are:
- explicit helper-backed dispatch
- explicit live-subagent dispatch

Helper-backed work may remain non-spawn, but it still requires an explicit
dispatch.

`guided_agent` and `strict_refactor` must cross the live spawn boundary after
dispatch emission.

Do not treat direct in-session substantive lane work as a normal peer path.
If no dispatch exists yet, stop and emit one first.
Missing dispatch for substantive lane work is a workflow violation.

For small routine helper-backed substantive tasks, prefer the low-friction
tracked path:
- `python3 scripts/governor_emit_micro_dispatch.py ...`

Micro-dispatch eligibility:
- clearly low-risk helper-backed docs/report/evidence maintenance only
- not for runtime/core patches
- not for reviewer-gated work
- not for anything that would otherwise need a normal medium/high-complexity
  dispatch

## Autonomous loop
When operating in an autonomous phase (Phase 1, 2, or 3 as defined in
autonomous_execution_spec.md §7):

1. classify the next task (bug_fix | feature_impl | refactor | excluded)
2. if excluded → stop, escalate to human
3. declare the file set and required validation tiers
4. dispatch with cycle_id = dispatch_ref
5. executor captures baseline, executes, validates
6. if validation passes → auto-commit with structured trailer
7. if review is required → collect reviewer verdict before treating the result as accepted
   - helper-backed flows should record that verdict through `governor_decision.json`
8. if validation fails → decide retry (max 3) or stop
9. if the dispatch completed cleanly → persist `governor_decision.json`
10. update autonomous session log
11. if a hard stop or unresolved material gate appears → pause and escalate
12. otherwise continue until the branch is merge-ready, out of scope, or fully done

Treat quiet-mode autonomous work as incomplete until the current branch
task is finished and merged.

## Human interrupt gate

Before any human-facing stop or summary handoff:
- record `.agent/governor/<lane>/proposed_transition.json`
- if the governor wants to stop, validate that transition with
  `scripts/check_governor_interrupt_gate.py`
- validate liveness with `scripts/check_governor_liveness.py`

Allowed human-stop reasons are narrow and explicit:
- `merge_ready`
- `lane_complete`
- `material_blocker`
- `missing_permission`
- `missing_resource`
- `human_decision_required`
- `safety_boundary`

These are not legal stop reasons by themselves:
- completed one dispatch
- completed one review
- completed one validation loop
- reached an internal milestone
- wants confirmation even though policy says continue internally

If no legal stop reason exists, the workflow must continue internally or raise
explicit `governor_stall`; it must not quietly hand control back to the human.

## Limited safe parallelism

The governor may run a small batch of tracked work in parallel only when all of
the following are true:
- active same-lane tracked task count would stay at 2 or fewer
- every candidate task's `depends_on_dispatches` already has:
  - `governor_decision.json` with `decision = accept`
  - `result.json` completed with no blocker
  - declared outputs present
  - non-empty validation evidence
- every candidate task declares non-empty `scope_reservations`
- no candidate scope overlaps an active same-lane task's scope reservation

If any of those checks fail or are unclear, serialize.

Optional overlap isolation:
- keep the normal lightweight path for non-overlapping tasks
- use git-worktree overlap isolation only as an explicit opt-in for overlapping
  live-subagent `patch` candidates
- small-batch limit remains 2 active same-lane tasks
- overlapping candidates may run in parallel only when they declare matching
  `overlap_isolation` metadata for the same overlap group and policy
- worktree isolation prevents direct write collisions; it does not remove
  semantic conflicts, dependency mistakes, or stale-base risk
- executors must not integrate isolated candidates directly into the lane branch
- isolated candidate packaging must fail closed on out-of-scope substantive
  changes or workflow-state drift inside the isolated worktree
- the governor remains the only integration authority and must integrate
  accepted candidates serially on the lane branch
- isolated integration requires a completed `result.json` plus an accepted
  `governor_decision.json`; the overlap sidecar alone is not enough authority
- if the lane branch moved after an isolated candidate was created, mark the
  candidate `stale`, `rebase_needed`, or `superseded` instead of silently
  integrating it

Enforcement points:
- helper-backed dispatches must pass `scripts/dispatch_start_guard.py` checks
  before queued discovery or explicit `--dispatch-dir` claim
- live-subagent dispatches must pass the same checks before
  `prepare_executor_spawn`
- overlap-isolated live-subagent dispatches also prepare
  `overlap_isolation.json`, an isolated worktree, and an ephemeral branch
  before executor spawn
- helper-backed substantive work must pass an early worktree guard before
  `result.json` is written
- finalization must fail if uncovered substantive worktree changes remain

## Dispatch prompt serialization

When spawning the executor subagent, the governor converts the structured
dispatch into a natural-language prompt. The governor must NOT send raw JSON.

Template:

---
You are the executor for a bounded coding task. Follow these rules exactly.

TASK_CLASS: {task_class}
DISPATCH_REF: {dispatch_ref}
TOOL_USE_BUDGET: {budget}

DECLARED_FILES (modify ONLY these):
- {file1}
- {file2}

INJECTED_WEAKNESS_GUARDS: {weakness_ids or "none"}

PLAN:
Step 1: {action} {target}
  Instruction: {instruction}
  Constraints:
  - {constraint1}
  - {constraint2}
  [Checkpoint: run "{command}" after this step. Stop if it fails.]

Step 2: ...

VALIDATION (run in order after all steps):
1. {tier1_command}
2. {tier2_command}
3. {tier3_command if applicable}

After validation, produce validation_delta.json with before/after metrics.

ON COMPLETION:
If all validation passes, commit with message:
  {type}({scope}): {description} [auto]

Include this trailer:
  Dispatch-Ref: {dispatch_ref}
  Validation-Tiers: {tiers}
  Auto-Commit: true

ON FAILURE:
Report which tier failed and include the error output.
Do NOT attempt to fix.
---

The prompt must be readable by a human and executable by gpt-5.3-codex.

## Spawn bridge boundary

After `scripts/governor_emit_dispatch.py` writes a dispatch:
- call the thin spawn bridge before treating the task as started
- the bridge decides helper-backed vs live-subagent path from the existing dispatch contract
- for live-subagent dispatches, the bridge prepares and records the handoff package but does not pretend to own a hidden internal spawn API
- based on the current repo evidence and the current documented workflow, we should not assume that an MCP tool can directly replace live chat-window spawning

The spawn bridge is a boundary formalizer only:
- it prepares `spawn_bridge.json`
- it prepares `executor_handoff.txt` or `reviewer_handoff.txt` when needed
- when overlap isolation is requested, it also prepares the isolated worktree
  handoff package and records `overlap_isolation.json`
- it records pre-spawn or post-spawn metadata
- it returns the exact next live chat-window action the governor must take

## Merge-ready gate

Before telling the human that a branch is ready for final review or before
merging:
- run `python3 scripts/check_lane_merge_ready.py --lane <active-lane>`
- require a clean worktree
- require substantive branch changes to be covered by accepted tracked
  dispatch scope
- require no unresolved lane dispatch state such as `needs_review`,
  `needs_verification`, or still-active dispatch lifecycle state
- require accepted supporting dispatches to still have real completion signals
  (`result.json`, outputs, validation evidence), not just an accepted decision
- require no unresolved overlap-isolation candidate state such as `prepared`,
  `candidate_ready`, `stale`, or `rebase_needed`

If the merge-ready gate fails:
- do not escalate just because routine work remains
- continue internal branch work until the gate passes or a real material gate
  appears

### Complexity Assessment (pre-dispatch)

Before dispatching any task, the governor MUST assign estimated_complexity:

1. Count files likely to be modified
2. Estimate lines of change
3. Check for cross-module dependencies
4. Estimate wall-clock time
5. Assign: low / medium / high based on criteria in governor_executor_dispatch_contract.md

estimated_complexity controls communication protocol strictness only and does NOT determine model selection.

IF estimated_complexity = high:
- Evaluate task decomposition (see Task Decomposition below)
- Author execution_plan with step-by-step breakdown
- Set checkpoint_after_step to the last preparatory step before long-running work

IF estimated_complexity = medium:
- Author execution_plan (recommended)
- Checkpoint artifact required from executor

### Skip-to-Heavy Gate (pre-dispatch, conservative exception)

The governor MAY bypass the standard executor and dispatch directly to `executor-heavy.toml` when ALL of the following are true:
- estimated_complexity = high
- task involves >= 5 files across >= 3 distinct modules
- prior evidence (weakness registry or recent escalation history) shows this task class consistently fails with the standard executor

When triggered:
- set attempt_number = 2
- dispatch directly to `executor-heavy.toml`
- log `SKIP_TO_HEAVY dispatch_ref={ref} reason={reason}`

When in doubt, do NOT skip; start with the standard executor.

### Heavy-executor runtime alignment

Before relying on escalation or skip-to-heavy, the governor MUST confirm the
model named in `.codex/agents/executor-heavy.toml` is actually supported by the
active runtime.

If the heavy model is unavailable:
- record a runtime-alignment blocker
- do NOT report that heavy escalation occurred
- do NOT silently keep retrying on the standard executor as a substitute for heavy escalation
- repair runtime alignment or escalate to the human

### Task Decomposition Protocol

A task SHOULD be decomposed if ANY of the following apply:
- >= 3 independent units of work (e.g. "rerun 6 samples" = 6 units)
- Expected wall-clock time > 5 minutes
- >= 4 files modified with cross-module dependencies
- >= 3 sequential steps without intermediate validation

Decomposition rules:
1. Break task into batch units (each <= 2 independent items or <= 1 complex item)
2. Each batch becomes a separate dispatch cycle with its own dispatch_ref
3. Batch dispatch_refs use parent ref as prefix: {parent_ref}/B01, /B02, ...
4. Each batch MUST produce a checkpoint artifact before governor dispatches next batch
5. Governor reviews checkpoint before continuing to next batch
6. If any batch fails escalation (3 attempts exhausted), STOP entire parent task and report to human

### Diagnosis-first dispatch discipline

Before authorizing a patch dispatch for a non-mechanical failure, the governor
SHOULD first authorize a `diagnosis` task that isolates the failure surface.

Diagnosis dispatches are for:
- artifact comparison
- trace review
- bounded instrumentation
- failure-surface isolation

Patch dispatches are for:
- localized implementation against an already-identified failure surface

The governor SHOULD keep a task in `diagnosis` track when:
- the exact failing key path is unknown
- the expected artifact shape is still unclear
- the source schema or contract is ambiguous

The governor SHOULD move to `patch` track only when the diagnosis artifact or
retry handoff identifies the concrete surface to change.

### Runtime patch authorization inside an active lane

Once a diagnosis artifact or `retry_handoff` identifies the exact failure
surface, the governor MAY authorize one narrow runtime patch inside the active
lane without separate human approval when ALL of the following are true:
- the change remains inside current lane authority
- the dispatch declares an explicit and minimal file set
- the expected runtime/code surface is localized and validator-backed
- no regression-guard policy, acceptance posture, or lane scope is being changed

When authorizing such a patch dispatch, the governor MUST:
- keep the task in `task_track = patch`
- declare every allowed runtime, test, script, and report file explicitly
- run post-hoc `git diff --name-only` verification
- reject the result if any undeclared file was touched

### Checkpoint contract closure

For any medium/high-complexity or batched dispatch, the governor MUST verify:
- the required checkpoint artifact exists
- the checkpoint artifact passes contract validation before the dispatch is treated as complete
- the checkpoint artifact is stored under a declared repo-local durable path

## Reviewer protocol

Use the reviewer by default for:
- `task_track = patch`
- medium/high-complexity tasks
- changes in `core/`, harness/runtime scripts, dispatch/runtime contracts, or prompts

The reviewer must stay read-only and advisory.
Reviewer writes must stay inside the allowed review-artifact path.
Workflow transitions remain governor-only.
Reviewer overreach is a `reviewer_contract_violation`.
The reviewer should return:
- `pass`
- `request_changes`
- `inconclusive`

The reviewer checks:
- semantic correctness of the executor's claimed result
- adequacy of validator coverage
- scope and declared-file compliance as reflected in the task package
- residual regression risk that validators may not have exercised

Disagreement handling:
- validator failure beats reviewer `pass`
- reviewer `request_changes` should usually lead to redispatch or bounded verification unless the finding is clearly unsupported
- reviewer `inconclusive` should trigger a bounded verification step
- reviewer `pass` does not prevent the governor from rejecting on lane, policy, or acceptance grounds

## Lane setup rule
- When opening a new lane, create and switch to a dedicated lane branch before substantive lane work begins.
- Keep lane checkpoints on that branch until they are ready to merge back into `main`.
- Do not activate a new lane directly on `main` unless the human explicitly authorizes that exception.

## Autonomy rule
A single successful dispatch is enough to continue autonomously if:
- the next step remains inside current lane authority
- no policy boundary is crossed
- the recommendation is grounded in artifacts and validations

Do not ask the human routine questions like:
- whether to rerun the broader sample evidence set to refresh durable acceptance evidence for the current lane
- whether to refresh committed reports and aggregate comparison artifacts before any runtime change is considered
- whether to run one bounded regression check after a promising acceptance-evidence refresh step

## Advisor-first rule
When the next step is non-trivial but still appears to remain inside current lane authority:
- consult one or more bounded advisors if useful
- synthesize their advice into one bounded recommendation
- proceed if one bounded recommendation is still clearly defensible
- escalate only if the advice does not collapse into one safe next action

## Panel consultation protocol
For high-stakes decisions, the governor uses panel mode: send the same
structured question to both `consult_minimax` and `consult_claude_headless`
with the same `cycle_id`.

### Panel question structure
Both advisors receive the same core question:
- CONTEXT: current lane, baseline posture, recent changes
- QUESTION: the specific question
- CONSTRAINTS: what is in scope / out of scope
- EXPECTED OUTPUT: ASSESSMENT, RECOMMENDATION, CONFIDENCE, RISKS

For MiniMax: inline code snippets under 500 words.
For headless: reference file paths.

### Panel synthesis
After both responses arrive, the governor produces:

```text
PANEL SYNTHESIS:
  Question: <original question>
  Cycle: <dispatch_ref>
  MiniMax Assessment: <2-3 sentence summary>
  MiniMax Confidence: <high/medium/low>
  Headless Assessment: <2-3 sentence summary>
  Headless Confidence: <high/medium/low>
  Agreement: ALIGNED | PARTIALLY_ALIGNED | DIVERGENT
```

Decision rules:
- ALIGNED: proceed with the shared recommendation
- PARTIALLY_ALIGNED: identify the divergence point, determine which advisor's reasoning is stronger, proceed with a merged recommendation
- DIVERGENT: do not proceed automatically; if within lane authority, the governor decides and records rationale; if at an authority boundary, escalate to the human with both opinions

## Risk-based pre-flight review
Use pre-flight review when the dispatch is high risk, especially:
- 3 or more files
- 4 or more steps
- low confidence after planning
- re-planning after failure

For high-risk dispatches, use panel mode instead of MiniMax-only pre-flight review.

## Post-execution verification
- always inspect validation results
- always run `git diff --name-only` to verify no undeclared files were modified
- always read `validation_delta.json` when present

### Executor result deep review (optional, panel mode)
For high-risk dispatches or when validation passed but the governor
suspects subtle issues, send the executor's diff and `validation_delta.json`
to both advisors:
- MiniMax reviews the logic conceptually
- Headless reads the surrounding code for integration risks

Use panel synthesis to decide accept or reject.

### Escalation Decision (post Tier 3 eval failure)

When an executor's output fails Tier 3 eval:

1. Read attempt_number from current dispatch payload
2. IF attempt_number < 3:
   a. Construct escalation_context:
      - Collect eval feedback from current attempt
      - Append to prior_attempts array
      - Write cumulative_failure_summary (2-3 sentences synthesizing all failures)
   b. Select executor:
      - attempt_number = 1 (just failed): next attempt uses executor-heavy.toml (gpt-5.4, xhigh)
      - attempt_number = 2 (first escalation failed): retry with executor-heavy.toml again
   c. Increment attempt_number
   d. Set escalated = true
   e. Re-dispatch with full escalation_context attached
   f. Log: "ESCALATION attempt_number={n} from={prior_executor} to={new_executor}"
3. IF attempt_number = 3 AND eval fails:
   a. STOP autonomous execution for this task
   b. Compile escalation report:
      - Original task description and dispatch_ref
      - All 3 attempt eval results with eval feedback
      - Files touched across all attempts
      - Cumulative failure summary
   c. Present to human for decision
   d. Log: "ESCALATION_EXHAUSTED task={dispatch_ref} attempts=3"

### Handling Executor Escalation Requests

When an executor produces an escalation request artifact instead of completing the task:

1. Read the escalation trigger and context
2. Evaluate whether the issue can be resolved by:
   a. Clarifying requirements and re-dispatching (same executor)
   b. Absorbing as governor direct-work (within 20-line limit)
   c. Escalating to human
3. Do NOT count an escalation request as a failed attempt — it is a communication, not a failure
4. Log: "EXECUTOR_ESCALATION_REQUEST dispatch_ref={ref} trigger={trigger}"

### Retry handoff template

When a task is retried after validation failure or escalated failure, the
governor MUST build a `retry_handoff` that includes:
- `failing_validator`
- `failing_artifact_path`
- `failing_key_path`
- `source_schema_ref`
- `expected_artifact_ref`
- `expected_value_summary`
- `observed_value_summary`

If the governor cannot state the exact failing key path, source schema, and
expected artifact, the next task SHOULD revert to `diagnosis` track rather
than retrying a `patch` track with vague instructions.

## Loop budget rule
If the governor has dispatched more than 5 consecutive cycles on the same bounded hypothesis without a `completed` result, the governor must stop, write a ceiling-report, and escalate.
