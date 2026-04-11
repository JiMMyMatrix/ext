# Governor / Executor Dispatch Contract

This document defines the dispatch, result, review, and bridge artifact schema.
Use `governor_workflow.md` for sequencing and policy timing, and use
`executor_runtime_bootstrap.md` / `runtime_bootstrap_guide.md` for helper-runtime execution details.

Dispatch directory:

`.agent/dispatches/<cycle>/<scope_type>/<scope_ref>/<dispatch_kind>/<attempt>/`

Canonical identifier:

`dispatch_ref = <cycle>/<scope_type>/<scope_ref>/<dispatch_kind>/<attempt>`

## Request contract

Required request fields:
- `dispatch_ref`
- `from_role`
- `to_role`
- `objective`
- `scope`
- `non_goals`
- `inputs`
- `required_outputs`
- `acceptance_criteria`
- `required_validators`
- `stop_conditions`
- `report_format`

Expected role values:
- `from_role = agentA`
- `to_role = agentB`

Optional but recommended request fields:
- `task_kind`
- `task_track`
- `lane`
- `execution_mode`
- `execution_payload`
- `executor_run`
- `review_required`
- `review_focus`
- `review_artifact_path`
- `advisor_context`
- `retry_handoff`
- `depends_on_dispatches`
- `scope_reservations`
- `overlap_isolation`
- `human_escalation_policy`
- `whitelist_class`
- `loop_iteration`
- `created_at`

If `execution_mode` is omitted, the executor runtime defaults to:
- `manual_artifact_report`

### Lightweight coordination metadata

Use `depends_on_dispatches` for a simple prerequisite list:
- each item names a prior `dispatch_ref`
- a dependent dispatch may start only after each dependency has:
  - `governor_decision.json` with `decision = accept`
  - `result.json` with `status = completed` and no blocker
  - every declared `required_output` present
  - non-empty validation evidence in `result.json.auto_validated`

Use `scope_reservations` for simple declared write scope:
- each item is a file path or directory prefix
- helper-backed claim and live-subagent spawn preparation must stay serialized
  when reservations overlap
- if reservations are missing and parallel safety is unclear, serialize

Use `overlap_isolation` only for the narrow overlapping-candidate case:
- first increment scope: live-subagent `patch` dispatches only
- supported mode: `git_worktree`
- required fields:
  - `mode`
  - `overlap_group`
  - `integration_policy` (`choose_one` | `can_stack`)
- this is optional and does not replace the normal non-overlap path
- it allows overlapping live-subagent patch candidates to run in isolated
  worktrees instead of racing in the lane branch worktree
- it does not grant auto-merge or reviewer integration authority

## Execution modes

Supported execution modes:
- `manual_artifact_report`
- `command_chain`
- `report_only_demo`
- `sample_correctness_chain`
- `sample_acceptance`
- `aggregate_report_refresh`
- `guided_agent`
- `strict_refactor`

Overall contract support is broader than the current helper runtime surface:
- `command_chain`, `manual_artifact_report`, `report_only_demo`, `sample_correctness_chain`, `sample_acceptance`, and `aggregate_report_refresh` are helper-backed in `scripts/executor_consume_dispatch.py`
- `guided_agent` and `strict_refactor` are subagent-governed modes defined by the executor subagent architecture and stay on the live chat-window executor path
- based on the current repo evidence and the current documented workflow, we should not assume that an MCP tool can directly replace live chat-window spawning
- the thin spawn bridge exists to prepare, record, and return the exact live handoff package, not to hide or replace the live spawn boundary

## Governor transition contract

Human-facing stop/continue control uses:
- `.agent/governor/<lane>/proposed_transition.json`
- `docs/governance/lane_completion_rules.json`

`proposed_transition.json` is intent only, not a second workflow truth source.
Workflow truth still comes from:
- `request.json`
- `result.json`
- `review.json` when present
- `governor_decision.json`
- merge-ready truth and overlap-isolation runtime state when relevant

Allowed `transition` values:
- `continue_internal`
- `interrupt_human`

Allowed `requested_stop_reason` values:
- `merge_ready`
- `lane_complete`
- `material_blocker`
- `missing_permission`
- `missing_resource`
- `human_decision_required`
- `safety_boundary`

`continue_internal` requires a machine-readable `next_action`.

`interrupt_human` is legal only when:
- `merge_ready` passes actual merge-ready truth
- `lane_complete` passes the machine-readable lane completion rule
- blocker-style reasons include structured blocker evidence

### `manual_artifact_report`
Use when AgentB completes the bounded task outside the runtime helper and the runtime only needs to:
- claim the dispatch
- attach the executor run
- verify required outputs exist
- write the final dispatch result

Required payload fields:
- `execution_payload.summary`

Recommended payload fields:
- `execution_payload.claims`
- `execution_payload.evidence`
- `execution_payload.notes`
- `execution_payload.next_action`
- `execution_payload.validator_commands`

### `command_chain`
Use when the bounded task can be expressed as explicit commands that the runtime may execute directly.

Required payload fields:
- `execution_payload.commands`

Each command entry may be either:
- a shell-like string, or
- an object with:
  - `argv`
  - `cwd`
  - `timeout_sec`
  - `allow_failure`
  - `name`

Optional payload fields:
- `execution_payload.summary`
- `execution_payload.claims`
- `execution_payload.evidence`
- `execution_payload.notes`
- `execution_payload.next_action`
- `execution_payload.validator_commands`

Low-friction helper-backed routine work:
- use `scripts/governor_emit_micro_dispatch.py` to emit a `command_chain`
  micro-dispatch with low-complexity defaults and derived `executor_run`
  metadata
- keep micro-dispatch limited to clearly low-risk docs/report/evidence
  maintenance
- do not use micro-dispatch for reviewer-gated work, runtime/core patches, or
  anything that would otherwise need a normal medium/high-complexity dispatch

#### Command safety contract

`forbidden_command_patterns`:
- `git push`
- `git merge`
- `git rebase`
- `git reset --hard`
- `rm -rf /`
- `rm -rf /*`
- any command containing both `force` and (`push` or `reset`)

`whitelist_class` semantics:
- `read_only`
- `repo_local_write`
- `full` (requires human override)

Default `whitelist_class`:
- `repo_local_write`

The executor runtime MUST reject any command matching a forbidden pattern before execution.
Rejection is a hard stop, not a warning.

### `report_only_demo`
Use only for narrow runtime-path demonstrations where the dispatch payload already contains the report body the executor should write.

Required payload fields:
- `execution_payload.report`

### `sample_correctness_chain`
Use when AgentB should produce one sample-scoped correctness chain from repo-local review truth plus an existing repo-local evaluation report.

Expected outputs:
- `window_eval.<sample>.json`
- `pairwise_eval.<sample>.json`
- `guard_review.<sample>.json`
- `supervisor_decision.<sample>.json`

Required dispatch shape:
- exactly one sample-scoped `window_eval.<sample>.json` in `required_outputs`
- one `review_labels.json` input
- one repo-local evaluation `report.json` input

### `sample_acceptance`
Use when AgentB should run the stable acceptance harness for a supported sample flow and produce the committed review/checkpoint/validation-delta trio.

Current support:
- `sample6`
- `sample3`

Required payload fields:
- `execution_payload.sample_id`

Required dispatch shape:
- `execution_payload.sample_id` must name a supported normalized acceptance flow
- `required_outputs` must include the acceptance review JSON, checkpoint markdown, and validation-delta JSON expected from the stable runner

Helper-runtime behavior:
- the runtime executes `scripts/run_sample_acceptance.py --sample <sample_id>`
- the dispatch cannot complete until the checkpoint artifact exists and passes checkpoint contract validation
- acceptance review and validation-delta artifacts must also pass read-time contract validation

### `aggregate_report_refresh`
Use when AgentB should refresh aggregate report-only governance artifacts from already-produced sample-scoped chains.

Expected outputs:
- `reports/supervisor_summary.multi_sample.json`
- `reports/shadow_artifact_audit.json`
- `reports/guard_review.aggregate.json`
- `reports/supervisor_decision.aggregate.json`
- `reports/phase_snapshot.aggregate.json`

Required dispatch shape:
- sample-scoped `window_eval.<sample>.json` inputs for the chains that should be included in the aggregate refresh

### `guided_agent`
Use when the task requires code comprehension and localized edits that cannot
be expressed as explicit shell commands, but can be decomposed into ordered
read/edit steps with explicit constraints.

Required payload fields:
- `execution_payload.plan_steps` (ordered list of step objects)
- `execution_payload.declared_files` (list of file paths the executor may touch)
- `execution_payload.validation` (tier definitions with commands and timeouts)

For runtime patch dispatches in `guided_agent` mode:
- `execution_payload.declared_files` is the full write authority
- every runtime, test, script, report, and checkpoint path the executor may touch MUST be listed there
- any undeclared file touch invalidates the result, even if validation passes

Each step object must include:
- `step` (integer, execution order)
- `action` (`read` or `edit`)
- `target` (file path)
- `purpose` (for read steps) or `instruction` + `constraints` (for edit steps)

Optional payload fields:
- `execution_payload.turn_limit` (default: 15)
- `execution_payload.diff_limit` (default: 200 lines)
- `execution_payload.injected_weakness_guards` (list of weakness IDs)
- `execution_payload.summary`
- `execution_payload.next_action`

### `strict_refactor`
Use when the change must be strictly behavior-preserving and the test suite
is the source of truth for "behavior unchanged."

Required payload fields:
- `execution_payload.refactor_type` (e.g., `extract_function`, `rename_symbol`, `move_code`)
- `execution_payload.instruction` (what to refactor)
- `execution_payload.target_files` (list of file paths)
- `execution_payload.baseline_command` (test command to run before the change)
- `execution_payload.post_command` (test command to run after the change)

Optional payload fields:
- `execution_payload.turn_limit` (default: 10)
- `execution_payload.diff_limit` (default: 300 lines)
- `execution_payload.injected_weakness_guards` (list of weakness IDs)

Commit is allowed ONLY if baseline and post-change test results are identical
(same test count, same pass/fail per test). Any change in test status
(including fail→pass) must be reported as `blocker = "behavior_change_detected"`.

## Executor run contract

If `executor_run` is present, it should include:
- `run_ref`
- `objective`
- `scope`
- `read_list`
- `produce_list`
- `planned_file_touch_list`
- `non_goals`
- `stop_conditions`

`run_ref` should point to:

`.agent/runs/<cycle>/<scope_type>/<scope_ref>/<artifact_kind>/<attempt>/`

## Advisor context contract

`advisor_context` should capture bounded specialist usage, not delegation of authority.

Recommended fields:
- `consultations`: list of brief provider/summary records
- `artifact_refs`: list of repository artifact paths summarizing advisor output

## Review contract

Reviewer-aware dispatches may include:
- `review_required`: boolean
- `review_focus`: list of specific claims or risks the reviewer should verify
- `review_artifact_path`: repo-local path where the structured review artifact should be written or copied

Recommended review artifact location:
- `.agent/reviews/<dispatch_ref>/review.json`

Review artifact fields:
- `dispatch_ref`
- `reviewer_role`
- `verdict` (`pass` | `request_changes` | `inconclusive`)
- `validator_assessment`
- `scope_assessment`
- `findings`
- `residual_risks`
- `recommendation`

Decision rule:
- reviewer output is advisory; the governor remains the final decider
- reviewer output must not contain workflow-control fields such as
  `decision`, `recommended_next_action`, `recommended_next_bounded_task`, or
  merge-ready signals
- hard validator failures are not overridable by review
- for live-subagent dispatches, missing review should remain `needs_review` instead of silently materializing helper review

## Spawn bridge contract

Live-subagent dispatches may carry an additional sidecar artifact:

- `.agent/dispatches/<dispatch_ref>/spawn_bridge.json`

Purpose:
- make the dispatch-to-live-spawn boundary explicit and machine-readable
- resolve helper-backed vs live-subagent path
- prepare the exact executor or reviewer handoff package
- record whether the governor has already crossed the live spawn boundary

This artifact is not required for initial dispatch validity.
Fresh `guided_agent` and `strict_refactor` dispatches remain valid immediately
after `request.json` and `state.json` are emitted.

The bridge artifact becomes required only at the live-execution-ready
boundary, after the governor calls the spawn bridge and before the governor
treats live-subagent work as started.

Expected `spawn_bridge.json` fields:
- `dispatch_ref`
- `execution_mode`
- `resolved_path` (`helper_runtime` | `live_subagent`)
- `review_required`
- `bridge_stage`
- `last_action`
- `executor_handoff_ref`
- `reviewer_handoff_ref`
- `overlap_isolation_ref`
- `spawn_records`

Recommended companion handoff artifacts:
- `.agent/dispatches/<dispatch_ref>/executor_handoff.txt`
- `.agent/dispatches/<dispatch_ref>/reviewer_handoff.txt`

Optional overlap-isolation companion artifacts:
- `.agent/dispatches/<dispatch_ref>/overlap_isolation.json`
- `.agent/dispatches/<dispatch_ref>/candidate.patch`

Expected `overlap_isolation.json` fields:
- `dispatch_ref`
- `originating_dispatch_ref`
- `lane`
- `lane_branch`
- `lane_repo_root`
- `mode` (`git_worktree`)
- `overlap_group`
- `integration_policy` (`choose_one` | `can_stack`)
- `base_commit_sha`
- `ephemeral_branch`
- `worktree_path`
- `status`

Optional overlap-isolation fields:
- `candidate_artifact_ref`
- `candidate_commit_sha`
- `candidate_changed_files`
- `integrated_commit_sha`
- `superseded_by_dispatch_ref`

Status semantics:
- `prepared`: isolated worktree exists; candidate not yet packaged
- `candidate_ready`: candidate patch is packaged and awaiting governor decision
- `integrated`: governor integrated the candidate serially on the lane branch
- `stale`: lane branch moved before safe integration and no automatic stack rule applies
- `rebase_needed`: lane branch moved and `can_stack` requires explicit rebase/revalidation
- `superseded`: another `choose_one` candidate in the same overlap group was integrated first
- `discarded`: governor intentionally declined the candidate
- `cleaned`: terminal candidate plus worktree / ephemeral-branch cleanup completed

Isolation rules:
- `overlap_isolation.json` is runtime metadata only; workflow truth still comes
  from `request.json`, `result.json`, `review.json` when present, and
  `governor_decision.json`
- isolated candidate packaging must fail closed on out-of-scope substantive
  changes or workflow-state drift inside the isolated worktree
- executors may prepare isolated candidates, but they must not integrate them into the lane branch
- reviewer may compare isolated candidates, but remains advisory only
- governor integration requires a completed `result.json` plus an accepted
  `governor_decision.json`; the sidecar alone is not enough authority to integrate
- the governor chooses whether to integrate, discard, or leave a candidate unresolved
- after governor integration, targeted validation must run again on the lane branch

## Governor decision contract

When a dispatch reaches final governor acceptance/rejection, the helper-backed
runtime may write:

- `.agent/dispatches/<dispatch_ref>/governor_decision.json`

Required decision fields:
- `dispatch_ref`
- `result_ref`
- `decision` (`accept` | `reject` | `needs_review` | `needs_verification`)
- `reason`
- `recommended_next_action`

Optional decision fields:
- `review_ref`

Decision artifact rules:
- helper-backed reviewer flows should persist the final governor decision in this artifact
- `review_ref` should point to the structured review artifact when one exists
- the decision artifact records the governor outcome; it does not replace `result.json` or `review.json`

## Cycle identity contract

When advisor tools or other bounded external systems require `cycle_id`:
- `cycle_id` MUST equal the active `dispatch_ref`, or
- `cycle_id` MUST equal `governor/<timestamp>` if no dispatch is active

## Human escalation policy contract

`human_escalation_policy` defines when the governor may ask the human.

Recommended fields:
- `advisor_first_required`
- `allowed_without_advisors`
- `note`

Default posture:
- training-direction ambiguity should go to bounded advisor consultation first
- human escalation is reserved for authority boundaries, safety boundaries, missing required inputs, or unresolved post-advisor deadlock

## Result contract

Required result fields:
- `dispatch_ref`
- `status`
- `executor_run_refs`
- `written_or_updated`
- `auto_validated`
- `blocker`
- `recommended_next_bounded_task`
- `runtime_behavior_changed`
- `scope_respected`

Allowed result status values:
- `completed`
- `partial`
- `blocked`
- `failed`

Optional result fields:
- `notes`
- `failure_category`
- `review_artifact_refs`

## Harness enforcement contract

Correctness-sensitive helper/runtime work must use the approved interpreter:
- `abba/.venv/bin/python`

Helper/runtime scope enforcement is post-hoc and hard-failing:
- tracked file modifications outside the declared file set are `scope_violation`
- untracked file creation outside the declared file set is `undeclared_untracked_output`
- internal helper artifacts under declared `.agent/dispatches/...`, `.agent/runs/...`, and `.agent/runs/evals/...` paths may be ignored only when they are part of the declared runtime surface

Durable eval/checkpoint storage rules:
- live eval artifacts and medium/high-complexity checkpoint artifacts should be written to repo-local durable paths
- `.agent/runs/evals/<flow>/<run_ref-or-timestamp>/...` is the canonical default root
- committed reports may summarize those reruns, but must not depend on `/tmp` paths

## Escalation, Decomposition & Communication Fields

These fields extend the dispatch payload to support executor model escalation (E1),
task decomposition (E2), and structured communication (E3) as defined in
executor_escalation_spec.md.

### Complexity estimation (governor-assigned)

| Field | Type | Required | Description |
|---|---|---|---|
| estimated_complexity | enum: low / medium / high | yes | Governor's assessment of task complexity |

Criteria:
- **low:** single file, < 50 lines changed, well-defined task. No checkpoint required, no execution plan.
- **medium:** 2-3 files, or 50-200 lines, or moderate ambiguity. Checkpoint artifact required, execution plan recommended.
- **high:** 4+ files, or > 200 lines, or cross-module, or long-running. Checkpoint + execution plan required, decomposition strongly recommended.

### Escalation fields (E1, governor-managed)

| Field | Type | Required | Description |
|---|---|---|---|
| attempt_number | integer (1-3) | yes | 1 = first try on the standard executor, 2 = first escalation, 3 = final |
| escalated | boolean | yes | true if this dispatch is an escalation from a prior failure |
| escalation_context | object | only when escalated = true | Prior attempt history and failure context |

escalation_context structure:
- prior_attempts: array of {attempt, executor, model, eval_result, eval_feedback, files_touched}
- original_dispatch_ref: string — the dispatch_ref of the first attempt
- cumulative_failure_summary: string — governor's 2-3 sentence synthesis of what went wrong

### Task decomposition fields (E2, governor-managed)

| Field | Type | Required | Description |
|---|---|---|---|
| batch_context | object | only for decomposed tasks | Batch identification and checkpoint tracking |

batch_context structure:
- parent_dispatch_ref: string — the dispatch_ref of the parent task
- batch_id: string — e.g. "B01", "B02"
- batch_total: integer — total number of batches
- batch_scope: string — human-readable description of what this batch covers
- prior_batch_checkpoints: array of {batch_id, status, checkpoint_artifact}
- required_checkpoint_artifact: string — path where executor must write checkpoint

### Execution plan fields (E3, governor-authored)

| Field | Type | Required | Description |
|---|---|---|---|
| execution_plan | object | required when estimated_complexity >= medium | Step-by-step plan for executor to validate and follow |

execution_plan structure:
- steps: array of {id, description, expected_output, estimated_minutes}
- total_estimated_minutes: integer
- checkpoint_after_step: integer — executor must produce checkpoint after this step

### Task-track fields (governor-authored)

| Field | Type | Required | Description |
|---|---|---|---|
| task_track | enum: diagnosis / patch | required for executor-backed implementation work | Separates evidence-building work from behavior-changing work |

Task-track rules:
- **diagnosis:** report-only comparison, artifact generation, bounded instrumentation, or failure-surface isolation. Runtime behavior changes are not allowed unless the dispatch explicitly authorizes behavior-neutral instrumentation.
- **patch:** localized implementation meant to resolve a previously isolated failure surface. Patch dispatches MUST cite the diagnosis artifact or retry handoff that defines what is being fixed.

### Retry-handoff fields (governor-authored)

| Field | Type | Required | Description |
|---|---|---|---|
| retry_handoff | object | required when retrying a failed diagnosis/patch task or escalating after Tier 3 failure | Exact failure contract for the next attempt |

retry_handoff structure:
- failing_validator: string — exact validator or gate that failed
- failing_artifact_path: string — artifact path that exposed the failure
- failing_key_path: string — exact JSON/path-style location of the failure
- source_schema_ref: string — schema or contract document that defines the expected shape
- expected_artifact_ref: string — artifact/template/reference showing the expected result
- expected_value_summary: string — concise statement of what should have been present
- observed_value_summary: string — concise statement of what was actually present

Retry-handoff rule:
- if the governor cannot specify exact failing_key_path, source_schema_ref, and expected_artifact_ref, the next task SHOULD stay in `diagnosis` track rather than retrying a `patch` track blindly

Checkpoint validation rule:
- a medium/high-complexity or batched dispatch does not complete successfully until the required checkpoint artifact exists and passes checkpoint contract validation

## State contract

Required state fields:
- `dispatch_ref`
- `status`
- `claimed_by`
- `claimed_at`
- `run_ref`
- `result_ref`
- `last_transition_at`
- `transition_history`
- `notes`

Supported state values:
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

Terminal states:
- `completed`
- `escalated`

## Escalation contract

Required escalation fields:
- `dispatch_ref`
- `from_role`
- `to_role`
- `escalation_type`
- `reason`
- `artifacts_consulted`
- `recommended_human_decision`
- `forbidden_until_decided`

Allowed escalation types:
- `blocker`
- `milestone_boundary`
- `authority_boundary`
- `loop_budget_exhausted`
- `conflicting_policy`
- `safety_boundary`
- `missing_required_input`

## Validation expectations

The dispatch contract is valid only if:
- JSON parses successfully
- required fields are present
- `dispatch_ref` matches across request/state/result/escalation when multiple files exist
- roles and enum values are valid
- state transitions are legal when transition history is present
- `queued`, `claimed`, and `running` states do not already carry terminal result or escalation artifacts
- `validated` state does not already carry a terminal `result.json`
- `completed` state carries `result.json` and a matching `result_ref`
- `escalated` state carries `escalation.json`
- `run_ref` points to an existing run directory when execution occurred
- execution payload shape matches the declared execution mode

The dispatch contract does not replace executor run validation.
Dispatch validation and run validation are both required when both artifact types are used.
