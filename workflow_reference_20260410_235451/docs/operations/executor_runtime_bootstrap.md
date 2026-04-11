# Executor Runtime Bootstrap

This document describes the minimum viable helper-backed AgentB runtime path.

Reviewer note:
- the helper runtime now supports reviewer-gated dispatch finalization through
  `scripts/reviewer_consume_dispatch.py` and
  `scripts/governor_finalize_dispatch.py`
- helper-backed review remains an artifact-driven fallback; the configured
  reviewer subagent is still preferred for deeper semantic review when
  available

## Goal

Make dispatch consumption real enough that a second execution unit can:
- discover a queued dispatch
- claim it safely
- execute inside bounded executor scope only
- validate outputs
- complete or escalate the dispatch through repo artifacts alone

## Lifecycle artifact

Each dispatch now carries:
- `request.json`
- `state.json`
- `result.json` on successful completion
- optional `escalation.json`
- optional `review.json` via the configured review artifact path
- optional `governor_decision.json` after finalization

Supported `state.json.status` values:
- `queued`
- `claimed`
- `running`
- `validated`
- `completed`
- `escalated`

Allowed transitions:
- `queued -> claimed`
- `queued -> escalated`
- `claimed -> running`
- `claimed -> escalated`
- `running -> validated`
- `running -> escalated`
- `validated -> completed`
- `validated -> escalated`

`completed` and `escalated` are terminal.

## Governor-side emit path

Use:

`python3 scripts/governor_emit_dispatch.py ...`

For small routine helper-backed substantive tasks, prefer:

`python3 scripts/governor_emit_micro_dispatch.py ...`

Micro-dispatch boundary:
- low-risk docs/report/evidence maintenance only
- not for runtime/core patches
- not for reviewer-gated work

This script:
- writes `request.json`
- initializes or normalizes `state.json`
- stamps the initial `queued` transition

If the dispatch is reviewer-gated, the governor finalizes it with:

`python3 scripts/governor_finalize_dispatch.py --dispatch-dir .agent/dispatches/<...>`

If helper-backed execution completes cleanly and no blocker remains:
- the governor should persist `governor_decision.json` before any human-facing
  pause, summary, or handoff
- any human-facing stop still requires a proposed transition plus successful
  interrupt/liveness gate checks; helper completion alone is not a legal stop
  - context-window rollover or session handoff should be treated as an internal
  continuation point, not a human checkpoint by itself

For live-subagent dispatches, the governor should first call the thin spawn
bridge and only cross into live chat-window spawning after the bridge has
prepared the handoff artifact.

## Executor-side consume path

Use:

`python3 scripts/executor_consume_dispatch.py`

or target one dispatch explicitly:

`python3 scripts/executor_consume_dispatch.py --dispatch-dir .agent/dispatches/<...>`

The helper runtime currently executes these bounded modes directly:
- `manual_artifact_report`
- `command_chain`
- `report_only_demo`
- `sample_correctness_chain`
- `aggregate_report_refresh`

Contract-valid subagent modes:
- `guided_agent`
- `strict_refactor`

These two modes are defined by the governance docs and dispatch contract, but they are not executed by `scripts/executor_consume_dispatch.py`. If they are routed through this helper before a dedicated harness exists, the helper must hard-stop and return an escalation artifact instead of improvising.

Helper-runtime exclusion rule:
- queued discovery must ignore `guided_agent` and `strict_refactor` before claim
- explicit `--dispatch-dir` targeting must reject those modes before claim
- the existing later hard-stop remains only as a defensive backstop

Helper-runtime start guard:
- helper-backed queued discovery must also skip dispatches whose dependencies
  are not yet accepted
- dependencies are not satisfied by acceptance alone; they also need completed
  result state, outputs present, and validation evidence
- helper-backed queued discovery must skip dispatches whose declared
  `scope_reservations` overlap active same-lane work
- explicit `--dispatch-dir` targeting must reject the same start blockers
  before claim
- helper-backed same-lane active concurrency stays capped at 2
- helper-backed substantive work must also pass the worktree coverage guard
  before `result.json` is written

These modes stay intentionally narrow:
- scaffold or reuse the executor run
- produce only the bounded artifacts declared in the dispatch
- validate the run and required outputs
- write the dispatch result
- finalize the dispatch lifecycle

If a task is reviewer-gated:
- `scripts/governor_finalize_dispatch.py` triggers helper review only for helper-backed flows when needed
- `scripts/reviewer_consume_dispatch.py` can generate or validate the structured `review.json` artifact
- the reviewer remains read-only and does not alter executor lifecycle state directly
- `scripts/reviewer_contract.py` fails closed if reviewer execution touches repo files or workflow state outside the allowed review artifact
- `governor_finalize_dispatch.py` writes `governor_decision.json`
- live-subagent dispatches with missing review remain `needs_review`
- the final governor decision should consider both executor outputs and the reviewer artifact

For helper-backed work:
- `command_chain` is the normal mode for reproducible script-driven tasks
- `manual_artifact_report` is the normal mode when AgentB writes the artifacts directly and the helper only finalizes lifecycle state
- when `execution_payload.injected_weakness_guards` is present, helper-produced execution artifacts should preserve those weakness IDs in the execution manifest or run report for auditability

The report-only bounded modes are:
- `sample_correctness_chain`
  - writes one sample-scoped correctness chain:
    - `window_eval.<sample>.json`
    - `pairwise_eval.<sample>.json`
    - `guard_review.<sample>.json`
    - `supervisor_decision.<sample>.json`
- `aggregate_report_refresh`
  - refreshes the aggregate report-only governance baseline from the sample-scoped chains

See `runtime_bootstrap_guide.md` for concrete command examples using the current repo scripts.

## Single-session fallback vs true two-session execution

Single-session fallback:
- the same operator may emit a dispatch and then invoke the executor script manually
- role separation still exists in repo artifacts:
  - dispatch request
  - lifecycle state
  - executor run
  - dispatch result

True two-session execution:
- one session emits the dispatch
- a separate session or worker process runs `executor_consume_dispatch.py`
- the second session needs only repo artifacts, not chat history

## What remains forbidden

This bootstrap does not approve:
- runtime integration
- guarded rescue
- model retraining
- broad schema redesign
- freeform multi-agent autonomy
- runtime/core behavior changes outside active lane authority

The current strategic posture remains:
- lane authority comes from `AGENTS.md` plus the active lane spec
- no runtime/core behavior changes through this helper unless the active lane explicitly allows them
- report-only modes are available only when a bounded task explicitly uses them
- subagent-only modes require the executor path defined by the executor subagent architecture
