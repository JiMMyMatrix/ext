# Core Principles

## Primary Goal
Make the remote Codex agent obey the user's harness rules.

## Governing Rules
- Substantive governed work is dispatch-first.
- New feature work, debugging, and refactors live on dedicated branches/lane
  surfaces, not on the integrated baseline by default.
- Routine internal work loops should continue silently without human
  interruption.
- `checkpoint != pause`.
- Context rollover is an internal continuation point, not a human stop.
- Finalize clean completed work before any human-facing pause.
- Only interrupt the human for a real blocker, authority boundary, safety
  boundary, or merge checkpoint.
- Reviewer feedback is advisory only.
- Advisor output is advisory only.
- Workflow truth stays artifact-based.

## Enforcement Principle
Important harness rules should be aligned across:
- policy docs
- model-facing prompts and skills
- runtime role/config constraints
- fail-closed lifecycle code

If a high-risk rule exists in only one of those places, the orchestration layer
is weak.

## What Must Not Happen
- UX becoming a hidden operator/governor
- Intake becoming a hidden governor
- Orchestration inventing work-plane decisions that Governor did not authorize
- Executor becoming a planner
- Reviewer becoming a second governor
- routine progress updates being treated as legal human-stop reasons
- request drafts or local cache being treated as workflow truth
