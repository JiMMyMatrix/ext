---
title: Reviewer Subagent Spec
purpose: Rules for the read-only reviewer subagent that verifies executor outputs, diffs, and validation evidence before governor decisions
when_to_read: Read when dispatching a reviewer task, interpreting reviewer feedback, or resolving executor-reviewer disagreement
priority: high
status: active
---

# Reviewer Subagent Spec

> This document defines the reviewer as a read-only verification role that
> sits between executor completion and the governor's final accept/reject
> decision.

Read this document together with:
- `docs/operations/governor_workflow.md` for the canonical review timing inside the governor loop
- `docs/operations/governor_executor_dispatch_contract.md` for `review.json` and `governor_decision.json` contracts

## 1. Role definition

- The reviewer is configured in `.codex/agents/reviewer.toml`.
- The reviewer runs `gpt-5.4` with `model_reasoning_effort = "xhigh"`.
- The reviewer is read-only and advisory only.
- The reviewer is not a second writer and not a second governor.

Core split of responsibilities:
- governor decides
- executor writes
- reviewer verifies

## 2. What the reviewer checks

The reviewer should focus on evidence that is difficult to reduce to simple
validator gates:
- semantic correctness of the claimed result
- mismatch between code changes and the executor's summary
- weak, incomplete, or suspicious validation coverage
- regression risk not fully exercised by the chosen validators
- declared-file and scope compliance as reflected in the task package

The reviewer should not duplicate simple deterministic checks that already have
validator support unless the validator output itself looks suspect.

## 3. Required inputs

A reviewer task should include, at minimum:
- the executor summary/result
- the validator outputs or references to them
- the diff or touched-file list
- the key artifacts the executor claims justify completion
- optional `review_focus` bullets from the governor

## 4. Standard review output

The reviewer should return a structured review artifact with:
- `verdict`: `pass` | `request_changes` | `inconclusive`
- `validator_assessment`
- `scope_assessment`
- `findings`
- `residual_risks`
- `recommendation`

Recommended artifact location:
- `.agent/reviews/<dispatch_ref>/review.json`

Helper-backed fallback:
- `scripts/reviewer_consume_dispatch.py` may generate or validate the same
  structured `review.json` artifact for reviewer-gated helper flows
- `scripts/governor_finalize_dispatch.py` consumes that artifact and writes
  `governor_decision.json`
- `review.json` stays advisory-only and must not carry workflow-control fields
  such as `decision`, `recommended_next_action`, or merge-ready signals
- this fallback keeps the reviewer read-only, but the configured reviewer
  subagent remains preferred for deeper semantic review
- for live-subagent dispatches, missing review should remain `needs_review`
  rather than silently materializing helper review

## 5. When review is required

Review should be the default for:
- `task_track = patch`
- medium/high-complexity tasks
- changes under `core/`, harness/runtime scripts, dispatch/runtime contracts, or agent prompts

Review may be skipped for:
- low-complexity docs-only tasks
- low-risk report-only artifact refreshes
- tiny governance/index alignment tasks with no runtime behavior change

## 6. Disagreement handling

Evidence outranks role rank.

Decision rules:
- validator failure => automatic reject; reviewer cannot override it
- reviewer `pass` => governor may still reject on policy, lane, or acceptance grounds
- reviewer `request_changes` => governor should usually redispatch or verify the finding unless the review is clearly unsupported by artifacts
- reviewer `inconclusive` => governor should prefer a bounded verification step rather than guess
- executor and reviewer disagreement on facts => governor should request a bounded reproduction or narrower verification, not decide by intuition alone

## 7. Hard boundaries

The reviewer must not:
- edit files
- write dispatch, governor, or merge/integration state
- rerun work in a way that mutates the repository
- redefine task scope
- approve merge/push
- replace governor authority

Reviewer overreach is a `reviewer_contract_violation`.
The governor should ignore unauthorized reviewer control or state writes and
decide the next step itself.

The executor remains the single substantive writer even when review is active.
