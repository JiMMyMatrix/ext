# UX Contract

The VS Code extension is a thin human-facing client.

## Context Snapshot
The orchestration layer may provide:
- `lane`
- `branch`
- `task`
- `currentActor`
- `currentStage`
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

## User Actions
- `submit_prompt`
- `answer_clarification`
- `approve`
- `decline_or_hold`
- `interrupt_run`
- `reconnect`
- `open_artifact`
- `reveal_artifact_path`
- `copy_artifact_path`

## Authority Boundary
- accepted intake summaries are authoritative only when emitted upstream
- request drafts, shell hints, cached snapshots, and verbose logs are
  informational only
- the extension must not infer actor authority, workflow legality, or progress
  certainty from local state

## Command Boundary
The extension should talk to the orchestration harness through:
- `python3 orchestration/scripts/orchestrate.py session ...`

It should not depend on individual orchestration implementation scripts as its
public backend interface.
