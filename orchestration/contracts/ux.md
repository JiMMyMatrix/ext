# UX Contract

The VS Code extension is a thin human-facing webview client.

## Context Snapshot
The orchestration layer may provide:
- `sessionRef`
- `lane`
- `branch`
- `task`
- `currentActor`
- `currentStage`
- `permissionScope`
- `runState`
- `transportState`
- `pendingPermissionRequest`
- `pendingInterrupt`
- `recentArtifacts`
- `snapshotFreshness`
- `currentWorkRef`
- `currentGoalRef`
- `currentGoalTitle`
- `currentGoalStepRef`
- `currentGoalStepIndex`
- `goalStepCount`
- `goalStatus`
- `goalContinuationState`
- `pendingGoalContinuationRequestRef`
- `latestGoalDecisionRef`
- `currentPlanVersion`
- `currentAttemptNumber`
- `latestReviewRef`
- `latestReviewVerdict`
- `latestGovernorDecisionRef`
- `latestGovernorDecision`

The public model may also expose `planReadyRequest` when Governor planning has
completed for the current accepted intake. The Plan ready card must render from
that authoritative request, not from UI-local guesses based only on stage text.

## Renderable Feed Items
- `user_message`
- `shell_event`
- `system_status`
- `actor_event`
- `clarification_request`
- `permission_request`
- `interrupt_request`
- `artifact_reference`
- `error`

## Turn Types
- `governed_work_intent`
- `governor_dialogue`
- `clarification_reply`
- `permission_action`
- `stop_action`
- `system`

Only governed work-intent turns may proceed toward Governor as work-plane input.
Governor dialogue turns remain read-only by default.

## Clarification Shape
- clarification may be free-text, option-based, or both
- option-based clarification should be preferred when the missing information is
  classifiable
- the UX may render clarification options as buttons/chips before falling back
  to typed input

## User Actions
- `submit_prompt`
- `start_goal`
- `answer_clarification`
- `set_permission_scope`
- `decline_permission`
- `execute_plan`
- `revise_plan`
- `interrupt_run`
- `open_artifact`
- `reveal_artifact_path`
- `copy_artifact_path`

## Session Command Boundary
The extension talks to the orchestration session bridge through transport-level
commands.

Free-text commands:
- `submit-prompt`
- `answer-clarification`
- `start-goal`

Stateful control commands:
- `set-permission-scope`
- `decline-permission`
- `execute-plan`
- `revise-plan`
- `request-goal-revision` (orchestration/CLI goal maintenance; not a default
  user-facing button in V1)
- `interrupt`
- `reconnect`

`submit-prompt` is a transport-level command name only. Its downstream
semantics are determined by `turn_type`:
- `governor_dialogue` means read-only Governor dialogue
- `governed_work_intent` means governed work/intake routing

Implementers must not flatten those two paths together just because they share
the same command name.

## Command Preconditions
Commands are valid only when their declared preconditions hold. Failed
preconditions must fail closed and must not trigger route guessing.

- `submit-prompt`
  - requires non-empty prompt text
  - requires semantic classification to have completed for free-text routing
  - default semantic classification is sidecar-first and may use the persistent
    app-server sidecar runtime; `codex exec` is the explicit legacy fallback
  - requires explicit route metadata such as `turn_type` or a compatible
    `semantic_route_type`
  - must not infer routing from raw prompt keywords when route metadata is absent
  - may use experimental `semantic_mode=governor-first`, where Governor returns
    candidate user-facing copy plus an internal control proposal; orchestration
    must validate the proposal before committing transcript or state changes
  - may omit `session_ref`, including first-turn/bootstrap submission
  - must still carry a unique `request_id`
  - must fail closed if it does provide a mismatched `session_ref`
- `start-goal`
  - creates one authoritative parent goal and an ordered step plan with an
    explicit source (`governor` or deterministic orchestration template)
  - V1 supports one foreground goal at a time and serial step execution
  - each goal step becomes one normal accepted work item with its own `workRef`
  - after a step reaches accepted Governor decision, orchestration may advance
    to the next step without asking the human
  - after the last planned Governor-authored step is accepted, orchestration
    enters `goalContinuationState=pending` and asks Governor whether to
    finalize, extend, or block the goal
  - deterministic orchestration-template goals may finalize automatically to
    preserve command-test compatibility
  - must pause only for permission, clarification, safety/material blocker,
    retry-limit failure, final checkpoint, or a Governor continuation decision
  - goal progress must come from `.agent/goals/<goal_ref>/goal_progress.json`,
    not local UI guesses
- `answer-clarification`
  - requires an active clarification
  - should carry the current `session_ref` once a session exists
  - requires a fresh matching `context_ref`
- `set-permission-scope`
  - requires a currently pending permission request
  - requires a valid `permission_scope`
  - should carry the current `session_ref` once a session exists
  - requires a fresh matching `context_ref`
- `decline-permission`
  - requires a currently pending permission request
  - should carry the current `session_ref` once a session exists
  - requires a fresh matching `context_ref`
- `execute-plan`
  - requires a current `planReadyRequest`
  - should carry the current `session_ref` once a session exists
  - requires the plan-ready `context_ref`
  - is the explicit Execute authorization for the current validated plan
  - must not create a second Execute permission request or permission card
  - must not start execution from any implicit or synthetic prompt
  - must create dispatch truth before
    surfacing a dispatch-queued handoff state
  - in the extension-backed path, should immediately hand startable
    helper-runtime dispatches to Executor after dispatch truth is written
  - must not surface running/Executor state until Executor work has actually
    started
  - keeps Executor as the only substantive writer and Reviewer as read-only
    advisory
  - retry attempts must remain under the same current `workRef`
  - reviewer `request_changes` or material `inconclusive` should route back to
    Governor planning rather than ending the human-visible flow prematurely
- `revise-plan`
  - requires a current `planReadyRequest`
  - should carry the current `session_ref` once a session exists
  - requires the plan-ready `context_ref`
  - stays in Governor planning/dialogue mode and must not enable Executor
- `request-goal-revision`
  - requires an active foreground goal and a current `planReadyRequest`
  - should carry the current `session_ref` once a session exists
  - requires the plan-ready `context_ref`
  - may ask Governor to revise the unfinished goal path under the same
    `goal_ref`
  - must preserve completed steps, increment goal plan version, and must not
    create a new parent goal
- `interrupt`
  - requires an interruptible running session state
  - should carry the current `session_ref` once a session exists
  - requires a fresh matching `context_ref`
- `reconnect`
  - requires reconnectable, stale, degraded, or disconnected session state
  - should carry `session_ref` when reconnect targets a known session

The controller may reject obviously invalid commands locally, but the session
layer remains authoritative for state freshness and legality.

## Request Correlation And Replay
Every controller-originated command carries a unique `request_id`.

- `request_id` must be unique per controller-originated user action
- duplicate replay of the same `request_id` must not be treated as a new action
  silently
- duplicate replay must either:
  - fail deterministically, or
  - be handled idempotently by explicit policy
- if no explicit idempotency rule exists, duplicates fail closed

Request-triggered feed/events should carry `in_response_to_request_id`.
Spontaneous authoritative events must omit it rather than guessing.

If one request produces multiple downstream events, each event in that causal
chain should reuse the same `in_response_to_request_id`.

## State Token Freshness
Commands tied to active session state should carry a current `context_ref`.

- stale or mismatched `context_ref` values must fail closed
- once a session exists, state-bound commands should normally carry `session_ref`
- `submit-prompt` is not state-bound for freshness purposes; it may omit
  `session_ref` so first-turn startup races do not fail solely because the
  local webview has not yet received authoritative session state
- if any command provides a mismatched `session_ref`, the session bridge must
  fail closed
- the controller must not assume a rendered UI card is still valid without
  state confirmation
- this especially applies to:
  - `answer-clarification`
  - `set-permission-scope`
  - `decline-permission`
  - `interrupt`

## Authority Boundary
- accepted intake summaries are authoritative only when emitted upstream
- request drafts, shell hints, cached snapshots, and verbose logs are
  informational only
- the extension must not infer actor authority, workflow legality, or progress
  certainty from local state

## Goal Program Boundary

Goal programs are a parent orchestration layer above existing accepted work:

- `goal.json` is authoritative goal identity and status
- `goal_plan.json` is the authoritative ordered step list; `proposed_by`
  must identify whether the list came from Governor planning or a deterministic
  orchestration test template
- `goal_progress.json` is orchestration-owned progress truth
- each goal step creates a normal accepted intake and `workRef`
- `accepted_intake.json` remains step/intake truth only
- `request.json` remains dispatch truth only
- a parent goal completes only after every step has an accepted Governor
  decision and a final goal decision artifact is recorded
- Governor-proposed plans and deterministic test-template plans must both be
  explicitly sourced; orchestration drives validated step sequencing and must
  not skip blocked or failed steps
- Governor may propose a goal-plan revision, or orchestration may request one,
  but the revision must keep the same `goal_ref`, preserve completed steps,
  increment `goal_plan.plan_version`, and replace only the current/remaining
  unfinished steps
- goal-plan revision is not dispatch truth and must not silently grant
  permission, start Executor, or create a new parent goal

## Internal Provenance
Meaningful feed items should carry internal provenance for traceability and
debugging:
- `source_layer`
- `source_actor`
- `source_artifact_ref`
- `turn_type`
- `semantic_input_version`
- `semantic_summary_ref`
- `semantic_context_flags`
- `semantic_route_type`
- `semantic_confidence`
- `semantic_block_reason`
- `semantic_paraphrase`
- `semantic_normalized_text`
- `in_response_to_request_id`

This provenance is internal only and must not create visible multi-speaker
personas in the transcript.

## Presentation Boundary
Feed items may carry optional presentation metadata:
- `presentation_key`
- `presentation_args`

The extension may use these fields to map non-Governor control-plane events to
controller-owned user-facing copy. Existing `title` and `body` fields remain
fallbacks for compatibility.

- Governor `actor_event` output is already user-facing Governor output and
  should not be remapped unless explicitly required
- semantic provenance, request ids, session refs, context refs, model reasons,
  and artifact/control-plane metadata must not be rendered as normal transcript
  copy
- permission, clarification, system, and error items should prefer mapped
  presentation copy when `presentation_key` is present

## Runtime Ergonomics Kernel
The extension may derive a Runtime Ergonomics Kernel from authoritative
snapshot/feed state before rendering. This kernel is presentation-only.

It may emit normalized activity events with:
- `requestId`
- `workRef`
- `attemptNumber`
- `actor`
- `phase`
- `severity`
- `summaryKey`
- `summaryArgs`
- `visibility`
- `sourceRef`

It may also expose presentation indexes such as transcript, activity, detail,
and internal feed item ids so the webview can avoid re-deriving those
boundaries locally.

The kernel must not create workflow truth, mutate session state, authorize
actions, or replace orchestration validation.

Visibility policy:
- `transcript` is for user messages, Governor prose, and final concise
  human-facing outcomes
- `activity` is for short operational rows such as `Writing`, `Checking`,
  `Revising plan`, or `2 tasks running`; internal actor names stay available
  in hover/detail/source contexts rather than the default reading flow
- `detail` is for artifact-backed sources, runtime timings, dispatch/review
  refs, and advisor output
- `internal` is for request ids, session refs, context refs, semantic reasons,
  app-server ids, protocol payloads, and provenance fields

Routine Executor, Reviewer, dispatch, advisor, validation, retry, and
finalization events should render as brief activity first. Governor prose
remains the main readable transcript layer.

Declared-output recovery is also activity-first. User-facing copy should be
compact, for example `Step needs recovery`, `Restoring declared output`,
`Retrying step`, or `Recovery blocked`. Recovery manifests, baseline blobs,
hashes, dispatch refs, and recovery result artifacts stay behind `View source`
or details.

Actor readouts should use stable presentation keys when the data is available:

- `executor.completed` / `executor.blocked`
- `reviewer.completed` / `reviewer.blocked`
- `governor.final_decision` / `governor.finalization_blocked`

These feed items should include compact `activity` metadata and a
`source_artifact_ref` when a source artifact exists. The compact activity copy is
the default visible surface. Full Executor readouts, Reviewer artifacts,
Governor decision JSON, authorship signatures, dispatch refs, review refs, and
runtime evidence belong behind `View source` or details.

Governor remains the human-facing communicator for work-plane prose, but
orchestration owns the routing of workflow events into transcript, activity,
detail, or internal surfaces. The webview must not promote Executor/Reviewer
artifact bodies into normal transcript prose by guessing from titles.

## Command Boundary
The extension should talk to the project orchestration layer through:
- `python3 orchestration/scripts/orchestrate.py session ...`

It should not depend on individual orchestration implementation scripts as its
public backend interface.
