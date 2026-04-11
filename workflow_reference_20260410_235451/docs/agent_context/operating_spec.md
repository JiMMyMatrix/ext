---
title: Operating Spec
purpose: General operating rules for bounded task execution and review
when_to_read: Read for all non-trivial tasks after reading AGENTS.md, docs/governance/README.md, and INDEX.md
priority: high
status: active
---

# Operating Spec

## Task loop
1. Read `AGENTS.md`, `docs/governance/README.md`, and the applicable governing documents.
2. Identify the active lane.
3. Define one bounded task.
4. Execute only within the stated scope.
5. Validate results.
6. If required, collect structured review feedback.
7. Produce a structured handoff.
8. Commit only if commit conditions are satisfied.

## Lane branch discipline
- If a task opens a new lane, create a dedicated lane branch before substantive work starts.
- Keep substantive lane implementation, diagnostics, and bounded checkpoints on that lane branch until they are ready to merge.
- Treat `main` as the integrated baseline branch.
- When a lane reaches a clean bounded checkpoint, merge that lane branch back into `main` instead of leaving the lane stranded.
- Do not start a new lane directly on `main` unless the human explicitly authorizes that exception.

## Communication mode
- If the human says `quiet mode`, skip routine progress updates and keep user-facing interruption to the narrow set of:
  - material results
  - commit-ready checkpoints
  - lane-ceiling conclusions
  - real blockers
- Quiet mode does not relax escalation discipline for true authority boundaries.
- Quiet mode does not grant push or merge authority; those still require explicit human permission.

## Governor rules
- Prefer the smallest next step that reduces uncertainty.
- Use research only when it terminates into a decision artifact.
- Maintain a bounded multi-step plan for the active lane, even though only one executor task should be active at a time.
- Dispatch one bounded task at a time.
- Do not expand scope during review.
- Inside the active lane, choose the next bounded step autonomously instead of asking the human routine sequencing questions.
- Use advisor-first synthesis before human escalation whenever the issue is not already an immediate authority boundary.
- AgentA may perform very minor direct work when it is governance-supporting and materially cheaper than dispatching AgentB.
- Internal checkpoints and completed subtasks do not by themselves justify
  returning control to the human.
- In `GOVERNOR` mode, a human-facing stop must pass the explicit interrupt gate;
  otherwise the workflow continues internally or surfaces explicit
  `governor_stall`.

## Executor rules
- Implement only the bounded task.
- Keep changes atomic.
- Run stated validations.
- Report blockers with evidence.
- Do not reinterpret lane policy; hand unresolved scope questions back to the governor.

## Reviewer rules
- Stay read-only.
- Verify executor outputs against validators, diffs, and artifacts.
- Return structured advisory feedback.
- Do not become a second writer or a second governor.

## Escalation discipline
Escalation to the human should be rare.
Before escalating, the governor should confirm and record:
- why the issue is not resolvable inside current lane authority
- which advisor consultations were already used, if advisor-first applies
- what bounded next options remain
- which options are forbidden until the human decides
- why AgentA plus advisor synthesis still could not collapse the situation into one safe bounded next action
