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

Stateful control commands:
- `set-permission-scope`
- `decline-permission`
- `execute-plan`
- `revise-plan`
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
  - requires explicit route metadata such as `turn_type` or a compatible
    `semantic_route_type`
  - must not infer routing from raw prompt keywords when route metadata is absent
  - may use experimental `semantic_mode=governor-first`, where Governor returns
    candidate user-facing copy plus an internal control proposal; orchestration
    must validate the proposal before committing transcript or state changes
  - may omit `session_ref`, including first-turn/bootstrap submission
  - must still carry a unique `request_id`
  - must fail closed if it does provide a mismatched `session_ref`
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
  - requests Execute permission when the current session scope is below Execute
  - must not silently start execution without Execute permission
  - after Execute permission is confirmed, must create dispatch truth before
    surfacing running/Executor state
  - keeps Executor as the only substantive writer and Reviewer as read-only
    advisory
- `revise-plan`
  - requires a current `planReadyRequest`
  - should carry the current `session_ref` once a session exists
  - requires the plan-ready `context_ref`
  - stays in Governor planning/dialogue mode and must not enable Executor
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

## Command Boundary
The extension should talk to the project orchestration layer through:
- `python3 orchestration/scripts/orchestrate.py session ...`

It should not depend on individual orchestration implementation scripts as its
public backend interface.
