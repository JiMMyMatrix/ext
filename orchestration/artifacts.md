# Artifact Model

## Workflow Truth
These remain the authoritative workflow-truth artifacts:
- `request.json`
- `result.json`
- `review.json`
- `governor_decision.json`

`request.json` remains dispatch truth only.

## Intake Artifacts
These are distinct from dispatch truth:
- `raw_human_request.md`
- `request_draft.json`
- `accepted_intake.json`

Rules:
- `raw_human_request.md` is the verbatim human request record.
- `request_draft.json` is non-authoritative Intake output.
- `accepted_intake.json` is the canonical accepted intake artifact.
- `accepted_intake.json` is intake-level truth, not dispatch truth.

## Control-Plane Metadata
These are not workflow truth:
- `proposed_transition.json`
- `lane_status.json`
- `lane_snapshot.json`
- `transition_history.jsonl`
- `lane.lock`
- similar orchestration metadata

## UX Interpretation Rules
Treat as authoritative only when explicitly produced upstream:
- accepted intake summary
- explicit actor/stage/status
- active approval/interrupt requests
- artifact references tied to accepted backend artifacts

Treat as informational only:
- request drafts
- shell hints
- cached snapshots
- verbose logs
- local UI state
- progress estimates unless upstream explicitly marks them authoritative
