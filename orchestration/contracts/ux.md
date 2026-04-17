# UX Contract

The VS Code extension is a thin human-facing webview client.

## Context Snapshot
The orchestration layer may provide:
- `lane`
- `branch`
- `task`
- `currentActor`
- `currentStage`
- `accessMode`
- `runState`
- `transportState`
- `pendingApproval`
- `pendingInterrupt`
- `recentArtifacts`
- `snapshotFreshness`

## Renderable Feed Items
- `user_message`
- `shell_event`
- `system_status`
- `actor_event`
- `clarification_request`
- `approval_request`
- `interrupt_request`
- `artifact_reference`
- `error`

## Turn Types
- `governed_work_intent`
- `governor_dialogue`
- `clarification_reply`
- `approval_action`
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
- `approve`
- `full_access`
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
- `approve`
- `decline-or-hold`
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
- `answer-clarification`
  - requires an active clarification
  - requires a fresh matching `context_ref`
- `approve`
  - requires a currently pending approval
  - requires a fresh matching `context_ref`
- `decline-or-hold`
  - requires a currently pending approval
  - requires a fresh matching `context_ref`
- `interrupt`
  - requires an interruptible running session state
  - requires a fresh matching `context_ref`
- `reconnect`
  - requires reconnectable, stale, degraded, or disconnected session state

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
- the controller must not assume a rendered UI card is still valid without
  state confirmation
- this especially applies to:
  - `answer-clarification`
  - `approve`
  - `decline-or-hold`
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

## Command Boundary
The extension should talk to the project orchestration layer through:
- `python3 orchestration/scripts/orchestrate.py session ...`

It should not depend on individual orchestration implementation scripts as its
public backend interface.
