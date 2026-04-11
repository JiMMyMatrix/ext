# Lane And Authority Rules

## Lane lifecycle

- Every substantive lane starts on its own dedicated branch.
- Substantive lane work happens on the lane branch, not on `main`.
- Substantive lane work must be formalized through an explicit dispatch before
  it starts.
- The only normal tracked paths for substantive lane work are:
  - explicit helper-backed dispatch
  - explicit live-subagent dispatch
- Small routine helper-backed substantive tasks should use the micro-dispatch
  helper instead of bypassing tracked execution.
- `main` is the integrated baseline.
- When a lane reaches a clean bounded checkpoint, merge it back into `main`.
- A new chat window does not reset branch or lane obligations.

## `main` restrictions

Allowed on `main` unless the human authorizes otherwise:
- governance updates
- audit and validation review
- merge and push housekeeping

Do not incubate new sample/runtime behavior directly on `main`.

## Consultation policy

Use one-shot specialists only when they materially help:
- bounded research
- diagnosis of a concrete blocker
- option comparison
- critique of a finished artifact

Consultations are advisory only and should not replace execution.

## Human escalation gate

Escalate to the human only when at least one is true:
- the next step would open or broaden a lane
- success criteria, guard policy, or acceptance posture would change
- constitutional or operating-mode rules would need to change
- the next step would leave the authorized surface on `main`
- advisor-first handling still did not collapse the problem into one safe
  bounded action

Do not escalate to the human for:
- routine dispatch creation
- helper-backed vs live-subagent selection
- normal executor/reviewer cycles
- expected validation/fix loops
- routine reprioritization inside the already-authorized branch goal
- merge-preparation work that stays inside branch authority
- context rollover after a clean completed dispatch when finalization and the
  next bounded step can still be determined from repo guidance
- internal checkpoints, completed subtasks, or other routine workflow churn by
  themselves

Branch-ready gate:
- before calling a branch merge-ready or interrupting the human for final
  review/merge, run `scripts/check_lane_merge_ready.py --lane <active-lane>`
- if a tracked dispatch has finished cleanly, persist `governor_decision.json`
  before any human-facing pause, summary, handoff, or final review request
- any human-facing stop must also pass the hard interrupt gate by recording
  `.agent/governor/<lane>/proposed_transition.json` and validating it with
  `scripts/check_governor_interrupt_gate.py` plus
  `scripts/check_governor_liveness.py`
- if no legal stop reason exists and no active or queued next action remains,
  treat that as `governor_stall`, not as a quiet stop
- if it fails, continue branch work internally instead of escalating

## Default authority model

- AgentA owns planning, sequencing, and accept/reject decisions
- AgentB owns substantive execution and validation
- reviewer verifies executor outputs and returns advisory feedback
- specialists advise but do not approve or redefine scope
- humans decide policy, authority, and unresolved deadlocks
- direct in-session substantive lane work without a dispatch is a workflow
  violation, not a normal peer path
