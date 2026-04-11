---
title: Autonomous Execution Spec
purpose: Rules for autonomous dispatch-execute-validate-commit loops without human intervention
when_to_read: Read when the system is operating in any autonomous phase or when reviewing autonomous execution rules
priority: high
status: active
---

# Autonomous Execution Spec

> This document defines the rules under which the Governor-Executor system may
> operate autonomously — dispatching tasks, executing code changes, running
> validation, and committing results without human intervention.
>
> This document is subordinate to `AGENTS.md` and `docs/governance/` in precedence.
> MCP runtime policy (hard limits) still applies independently.

---

## 1. Autonomous scope

### 1.1 Allowed task classes

The system may autonomously execute tasks that match ALL of:
- the task falls into one of these classes:
  - `bug_fix`: a concrete error exists, an error log is available, and at
    least one automated validator can confirm the fix
  - `feature_impl`: a written spec exists (in a lane spec, dispatch, or
    doc artifact), and at least one automated validator can confirm the
    feature works as specified
  - `refactor`: the change is explicitly behavior-preserving, and the full
    existing test suite must pass identically before and after
- the task remains inside the current active lane
- the task does not cross any authority boundary listed in section 4

### 1.2 Excluded task classes (require human)

The following always require human approval before execution:
- `new_module`: building a new component from scratch with no existing test
  coverage to validate against
- `policy_change`: modifying regression guards, acceptance posture, lane
  rules, or constitutional authority
- `cross_lane`: any work that touches files or behavior outside the active
  lane's declared scope
- `schema_migration`: changing data formats, artifact contracts, or
  evaluation schemas in ways that break backward compatibility

### 1.3 Scope creep detection

Before dispatching any autonomous task, the governor must verify:
1. the set of files to be modified is declared in the dispatch
2. every file in that set falls within the active lane's declared surface
3. no file outside the declared set is modified during execution

If the executor modifies a file not in the declared set, the result status
must be `blocked` with `blocker = "undeclared_file_modification"`, and the
commit must not proceed.

---

## 2. Validation gates

Every autonomous task must pass through a validation pipeline before commit.
The pipeline has three tiers. Each task class defines which tiers are required.

### 2.1 Tier definitions

**Tier 1 — Build validation**
- the project compiles without errors
- command: project-specific build command (e.g., `make`, `cmake --build`)
- pass criteria: exit code 0, no new compiler warnings in modified files
- timeout: 300 seconds

**Tier 2 — Unit test**
- all existing tests pass
- command: `rtk pytest` (or project-specific test runner)
- pass criteria: exit code 0, no test regressions (same or more tests pass
  compared to pre-change baseline)
- timeout: 600 seconds

**Tier 3 — Evaluation pipeline**
- sample-scoped evaluation against the guard set
- command: project-specific eval runner for sample2, sample5, sample8
- pass criteria: no regression on any guard sample compared to the accepted
  baseline (defined by the most recent `completed` eval artifacts on the
  current lane branch)
- timeout: 1800 seconds

### 2.2 Required tiers by task class

| Task class     | Tier 1 (build) | Tier 2 (test) | Tier 3 (eval) |
|----------------|:--------------:|:-------------:|:--------------:|
| `bug_fix`      | required       | required      | required if the fix touches runtime behavior |
| `feature_impl` | required       | required      | required       |
| `refactor`     | required       | required      | required if refactored code is in the eval path |

### 2.3 Pre-change baseline capture

Before executing any code change, the executor must:
1. run Tier 1 + Tier 2 and record results as `baseline_build.log` and
   `baseline_test.log`
2. if Tier 3 is required, record the current eval baseline reference
   (the `dispatch_ref` or artifact path of the most recent accepted eval)

This establishes the "before" state for regression detection.

### 2.4 Validation failure handling

If any required tier fails after the code change:
1. the executor must NOT commit
2. the executor must record the failure in the dispatch result:
   - `status = "failed"`
   - `blocker = "tier_N_validation_failed"`
   - include the relevant log diff (baseline vs post-change)
3. the governor decides whether to:
   - dispatch a follow-up fix (if the failure is clearly diagnosable)
   - rollback and try a different approach
   - escalate to human

The governor may dispatch up to 3 follow-up fix attempts on the same
validation failure. After 3 failed attempts, the governor must stop and
write a ceiling report (per the loop-budget rule in governor_workflow.md).

### 2.5 Reviewer gate

After successful executor validation, the governor should require a read-only
review for:
- `task_track = patch`
- medium/high-complexity tasks
- changes to runtime code, harness/runtime scripts, contracts, or prompts

The reviewer is advisory only:
- `pass`
- `request_changes`
- `inconclusive`

Hard validator failures remain automatic rejects and do not go to review as a
substitute for validation.

---

## 3. Commit protocol

### 3.1 Auto-commit conditions

The executor may auto-commit to the lane branch if and only if ALL of:
1. all required validation tiers passed
2. no undeclared files were modified
3. the diff is non-empty (something actually changed)
4. the commit message follows the format:
   `<type>(<scope>): <description> [auto]`
   where `<type>` is `fix`, `feat`, or `refactor`
   and `[auto]` suffix marks it as an autonomous commit
5. the dispatch result records `runtime_behavior_changed = true|false`
   accurately
6. if `runtime_behavior_changed = true`, Tier 3 eval was run and passed

### 3.2 Commit metadata

Every auto-commit must include a trailer block:

```
Dispatch-Ref: <dispatch_ref>
Validation-Tiers: 1,2,3
Tier-1-Result: pass
Tier-2-Result: pass (47/47 tests)
Tier-3-Result: pass (sample2: no regression, sample5: improved, sample8: no regression)
Behavior-Changed: true|false
Auto-Commit: true
```

This makes every auto-commit auditable via `git log --grep="Auto-Commit: true"`.

### 3.3 Forbidden git operations

The following remain forbidden under autonomous execution, matching the
existing command safety contract:
- `git push` (any remote operation)
- `git merge`
- `git rebase`
- `git reset --hard`
- force operations of any kind

Commits accumulate on the lane branch. The human merges and pushes.

### 3.4 Rollback protocol

If a committed change is later found to cause issues (e.g., a subsequent
task reveals that a previous auto-commit introduced a subtle regression):
1. the governor must NOT use `git reset --hard` or `git rebase`
2. the governor must dispatch a revert task: `git revert <commit-hash>`
3. the revert must pass through the same validation pipeline
4. the revert commit message must reference the original dispatch_ref:
   `revert(<scope>): revert <original-hash> [auto]`

### 3.5 Post-commit review gate

An auto-commit is a candidate result, not final lane acceptance.

If review is required:
1. the governor obtains reviewer feedback after the executor completes
2. the governor evaluates executor evidence plus reviewer feedback together
3. the governor may accept, redispatch, verify, or revert based on that combined record

Reviewer disagreement does not automatically invalidate a commit, but it does
block treating the result as fully accepted until the governor resolves the
conflict.

---

## 4. Authority boundaries (hard stops)

The following conditions always halt autonomous execution and require human
decision. The governor must not attempt to resolve these autonomously, even
with advisor consultation.

| Boundary | Trigger |
|---|---|
| Lane exit | proposed change would leave the active lane's declared scope |
| Guard regression | Tier 3 eval shows regression on any guard sample and 3 fix attempts failed |
| Policy change | proposed change would modify regression guards, acceptance criteria, or lane rules |
| Schema break | proposed change breaks backward compatibility of any artifact contract |
| Merge/push | the system wants to integrate changes into main or push to remote |
| Budget exhaustion | aggregate advisor quota (40/hour) or loop budget (5 consecutive failures) hit |
| Constitutional | proposed change would modify AGENTS.md, operating_spec.md, or this document |

When a hard stop fires:
1. all in-progress execution halts
2. the governor writes a structured escalation artifact (per the existing
   escalation contract in governor_executor_dispatch_contract.md)
3. no further autonomous dispatches are issued until the human responds
4. the lane branch is left in a clean, committable state

---

## 5. Autonomous dispatch flow

This is the complete loop when the governor operates autonomously:

```
┌─────────────────────────────────────────────────────────┐
│ 1. PLAN                                                 │
│    - read lane spec + current artifacts                 │
│    - identify next bounded task                         │
│    - classify task: bug_fix | feature_impl | refactor   │
│    - verify task is within autonomous scope (§1)        │
│    - if not in scope → stop, escalate                   │
│    - optionally consult advisors (advisor-first rule)   │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 2. DISPATCH                                             │
│    - emit dispatch with:                                │
│      - declared file set                                │
│      - task_class                                       │
│      - required_validation_tiers                        │
│      - execution_mode (`command_chain`, `guided_agent`, │
│        `strict_refactor`, or `manual_artifact_report`) │
│      - acceptance_criteria referencing validation gates │
│    - cycle_id = dispatch_ref                            │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 3. BASELINE                                             │
│    - executor captures pre-change validation state      │
│    - Tier 1 (build) + Tier 2 (test) baseline            │
│    - record baseline artifacts                          │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 4. EXECUTE                                              │
│    - executor implements the bounded change             │
│    - if undeclared files modified → block               │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 5. VALIDATE                                             │
│    - run required tiers in order: Tier 1 → 2 → 3       │
│    - stop at first failure                              │
│    - compare against baseline                           │
│    - if any tier fails → do NOT commit                  │
│      → governor may retry (up to 3 attempts) or stop   │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 6. COMMIT                                               │
│    - verify all auto-commit conditions (§3.1)           │
│    - commit with structured message + trailer           │
│    - record dispatch result: completed                  │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 7. REVIEW                                               │
│    - if required, reviewer checks executor result       │
│    - reviewer returns pass/request_changes/inconclusive │
└───────────────────────┬─────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────┐
│ 8. DECIDE                                               │
│    - governor reviews executor + reviewer evidence      │
│    - if next task is still in scope → loop to step 1    │
│    - if authority boundary → hard stop                  │
│    - if loop budget exceeded → ceiling report + stop    │
│    - if lane objective achieved → checkpoint report     │
└─────────────────────────────────────────────────────────┘
```

---

## 6. Monitoring and transparency

### 6.1 Autonomous session log

During autonomous operation, the governor must maintain a running log at:
`.agent/autonomous_sessions/<date>_<session_id>.md`

Each entry records:
- timestamp
- dispatch_ref
- task_class
- files declared vs files actually touched
- validation results per tier
- commit hash (if committed)
- advisory calls made (tool + cycle_id + cost tier)
- decision: continue | retry | rollback | escalate | stop

### 6.2 Human review surface

When the human returns, they should be able to understand everything that
happened by reading:
1. `git log --grep="Auto-Commit: true"` — all autonomous commits with
   validation trailers
2. `.agent/autonomous_sessions/` — the decision log
3. `PROJECT_MEMORY.md` — updated by save-state skill at each checkpoint

### 6.3 Quiet mode interaction

Quiet mode (as defined in AGENTS.md) applies to autonomous execution:
- the system does not interrupt the human during autonomous operation
- the system interrupts only for:
  - hard stops (section 4)
  - unresolved material gates that cannot be resolved from repo guidance
  - final branch-ready / merge-ready checkpoints
- checkpoints and small completed subtasks remain internal unless they satisfy
  the explicit interrupt gate

---

## 7. Gradual rollout

This spec is designed for incremental adoption:

**Phase 1 — Supervised autonomous** (recommended starting point):
- governor plans and dispatches automatically
- executor executes and validates automatically
- auto-commit is enabled and the governor continues autonomously through
  routine branch work after each commit
- human interruption is reserved for hard stops, unresolved material gates,
  and final branch-ready / merge-ready checkpoints
- a human-facing stop must be proposed machine-readably and pass the interrupt
  gate plus liveness gate; otherwise the workflow continues internally or
  raises explicit `governor_stall`
- this phase validates the pipeline without full trust

**Phase 2 — Quiet autonomous**:
- same as Phase 1 but optimized for longer uninterrupted branch sessions
- the governor chains tasks continuously within a session and may defer
  routine checkpoint summaries until branch-ready or session end
- human reviews only at hard stops, unresolved material gates, and final
  branch-ready / merge-ready checkpoints
- requires: Phase 1 has been run successfully for at least 3 sessions
  without a rollback

**Phase 3 — Full autonomous**:
- same as Phase 2 but sessions can span multiple hours without human check-in
- requires: Phase 2 has been run successfully for at least 5 sessions
  without a rollback
- the governor manages its own session lifecycle (start, checkpoint, end)

The active phase must be recorded in AGENTS.md under a new
`## Autonomous execution phase` section. Advancing to the next phase
requires explicit human authorization.

---

## Precedence and amendment

This document sits between the operating spec and the executor subagent
architecture in the precedence chain:

```
1. AGENTS.md
2. active lane spec
3. operating spec
4. autonomous execution spec (this document)
5. executor and reviewer subagent architecture
6. MCP runtime policy
7. governor-executor enhancement spec (draft guidance only)
8. templates and protocols
9. handoff/history artifacts
```

Amendments to this document require human approval.
The governor may propose amendments via an escalation artifact, but must
not self-modify this document.
