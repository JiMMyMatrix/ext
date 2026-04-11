# Transition Contract

Interrupt and continue semantics are orchestration-owned.

## Continue Internal
Routine workflow churn remains internal:
- dispatch emission
- helper-vs-live path resolution
- executor cycles
- reviewer cycles
- expected validation loops
- context rollover
- internal checkpoints

## Human Interrupt
Human interruption is legal only for:
- `merge_ready`
- `lane_complete`
- `material_blocker`
- `missing_permission`
- `missing_resource`
- `human_decision_required`
- `safety_boundary`

## Required Gating
Before a human-facing stop:
- record `proposed_transition.json`
- pass interrupt legality gate
- pass liveness gate

## Non-Truth Metadata
Control-plane metadata remains non-authoritative:
- `proposed_transition.json`
- `lane_status.json`
- `lane_snapshot.json`
- `transition_history.jsonl`
- `lane.lock`
