---
title: Artifact Contracts
purpose: Minimal contracts for recurring artifacts used by the agents, including dispatch and escalation handoff
when_to_read: Read when a task produces a dataset spec, evaluation report, dispatch, handoff, or escalation summary
priority: medium
status: active
---

# Artifact Contracts

## Dataset spec
Should state:
- training unit
- label schema
- split discipline
- source inputs
- exclusions
- hard-label vs weak-label policy
- guard or holdout policy when applicable

## Evaluation report
Should state:
- model/version
- data split used
- metrics
- guard cases
- downstream impact
- offline-only or runtime-impact status
- recommended next bounded task
- durable eval root when the report depends on a live rerun artifact set

## Acceptance review
Should state:
- task_id
- phase
- status
- summary
- files_changed
- artifacts_produced
- truth_surface
- acceptance
- overall_summary
- sample_summaries
- findings
- recommendation

Read-time requirement:
- acceptance-review loaders should validate required keys at read time and fail with the exact missing key path rather than allowing a later KeyError.

## Validation delta
Should state:
- task_id
- before
- after
- delta
- any sample-level deltas when a guarded acceptance flow is involved

Read-time requirement:
- validation-delta loaders should validate required keys at read time and fail with the exact missing key path.

## Review artifact
Should state:
- dispatch_ref
- reviewer_role
- verdict (`pass`, `request_changes`, or `inconclusive`)
- validator_assessment
- scope_assessment
- findings
- residual_risks
- recommendation

Read-time requirement:
- review-artifact loaders should validate required keys at read time and fail with the exact missing key path.

## Checkpoint artifact
Should state:
- checkpoint title / dispatch identity
- status
- completed items
- remaining items when partial
- artifacts produced
- issues encountered
- executor assessment

Storage requirement:
- medium/high-complexity or batched checkpoints should live under `.agent/runs/evals/...` or another declared repo-local durable path, not `/tmp`.

Read-time requirement:
- checkpoint validation should fail early when required sections are missing.

## Dispatch
Should state:
- goal
- task kind
- task track (`diagnosis` or `patch`)
- lane
- scope
- non-goals
- inputs
- expected artifacts
- acceptance criteria
- required validations
- stop conditions
- report format
- whitelist class when bounded autonomy routing depends on it
- loop iteration when the governor is continuing an autonomous sequence
- execution mode
- execution payload summary
- executor run reference and planned file touch list when runtime helpers will execute the task
- autonomy context when the governor is continuing without human input
- human escalation policy when advisor-first or direct escalation boundaries matter
- advisor plan or advisor synthesis summary when advisor-first review influenced the dispatch
- where the task sits in the governor's current bounded plan when that context matters
- retry handoff details when this dispatch is a retry or escalation

## Retry handoff
Should state:
- exact failing validator or gate
- failing artifact path
- exact failing key path
- source schema or contract reference
- expected artifact reference
- expected value summary
- observed value summary
- why the next attempt is still a patch task instead of reverting to diagnosis

## Handoff
Should state:
- what is done
- what is not done
- validations run
- review artifact path or explicit note that review was skipped
- blockers
- artifacts changed
- whether scope was respected
- whether runtime behavior changed
- whether advisor consultation was used
- recommended next bounded task
- authority-boundary note when the result should escalate instead of continue
- whether the next bounded task was chosen by AgentA or deferred for human decision
- exact failure contract when recommending a retry (failing key path, schema, expected artifact)

## Harness enforcement note

For correctness-sensitive harness flows:
- `abba/.venv/bin/python` is the approved interpreter
- live eval artifacts belong under `.agent/runs/evals/...`
- contract-aware loaders should surface file path + exact failing key path on read failure
