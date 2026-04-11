# Dispatch Contract

Dispatch truth starts after intake acceptance.

## Authoritative Dispatch Artifacts
- `request.json`
- `result.json`
- `review.json`
- `governor_decision.json`

## Important Boundary
- `request.json` remains dispatch truth only.
- Intake must never write `request.json`.
- `accepted_intake.json` is canonical intake input, not dispatch truth.

## Ownership
- Governor owns dispatch intent.
- Orchestration may technically launch actors, but only from Governor-owned
  work intent.
- Executor is the single substantive writer under dispatch.
- Reviewer is advisory and read-only.

## Fail-Closed Expectations
- substantive governed work without dispatch is a workflow violation
- finalization must produce `governor_decision.json` before any human-facing
  pause unless a real blocker prevents finalization
- reviewer output never overrides failed validators

## Current Orchestration Port Status
- helper-runtime modes currently shipped:
  - `command_chain`
  - `manual_artifact_report`
- live-subagent modes preserved:
  - `guided_agent`
  - `strict_refactor`
- currently unavailable in the stabilized orchestration helper runtime:
  - `report_only_demo`
  - `sample_correctness_chain`
  - `aggregate_report_refresh`
  - `sample_acceptance`

Unavailable modes must fail closed as `unsupported_in_orchestration_port`.
