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

This provenance is internal only and must not create visible multi-speaker
personas in the transcript.

## Command Boundary
The extension should talk to the project orchestration layer through:
- `python3 orchestration/scripts/orchestrate.py session ...`

It should not depend on individual orchestration implementation scripts as its
public backend interface.
