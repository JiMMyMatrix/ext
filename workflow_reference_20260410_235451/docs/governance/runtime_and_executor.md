# Runtime And Executor Rules

## Runtime source of truth

Model selection and agent behavior are enforced by:
- `.codex/config.toml`
- `.codex/agents/executor.toml`
- `.codex/agents/executor-heavy.toml`
- `.codex/agents/reviewer.toml`
- `.codex/agents/advisor-reader.toml`

Governance prose describes policy. The TOML files are the runtime source of
truth.

This document is policy-level only.
For workflow mechanics and artifact behavior, use:
- `docs/operations/governor_workflow.md`
- `docs/operations/governor_executor_dispatch_contract.md`
- `docs/operations/executor_runtime_bootstrap.md`
- `docs/operations/runtime_bootstrap_guide.md`

## Executor runtime alignment

For substantive lane work, the normal tracked execution paths are:
- explicit helper-backed dispatch
- explicit live-subagent dispatch

Helper-backed work may remain non-spawn, but it still requires an explicit
dispatch.

Direct in-session substantive lane work is not a normal execution path.

For small routine helper-backed substantive tasks, prefer the low-friction
micro-dispatch helper:
- `scripts/governor_emit_micro_dispatch.py`
- limit it to clearly low-risk docs/report/evidence maintenance
- do not use it for runtime/core patches, reviewer-gated work, or anything
  that would be medium/high complexity under normal dispatch rules

Parallel tracked work is conservative:
- at most 2 active tasks in the same lane
- dependencies must already have accepted decisions plus concrete completion
  signals (`result.json` completed, outputs present, validation evidence present)
- declared `scope_reservations` must not overlap
- if safety is unclear, serialize

Optional overlap isolation:
- keep the normal lightweight path for non-overlapping work
- use git-worktree overlap isolation only when overlap-parallelism is explicitly
  worth it
- first increment scope: live-subagent `patch` dispatches only
- require explicit `overlap_isolation` metadata, an overlap group, and an
  integration policy (`choose_one` or `can_stack`)
- each isolated candidate gets its own worktree, ephemeral branch, and recorded
  base commit SHA
- executors may package isolated candidates, but they must not integrate them
  into the lane branch
- the governor remains the only integration authority, and integration still
  happens serially on the lane branch
- if the lane branch moved after an isolated candidate was created, do not
  silently integrate it; mark it `stale`, `rebase_needed`, or `superseded` as
  appropriate

Early tracked-work enforcement:
- helper-backed substantive work must pass an early worktree guard before
  `result.json` is persisted
- finalization should fail if uncovered substantive worktree changes remain
- if a tracked dispatch finishes cleanly, the governor should persist
  `governor_decision.json` before any human-facing pause, summary, or handoff
- a human-facing stop must be proposed explicitly through
  `.agent/governor/<lane>/proposed_transition.json` and validated through the
  interrupt gate plus liveness gate; completed subtasks are not legal stop
  reasons by themselves
- context-window rollover is an internal continuation point, not a human
  checkpoint by itself

Before substantive executor work in a fresh or uncertain session:
- run a bounded smoke test from the repo root
- declare one scratch path under `.agent/smoke/`
- verify only declared files were touched
- if the prompt includes an undeclared-path temptation, verify the executor
  refuses it

If the smoke test fails, stop substantive executor-only work until alignment is
repaired.

## Reviewer runtime

The reviewer is a read-only verification role:
- configured in `.codex/agents/reviewer.toml`
- model: `gpt-5.4`
- reasoning effort: `xhigh`
- sandbox: `read-only`

Reviewer rules:
- review executor outputs, diffs, validators, and referenced artifacts
- do not edit files
- do not write dispatch, governor, or merge/integration state
- do not replace deterministic validator gates
- produce structured advisory feedback for the governor
- do not emit workflow-control fields such as `decision`, `recommended_next_action`, or merge-ready signals
- reviewer overreach is a `reviewer_contract_violation`

Helper-backed reviewer path:
- `scripts/reviewer_consume_dispatch.py` can generate or validate `review.json`
- `scripts/governor_finalize_dispatch.py` can trigger reviewer handling for helper-backed dispatches when `review_required = true`
- helper review now fails closed if the reviewer touches repo files or workflow state outside the allowed review artifact path
- helper-backed review is an artifact-driven fallback; the reviewer subagent remains the preferred semantic-review path when available
- live-subagent dispatches with missing review should remain `needs_review` instead of silently substituting helper review

## Heavy-executor alignment

Before relying on escalation:
- confirm `.codex/agents/executor-heavy.toml` names a model the active runtime
  actually supports
- if unsupported, treat that as a runtime-alignment blocker
- do not silently keep retrying on the standard executor while claiming heavy escalation

## Diagnosis vs patch discipline

Executor-backed tasks must declare one of:
- `diagnosis`
- `patch`

Rules:
- prefer diagnosis-first until the failure surface is exact
- retries must carry a `retry_handoff` with the failing key path, source
  schema, and expected artifact/result
- diagnosis tasks must not silently become runtime patches
- patch tasks must not broaden into open-ended diagnosis
- reviewer tasks must stay read-only and must not become hidden fix tasks

## Harness runtime rules

For correctness-sensitive harness work:
- use `abba/.venv/bin/python`
- store live eval and checkpoint artifacts under `.agent/runs/evals/...`
- do not rely on `/tmp` in committed reports
- enforce declared-file scope against tracked and untracked outputs
