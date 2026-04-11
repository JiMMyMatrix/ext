# Runtime / Bootstrap Guide

## Purpose

This guide bootstraps the helper-backed Governor/Executor runtime for the current governance architecture.

## Minimal dispatch lifecycle

1. Governor emits a dispatch.
2. Governor calls the thin spawn bridge.
3. If the dispatch stays helper-backed, executor runtime claims it.
4. If the dispatch is live-subagent-managed, the bridge prepares the handoff and the governor spawns in the live chat window.
5. A run directory is scaffolded or reused.
6. The bounded task executes in one of the supported execution modes.
7. Required outputs are checked.
8. Run contract and dispatch contract are validated.
9. Result or escalation is written.
10. If review is required, the governor finalizer triggers helper review only for helper-backed flows before the final decision.
11. The finalizer writes `governor_decision.json`.
12. If the dispatch finished cleanly, the governor finalizes it before any
    human-facing pause, summary, or handoff.
13. If the governor wants to stop after that point, it must record a proposed
    transition and pass the interrupt/liveness gates; a completed subtask is
    not a legal stop reason by itself.

Context-window rollover or session handoff is an internal continuation point,
not a human checkpoint by itself.

## Supported execution modes

This guide covers the helper-backed runtime surface in `scripts/executor_consume_dispatch.py`.
The overall dispatch contract also defines `guided_agent` and `strict_refactor`, but those are subagent-managed modes and are not executed by this helper.
Based on the current repo evidence and the current documented workflow, we
should not assume that an MCP tool can directly replace live chat-window
spawning.

Use `command_chain` for:
- deterministic script-driven diagnostics
- reproducible evaluation commands
- bounded validator-backed repair scripts

Use `manual_artifact_report` for:
- tasks primarily completed by AgentB directly
- tasks where the runtime should only attach outputs and finalize lifecycle state

Use `sample_correctness_chain` for:
- sample-scoped report-only correctness chains from repo-local truth plus one existing evaluation report

Use `aggregate_report_refresh` for:
- aggregate report-only refreshes built from existing sample-scoped chains

Use `report_only_demo` only for:
- narrow runtime demonstrations

If `execution_mode` is omitted, the executor currently defaults to `manual_artifact_report`.

## Governor emit example

The example below shows a current helper-backed `command_chain` dispatch shape.

For very small routine helper-backed substantive work, use the low-friction
wrapper instead of rebuilding the full emit command by hand:

```bash
python3 scripts/governor_emit_micro_dispatch.py \
  --dispatch-ref c07/repo/docs/workflow-note/a01 \
  --objective "Refresh one bounded workflow note." \
  --lane workflow_upgrade \
  --scope "docs/operations/governor_workflow.md" \
  --required-output "docs/operations/governor_workflow.md" \
  --command "python3 scripts/refresh_workflow_note.py"
```

Keep micro-dispatch limited to low-risk docs/report/evidence maintenance.
If the task touches runtime/core code, needs reviewer gating, or is no longer
obviously low-complexity, switch back to the normal dispatch path.

```bash
python3 scripts/governor_emit_dispatch.py \
  --dispatch-ref sample5_window_birth.c01/repo/window-birth-context/failure_diagnostic/a01 \
  --objective "Inspect the sample5 false early window and write a bounded diagnostic." \
  --task-kind failure_diagnostic \
  --lane sample5_window_birth_context_diagnosis \
  --scope "Diagnose sample5 early-window birth without changing runtime behavior." \
  --non-goal "Do not modify runtime behavior in this dispatch." \
  --input "reports/sample5_window_birth_patch_guard_review.json" \
  --required-output "reports/sample5_window_birth_context_diagnostic.json" \
  --acceptance-criterion "The diagnostic report explains the candidate window-birth path and references the bounded evidence used." \
  --required-validator "python3 -m py_compile scripts/inspect_sample5_window_birth_context.py" \
  --stop-condition "Escalate if the next defensible move would broaden beyond the active sample5 lane." \
  --execution-mode command_chain \
  --command "python3 scripts/inspect_sample5_window_birth_context.py" \
  --validator-command "python3 -m py_compile scripts/inspect_sample5_window_birth_context.py" \
  --executor-run-ref sample5_window_birth.c01/repo/window-birth-context/failure_diagnostic_executor/a01
```

## Executor consume example

```bash
python3 scripts/executor_consume_dispatch.py --root .
```

Or consume a specific dispatch:

```bash
python3 scripts/executor_consume_dispatch.py \
  --dispatch-dir .agent/dispatches/c07/repo/event-normalization-dataset/dataset_refresh/a01 \
  --root .
```

The helper runtime only starts dispatches that are startable:
- dependencies listed in `depends_on_dispatches` must already be accepted
- acceptance alone is not enough; the dependency also needs completed result
  state, required outputs present, and validation evidence
- declared `scope_reservations` must not overlap active same-lane work
- same-lane helper-backed active concurrency stays capped at 2
- unclear cases stay serialized

## Governor finalize example

For a reviewer-gated completed dispatch:

```bash
python3 scripts/governor_finalize_dispatch.py \
  --dispatch-dir .agent/dispatches/c07/repo/event-normalization-dataset/dataset_refresh/a01
```

This helper:
- checks whether review is required
- triggers `scripts/reviewer_consume_dispatch.py` only for helper-backed review paths when needed
- writes `governor_decision.json` based on `result.json` plus `review.json`
- keeps the reviewer read-only and separate from executor lifecycle writes
- fails closed with `reviewer_contract_violation` if reviewer execution touched repo files or workflow/state artifacts outside the allowed review path
- returns `needs_review` for missing live-subagent review instead of silently materializing helper review
- should be run before any human-facing pause when a helper-backed dispatch has
  finished cleanly and no real blocker remains
- does not by itself authorize a human-facing stop; the governor still needs a
  valid proposed transition plus passing interrupt/liveness gates

Before telling the human a branch is ready or before merging, run:

```bash
python3 scripts/check_lane_merge_ready.py --lane <active-lane>
```

That gate requires:
- clean worktree
- changed substantive files covered by accepted dispatch scope
- no unresolved `needs_review` / `needs_verification` or still-active lane dispatches
- accepted supporting dispatches to still have real completion signals

## Validation checklist

Always validate:
- run contract
- dispatch contract
- any task-specific validator commands declared in the dispatch
- any schema or correctness validators required by the selected execution mode

## Escalation checklist

Escalate instead of improvising when:
- required outputs cannot be produced inside scope
- a command fails and the task cannot be narrowed safely
- policy requires human approval
- the next step would change behavior outside active lane authority or break the active guard policy
- advisors were consulted and still no bounded decision is defensible
