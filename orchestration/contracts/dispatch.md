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
- Parallel metadata such as `parallel_set_ref`, `parallel_group`,
  `parallel_intent`, `scope_reservations`, `depends_on_dispatches`,
  `resource_hints`, and `pre_dispatch_review_*` is scheduling/control metadata
  only; it does not replace dispatch truth or create independent work truth.
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
- helper-backed file-producing dispatches may opt into
  `authorship_evidence.required = true`; when enabled, Executor completion must
  include before/after `output_signatures` proving each declared
  `required_outputs` entry was created or mutated during the run
- unchanged required outputs fail closed unless the Governor explicitly declares
  that output in `authorship_evidence.idempotent_output_allowed`
- `governor_decision.json` must not accept a file-producing attempt whose
  authorship evidence is missing, stale, blocked, or unverifiable
- after the bounded retry limit is reached, the work bundle status must become
  blocked with an explicit `revision_limit_reached` reason rather than staying
  in a replan-ready state
- conservative parallelism is opt-in and must fail closed when scope,
  dependency, pre-dispatch review, or resource safety is unclear

## Conservative Parallelism
- Default execution is serial.
- V1 supports at most two active same-lane dispatches.
- The Governor may split one accepted work family into a reviewed parallel set
  only by writing member `request.json` artifacts that share the same
  `work_ref`, `lane`, and `parallel_set_ref`.
- The reviewed set artifact lives at
  `.agent/parallel_sets/<parallel_set_ref>/parallel_dispatch_set.json` and must
  declare `parallel_set_ref`, `work_ref`, `lane`, `dispatch_refs`, `intent`,
  `max_active`, `review_artifact_path`, and `created_at`.
- Every member dispatch must declare non-empty `scope_reservations`,
  `pre_dispatch_review_required = true`, and a repo-local
  `pre_dispatch_review_artifact_path`.
- Set-level review lives at
  `.agent/reviews/<parallel_set_ref>/pre_dispatch_review.json` and must have
  `review_phase = pre_dispatch`, `verdict = pass`, and
  `covered_dispatch_refs` matching the set members.
- Non-overlapping scopes use the normal dispatch path.
- Overlapping patch candidates may run in parallel only with explicit
  `overlap_isolation` metadata and the existing git-worktree isolation path.
- Executor integration remains forbidden; Governor fan-in and integration are
  serial even when execution was parallel.

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
