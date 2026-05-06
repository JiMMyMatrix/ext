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
- Work-loop bundle artifacts under `.agent/work/` may group plan versions,
  attempts, reviews, and decisions for one accepted problem, but they do not
  replace dispatch truth.
- Optional `request.json` fields `work_ref`, `plan_ref`, `plan_version`,
  `attempt_number`, and `revision_of_dispatch_ref` are linkage metadata only.
- A work bundle has exactly one accepted problem identity (`work_ref`) and may
  contain up to three dispatch attempts for that problem before escalation.
- Reviewer `request_changes` and material `inconclusive` verdicts return the
  same `work_ref` to Governor planning; they must not create a new unrelated
  intake by default.

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
- `governor_decision.json` with `accept` is required before an attempt is
  treated as accepted
- retry attempts must increment `attempt_number`, target the latest validated
  plan version, and link to the previous attempt through
  `revision_of_dispatch_ref`
- after the bounded retry limit is reached, the work bundle status must become
  blocked with an explicit `revision_limit_reached` reason rather than staying
  in a replan-ready state

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
