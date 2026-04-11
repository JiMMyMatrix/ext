---
title: Governor-Executor Enhancement Spec
purpose: Structural enhancements to the dispatch lifecycle for improved dispatch quality, validation signal richness, and executor failure pattern learning
when_to_read: Read when working on dispatch quality, validation infrastructure, or executor failure analysis
priority: medium
status: draft
---

# Governor-Executor Enhancement Spec

> **Status: DRAFT PROPOSAL — not active governance.**
> This document proposes enhancements to the governor-executor architecture.
> Individual enhancements move to active status only when explicitly adopted
> by human authorization and integrated into the active governance documents.
>
> Builds on: `autonomous_execution_spec.md`, `executor_subagent_spec.md`.
> Does not replace either.

---

## Enhancement 1 — Risk-Based Dispatch Pre-Flight Review

### Problem

The governor's dispatch itself has no validation. A flawed plan, incomplete
file set, or contradictory constraints burns executor tokens before discovery.

### Design

The governor MAY run a pre-flight review via `consult_minimax` before
emitting a Mode B or Mode C dispatch. Pre-flight is **risk-based, not
mandatory** — it consumes advisory quota and should be used when the risk
of a bad dispatch justifies the cost.

**When to run pre-flight:**
- the dispatch touches 3+ files
- the dispatch has 4+ edit steps
- the task is in a domain where the governor has low confidence
- the governor is re-planning after a failed dispatch (the first plan
  was already wrong once)

**When to skip:**
- Mode A dispatches (deterministic commands)
- simple 1-2 file dispatches where the governor has high confidence
- re-issues with only the attempt number incremented
- emergency rollback dispatches
- advisory quota is close to the aggregate limit

**This extends the existing governor pre-flight checklist in
`executor_subagent_spec.md` §4.2.** The 8-item self-check in §4.2
remains the baseline for every dispatch. This enhancement adds an
optional external review for higher-risk dispatches only.

**Pre-flight checklist (sent to advisor):**

```
Review this dispatch plan. For each item, respond PASS, WARN, or FAIL
with a one-line reason.

1. STEP_COVERAGE: Do the plan_steps cover the full objective?
2. FILE_COVERAGE: Does declared_files include every needed file?
3. CONSTRAINT_CONSISTENCY: Are any constraints contradictory or ambiguous?
4. ORDERING: Are the steps in logical order?
5. VALIDATION_COVERAGE: Do the validation tiers test the changed behavior?
6. SCOPE_BOUNDARY: Does the plan stay within declared scope?

DISPATCH:
<the full dispatch payload>
```

**Governor evaluation:**
- all PASS → emit dispatch
- any WARN → governor revises dispatch, then emits
- any FAIL → governor must re-plan before dispatching

**Recording:** stored as `preflight_review.json` in the dispatch directory:

```json
{
  "dispatch_ref": "<dispatch_ref>",
  "advisor_tool": "consult_minimax",
  "cycle_id": "<dispatch_ref>",
  "checklist": {
    "step_coverage": {"verdict": "PASS", "reason": "..."},
    "file_coverage": {"verdict": "WARN", "reason": "..."},
    "constraint_consistency": {"verdict": "PASS", "reason": "..."},
    "ordering": {"verdict": "PASS", "reason": "..."},
    "validation_coverage": {"verdict": "PASS", "reason": "..."},
    "scope_boundary": {"verdict": "PASS", "reason": "..."}
  },
  "overall": "PASS|WARN_REVISED|BLOCKED",
  "governor_action": "emitted|revised_and_emitted|re-planned"
}
```

If pre-flight is skipped, no `preflight_review.json` is produced and
the governor relies on the self-check in `executor_subagent_spec.md` §4.2.

**Adoption status: READY TO ADOPT.**
Can be activated by adding the risk-based trigger rules to the governor
prompt and workflow. No runtime changes required. When adopted, the
dispatch/artifact docs should be updated to list `preflight_review.json`
as a recognized optional dispatch-directory artifact so it is not a
purely informal convention.

---

## Enhancement 2 — Structured Validation Delta

### Problem

Validation reports pass/fail. The governor has xhigh reasoning but
receives only binary signals, limiting its next-step decision quality.

### Design

After every validation run, the executor produces `validation_delta.json`
with generic baseline/post-change comparisons. The schema is intentionally
minimal and toolchain-agnostic — projects extend it with domain-specific
fields as needed.

**Core schema (generic, required):**

```json
{
  "dispatch_ref": "<dispatch_ref>",
  "run_ref": "<run_ref>",
  "captured_at": "<ISO 8601>",

  "tiers": {
    "tier_1": {
      "name": "build",
      "status": "pass|fail|skipped",
      "duration_sec_before": null,
      "duration_sec_after": null,
      "signal_before": {},
      "signal_after": {},
      "regressions": [],
      "improvements": []
    },
    "tier_2": {
      "name": "test",
      "status": "pass|fail|skipped",
      "duration_sec_before": null,
      "duration_sec_after": null,
      "signal_before": {},
      "signal_after": {},
      "regressions": [],
      "improvements": []
    },
    "tier_3": {
      "name": "eval",
      "status": "pass|fail|skipped",
      "duration_sec_before": null,
      "duration_sec_after": null,
      "signal_before": {},
      "signal_after": {},
      "regressions": [],
      "improvements": []
    }
  },

  "diff_stats": {
    "files_changed": 0,
    "insertions": 0,
    "deletions": 0,
    "total_lines_changed": 0
  }
}
```

**Schema rules:**
- `signal_before` and `signal_after` are freeform objects — each project
  puts its own metrics here (warning counts, test counts, sample scores,
  etc.) without the schema prescribing what they must contain
- `regressions` is a list of strings describing what got worse
- `improvements` is a list of strings describing what got better
- if a tier is skipped, `status = "skipped"` and all other fields are `null`
- `run_ref` (not `dispatch_ref`) is used for the artifact path, matching
  the repo's existing run substrate convention

**Governor consumption:**
- governor must READ `validation_delta.json` before accept/reject decision
- governor interprets `regressions` and `improvements` with its own
  xhigh reasoning — the schema does not prescribe thresholds or policies
- if `diff_stats.total_lines_changed` significantly exceeds expectations,
  governor should investigate possible executor scope creep

**Storage:** in the run directory at the path pointed to by `run_ref`,
alongside existing result artifacts.

**Adoption status: READY TO ADOPT with one prerequisite.**
Requires: (a) executor prompt update to produce the file, (b) governor
prompt update to consume it, and (c) a small dispatch contract update to
name `validation_delta.json` as a recognized run artifact alongside
`result.json`. Without (c), the file is a soft convention that may be
silently dropped.

---

## Enhancement 3 — Checkpoint-Based Multi-Stage Dispatch

### Problem

Mode B dispatches validate only at the end. If an early step breaks the
build, subsequent steps execute uselessly.

### Design

Add optional `checkpoint_after` to individual plan_steps, allowing
mid-execution validation with early termination on failure.

**This enhancement requires dispatch contract and executor runtime changes
and is more complex than the other three enhancements. It is classified
as a future enhancement, not ready for immediate adoption.**

**Deferred because:**
- partial/resume/checkpoint semantics require real contract changes to
  dispatch state machine (a `partially_executed` state does not exist today)
- the executor runtime needs to handle mid-execution pause and report
- the governor needs logic to decide what to do with a partially
  completed dispatch (re-dispatch remaining steps? start over?)

**When to revisit:**
- after Enhancements 1, 2, and 4 are adopted and operational
- after at least 10 Mode B dispatches have been executed to collect data
  on where early failures actually occur
- when the data shows that late-stage validation failure is a meaningful
  cost driver (not just a theoretical concern)

**Sketch (for future reference):**

```json
{
  "step": 2,
  "action": "edit",
  "target": "src/pipeline/window_birth.cpp",
  "instruction": "...",
  "constraints": ["..."],
  "checkpoint_after": {
    "validation": "tier_1",
    "command": "make -j4",
    "timeout_sec": 300,
    "on_fail": "stop_and_report"
  }
}
```

On checkpoint failure: executor stops, reports `blocker = "checkpoint_failed"`
with `last_completed_step` and `checkpoint_output`. No self-repair.

**Rollback on checkpoint failure:** the executor must NOT use
destructive worktree-reset operations or any other destructive worktree operation. If the
partially completed work needs to be undone, the governor dispatches
a `git revert` following the existing rollback protocol in
`autonomous_execution_spec.md` §3.4.

**Adoption status: FUTURE — not ready to adopt.**

---

## Enhancement 4 — Executor Known-Weakness Registry

### Problem

The standard executor exhibits recurring failure patterns. Without systematic
capture, the governor keeps writing dispatches that trigger the same
weaknesses.

### Design

Structured registry at `docs/agent_context/executor_known_weaknesses.md`
(markdown with consistent entry format for governor parsing).

**Entry format:**

```markdown
### W001 — Missing exception handler in try/except
- category: error_handling
- languages: Python
- trigger: any edit that introduces or modifies try/except blocks
- observed_frequency: 2/4 exception-related dispatches
- guard_constraint: "Every try/except block introduced by this edit must
  catch specific exception types, not bare except. Include a meaningful
  error message in the except handler."
- added: 2026-03-15
- last_seen: 2026-03-28

### W002 — Import path error after file move
- category: module_structure
- languages: Python
- trigger: any edit that moves functions between files or renames modules
- observed_frequency: 2/3 refactor dispatches
- guard_constraint: "After moving any function or class, grep the entire
  repo for imports of the old path and update them. List every import
  you updated in your result report."
- added: 2026-03-18
- last_seen: 2026-03-27

### W003 — Pointer null-check omission
- category: memory_safety
- languages: C, C++
- trigger: any edit involving pointer access or allocation
- observed_frequency: 3/5 pointer-related dispatches
- guard_constraint: "Every pointer dereference introduced by this edit
  must be preceded by a null check."
- added: 2026-03-20
- last_seen: 2026-03-28

### W004 — CUDA stream sync omission
- category: concurrency
- languages: C++/CUDA
- trigger: any edit modifying CUDA kernel launches or GpuMat operations
- observed_frequency: 2/3 CUDA dispatches
- guard_constraint: "After any CUDA kernel launch or async GpuMat
  operation introduced by this edit, add explicit stream synchronization
  before the result is consumed."
- added: 2026-03-22
- last_seen: 2026-03-27
```

**Governor injection protocol:**
1. read registry before constructing Mode B/C dispatches
2. match active weaknesses by `category`, `languages`, `trigger`
3. append matching `guard_constraint` to relevant edit step constraints
4. record injected IDs in dispatch: `"injected_weakness_guards": ["W001"]`

**Contract field placement:** `injected_weakness_guards` is an optional
field in the dispatch request under `execution_payload` for both
`guided_agent` and `strict_refactor` execution modes. It is a list of
weakness ID strings (e.g., `["W001", "W003"]`). When present, it signals
to the governor (during result review) which guard constraints were active
for this dispatch, enabling correlation between injected guards and
executor success/failure.

**Update protocol:**
- first occurrence of a failure pattern: record in governor's scratch note
- second occurrence of the same pattern: add to registry
- removal: only after model upgrade + 5 dispatches without the pattern

**Maintenance boundary:**

The registry is governor-maintained. Because it lives under
`docs/agent_context/` and individual entries are small, it falls within
the governor's direct-edit scope as defined in AGENTS.md — but only for
append and frequency-update operations (adding a new entry, updating
`observed_frequency` and `last_seen`). Structural changes to the registry
format or bulk removals must go through an AgentB dispatch.

If a single registry update exceeds the governor's direct-edit line limit,
the governor must dispatch it to AgentB instead of editing directly.

The executor never reads or modifies the registry.

**Adoption status: READY TO ADOPT — recommended as first enhancement.**
Lowest cost, highest quality-of-life improvement. Can be activated by
seeding the empty registry file and adding injection rules to the
governor prompt.

---

## Adoption order

Based on the agent review and cost/value analysis:

| Priority | Enhancement | Status | Rationale |
|----------|-------------|--------|-----------|
| 1st | Enhancement 4 (weakness registry) | ready | lowest cost, highest dispatch quality improvement |
| 2nd | Enhancement 1 (pre-flight review) | ready | risk-based, extends existing checklist, moderate value |
| 3rd | Enhancement 2 (validation delta) | ready (with contract pass) | generic schema, needs artifact contract alignment before adoption |
| 4th | Enhancement 3 (checkpoints) | future | needs contract/runtime changes, wait for data |

Each enhancement is adopted independently. Adoption requires human
authorization and a dedicated integration commit.

---

## Precedence

When adopted, this document sits at position 7 in the precedence chain,
**below MCP runtime policy** (MCP hard limits are non-overridable):

```
1. AGENTS.md
2. active lane spec
3. operating spec
4. autonomous execution spec
5. executor subagent architecture
6. MCP runtime policy (hard limits, non-overridable)
7. governor-executor enhancement spec (this document)
8. templates and protocols
9. handoff/history artifacts
```
