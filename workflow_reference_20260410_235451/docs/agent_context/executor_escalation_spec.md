---
title: Executor Escalation Spec
purpose: Executor model escalation, task decomposition, and structured communication enhancements for long-running or failure-prone executor tasks
when_to_read: Read when extending governor/executor escalation behavior, decomposition rules, or executor communication protocols
priority: medium
status: draft
---

# Executor Escalation & Communication Enhancement Spec

> **Status:** draft  
> **Precedence:** sits at position 7 in the document precedence chain (same level as governor_executor_enhancements.md)  
> **Scope:** extends governor_executor_dispatch_contract.md, governor_workflow.md, executor_subagent_spec.md, AGENTS.md
> **Trigger:** observed failure pattern where the standard executor silently fails on complex/long-running tasks with no structured recovery path

---

## 1. Problem statement

Three interrelated failures were observed during a wider-sample evidence refresh task:

1. **Model limitation** — the standard executor produced a script with an undefined variable (`REPORTS_DIR`), a class of bug more likely with the lighter-weight default execution path on orchestration-heavy tasks.
2. **Dispatch design limitation** — a 6-sample sequential CPU pipeline was dispatched as a single executor task with no checkpoints, no heartbeat, and no partial durable output. When the turn was interrupted, the governor lost visibility entirely.
3. **Communication limitation** — the executor had no structured mechanism to report partial progress, signal that it was stuck, or request governor guidance mid-task. The governor had no mechanism to detect stalled executors or recover gracefully from interrupted turns.

These three problems compound: a weaker model is more likely to fail, but the communication contract gives it no way to fail gracefully, and the dispatch design gives the governor no way to intervene early.

## 1.1 Harness dependency note

This escalation/decomposition spec depends on a stable harness foundation:
- correctness-sensitive helper/runtime work must use `abba/.venv/bin/python`
- live eval and checkpoint artifacts must be written to repo-local durable storage under `.agent/runs/evals/...`
- checkpoint and review artifacts must fail fast on contract violations at read time
- Tier 3 eval decisions should rely on the stable acceptance harness where a supported sample flow exists

Implementation order matters:
1. environment and scope enforcement
2. durable eval/checkpoint storage
3. contract-aware loaders
4. stable acceptance runner pilot
5. then E1/E2/E3 runtime adoption on top of that foundation

---

## 2. Enhancement overview

Three interlocking mechanisms, designed to be adopted together:

| # | Enhancement | What it solves |
|---|---|---|
| E1 | Executor model escalation | Model limitation — automatic upgrade on Tier 3 eval failure |
| E2 | Task decomposition protocol | Dispatch limitation — mandatory batching for complex tasks |
| E3 | Structured communication contract | Communication limitation — checkpoint reporting, stuck detection, mid-task escalation |

---

## 3. E1 — Executor model escalation

### 3.1 Design

When an executor (gpt-5.3-codex) completes a task but fails the Tier 3 eval gate, the governor automatically re-dispatches to a heavy executor (gpt-5.4, xhigh reasoning) with accumulated failure context.

### 3.2 Escalation chain

```
Attempt 1: executor.toml        (gpt-5.3-codex, xhigh reasoning)
    ↓ Tier 3 eval fail
Attempt 2: executor-heavy.toml  (gpt-5.4, xhigh reasoning)
    ↓ Tier 3 eval fail
Attempt 3: executor-heavy.toml  (gpt-5.4, xhigh reasoning, with cumulative context)
    ↓ Tier 3 eval fail
STOP → report to human with all 3 attempt summaries
```

Maximum 2 escalation retries (3 total attempts). After 3 failures, the task is beyond automated resolution.

### 3.3 TOML file: `.codex/agents/executor-heavy.toml`

```toml
model = "gpt-5.4"
model_reasoning_effort = "xhigh"
sandbox_mode = "workspace-write"

[instructions]
developer_instructions = """
You are a heavy executor. You receive tasks that a lighter executor could not complete
to quality standards. You have access to prior attempt context including:
- The original dispatch payload
- Prior eval feedback explaining what failed
- Cumulative attempt history

Focus on the specific quality gaps identified in the eval feedback.
Follow all executor protocols defined in executor_subagent_spec.md.
"""
```

### 3.4 Dispatch contract additions

New fields in the dispatch payload (added to `governor_executor_dispatch_contract.md`):

```yaml
# Escalation fields (governor-managed)
attempt_number: 1              # 1 = first try on the standard executor, 2 = first escalation, 3 = final
escalated: false               # true if this dispatch is an escalation from a prior failure
escalation_context:            # present only when escalated = true
  prior_attempts:              # array of prior attempt summaries
    - attempt: 1
      executor: "executor.toml"
      model: "gpt-5.3-codex"
      eval_result: "fail"
      eval_feedback: |
        <governor pastes Tier 3 eval output here>
      files_touched: ["scripts/refresh_wider_sample_evidence.py"]
  original_dispatch_ref: "R042-wider-refresh"
  cumulative_failure_summary: |
    <governor writes a 2-3 sentence synthesis of what went wrong across attempts>
```

### 3.5 Governor workflow additions

Insert after existing Tier 3 eval gate logic in `governor_workflow.md`:

```
ESCALATION DECISION (post Tier 3 eval failure):
1. Read attempt_number from dispatch payload
2. IF attempt_number < 3:
   a. Construct escalation_context from current + prior attempts
   b. Set executor = "executor-heavy" if attempt_number >= 2, else "executor"
      (attempt 1 always uses executor.toml; escalation starts at attempt 2)
   c. Increment attempt_number
   d. Set escalated = true
   e. Re-dispatch with full escalation_context
   f. Log: "ESCALATION attempt_number={n} from={prior_model} to={new_model}"
3. IF attempt_number = 3 AND eval fails:
   a. STOP autonomous execution
   b. Compile escalation report:
      - Original task description
      - All 3 attempt eval results
      - Files touched across all attempts
      - Cumulative failure summary
   c. Present to human for decision
   d. Log: "ESCALATION_EXHAUSTED task={dispatch_ref} attempts=3"
```

### 3.6 AGENTS.md registration

Add to AGENTS.md under executor roles:

```
### executor-heavy

- **TOML:** `.codex/agents/executor-heavy.toml`
- **Model:** gpt-5.4
- **Reasoning effort:** xhigh
- **Sandbox:** workspace-write
- **Purpose:** handles tasks that the standard executor (gpt-5.3-codex) failed to complete to Tier 3 eval standards
- **Activation:** governor-only, via escalation protocol (never directly spawned)
- **Access:** same as standard executor — no advisory MCP access
- **Context:** receives escalation_context with prior attempt history and eval feedback
```

---

## 4. E2 — Task decomposition protocol

### 4.1 Design

The governor must decompose tasks that exceed a complexity threshold before dispatching to any executor. This prevents the "one big silent run" failure pattern.

### 4.2 Complexity indicators

A task SHOULD be decomposed if any of the following apply:

| Indicator | Threshold | Example |
|---|---|---|
| Multiple independent units of work | ≥ 3 units | "Rerun 6 samples" → 6 units |
| Expected wall-clock time | > 5 minutes estimated | CPU-bound pipeline runs |
| Cross-file orchestration | ≥ 4 files modified | Multi-module refactor |
| Sequential dependencies with no intermediate validation | ≥ 3 steps without checkpoint | Pipeline: fetch → process → evaluate → report |

### 4.3 Decomposition rules

```
TASK DECOMPOSITION (governor pre-dispatch):
1. Assess complexity indicators
2. IF any threshold exceeded:
   a. Break task into batch units (each ≤ 2 independent items or ≤ 1 complex item)
   b. Each batch becomes a separate dispatch cycle with its own dispatch_ref
   c. Batch dispatch_refs use parent ref as prefix: R042-wider-refresh/B01, B02, ...
   d. Each batch MUST produce a checkpoint artifact before governor dispatches next batch
   e. Governor reviews checkpoint before continuing
3. IF no threshold exceeded:
   a. Dispatch as single task (current behavior)
```

### 4.4 Dispatch contract additions

```yaml
# Task decomposition fields (governor-managed)
batch_context:                   # present only for decomposed tasks
  parent_dispatch_ref: "R042-wider-refresh"
  batch_id: "B01"
  batch_total: 3
  batch_scope: "Samples 1-2 of 6"
  prior_batch_checkpoints:       # array of completed batch summaries
    - batch_id: "B00"
      status: "complete"
      checkpoint_artifact: "evidence/wider_refresh_B00_checkpoint.md"
  required_checkpoint_artifact: "evidence/wider_refresh_B01_checkpoint.md"
```

---

## 5. E3 — Structured communication contract

### 5.1 Design

Defines mandatory communication patterns between governor and executor, replacing the current "dispatch → silent execution → result or failure" model with a richer protocol that supports progress visibility, stuck detection, and mid-task escalation requests.

### 5.2 Executor → Governor: checkpoint reporting

For any task with `batch_context` or `estimated_complexity ≥ medium`, the executor MUST produce a checkpoint artifact at the end of execution. Checkpoint format:

```markdown
# Checkpoint: {dispatch_ref}

## Status
- [ ] complete | partial | blocked

## Completed items
- Item 1: <description> → <outcome>
- Item 2: <description> → <outcome>

## Remaining items (if partial)
- Item 3: <description> → <reason not completed>

## Artifacts produced
- path/to/file1.py (new | modified)
- path/to/file2.md (new | modified)

## Issues encountered
- <issue description, if any>

## Executor assessment
- Confidence: high | medium | low
- Recommendation: proceed | needs_governor_review | needs_human_review
```

### 5.3 Executor → Governor: escalation request

The executor MAY request governor intervention during execution by producing an escalation artifact instead of continuing. This replaces "keep guessing when stuck."

Escalation triggers (executor SHOULD escalate rather than guess):

| Trigger | Description |
|---|---|
| Ambiguous requirements | Task description can be interpreted multiple ways and the choice matters |
| Unexpected error class | Error is outside the task's expected failure domain |
| Scope creep detected | Completing the task as written requires modifying files outside the declared scope |
| Confidence below threshold | Executor self-assesses < 50% likelihood of passing Tier 3 eval |
| Resource constraint | Task requires capabilities the executor does not have (e.g., network access, GPU) |

Escalation artifact format:

```markdown
# Escalation request: {dispatch_ref}

## Trigger
- <one of the triggers above>

## Context
- What was attempted: <description>
- Where the executor stopped: <description>
- What is ambiguous or blocked: <specific question or issue>

## Executor recommendation
- <what the executor would do if forced to continue, and why it's risky>

## Files touched so far
- <list of files modified before stopping>
```

When the governor receives an escalation artifact, it MUST:

1. Evaluate the escalation reason
2. Either: clarify and re-dispatch, absorb the task as governor direct-work (within 20-line limit), or escalate to human
3. Log: `EXECUTOR_ESCALATION_REQUEST dispatch_ref={ref} trigger={trigger}`

### 5.4 Governor → Executor: execution plan requirement

For tasks with `estimated_complexity ≥ medium`, the governor MUST include an `execution_plan` in the dispatch payload. The executor MUST validate this plan before beginning work and flag discrepancies via escalation request.

```yaml
# Execution plan (governor-authored, executor-validated)
execution_plan:
  steps:
    - id: 1
      description: "Create refresh script with REPORTS_DIR properly defined"
      expected_output: "scripts/refresh_wider_sample_evidence.py"
      estimated_minutes: 3
    - id: 2
      description: "Run samples 1-2 and capture output"
      expected_output: "evidence/sample_1.json, evidence/sample_2.json"
      estimated_minutes: 10
  total_estimated_minutes: 13
  checkpoint_after_step: 1    # executor must checkpoint after this step
```

### 5.5 Complexity estimation

The governor assigns an `estimated_complexity` to every dispatch:

| Level | Criteria | Communication requirements |
|---|---|---|
| low | Single file, < 50 lines changed, well-defined task | No checkpoint required, no execution plan |
| medium | 2-3 files, or 50-200 lines, or moderate ambiguity | Checkpoint artifact required, execution plan recommended |
| high | 4+ files, or > 200 lines, or cross-module, or long-running | Checkpoint artifact + execution plan required, decomposition strongly recommended |

Dispatch contract addition:

```yaml
estimated_complexity: "medium"   # low | medium | high — governor-assigned
```

---

## 6. Interaction between enhancements

The three enhancements interact as follows:

```
Governor receives task
    │
    ├─ E2: Assess complexity → decompose if needed
    │
    ├─ Dispatch batch/task to standard executor
    │   │
    │   ├─ E3: Executor validates execution plan
    │   │   └─ Discrepancy? → escalation request → governor re-evaluates
    │   │
    │   ├─ E3: Executor works, produces checkpoint
    │   │   └─ Stuck? → escalation request → governor intervenes
    │   │
    │   └─ Tier 1/2/3 validation gates (existing)
    │       │
    │       ├─ Pass → auto-commit (existing)
    │       │
    │       └─ Tier 3 fail → E1: escalation decision
    │           ├─ attempt < 3 → re-dispatch to executor-heavy with context
    │           └─ attempt = 3 → report to human
    │
    └─ Next batch (if decomposed) → repeat
```

---

## 7. Implementation deliverables

| # | Deliverable | File | Action |
|---|---|---|---|
| 1 | Heavy executor TOML | `.codex/agents/executor-heavy.toml` | create |
| 2 | Dispatch contract update | `docs/operations/governor_executor_dispatch_contract.md` | extend with escalation, batch, complexity, execution_plan fields |
| 3 | Governor workflow update | `docs/operations/governor_workflow.md` | add escalation decision logic, decomposition pre-check, execution plan authoring |
| 4 | Executor prompt update | `docs/operations/prompts/agentB_executor_prompt.txt` | add checkpoint reporting protocol, escalation request protocol, plan validation |
| 5 | AGENTS.md update | `AGENTS.md` | register executor-heavy role |
| 6 | Executor subagent spec update | `docs/agent_context/executor_subagent_spec.md` | add E2/E3 protocols as executor obligations |
| 7 | Weakness registry update | `docs/agent_context/executor_known_weaknesses.md` | add W005 (long-running silent tasks) |
| 8 | Governor prompt update | `docs/operations/prompts/agentA_governor_prompt.txt` | add complexity assessment, decomposition protocol, escalation handling |

---

## 8. Rollout

This spec follows the existing Phase 1 (supervised) autonomous execution model:

- **Step 1:** Human reviews and approves this spec
- **Step 2:** Codex agent implements deliverables 1-8 via a single execution prompt
- **Step 3:** Human reviews commit, merges to lane branch
- **Step 4:** Observe 5-10 dispatch cycles with escalation/decomposition active
- **Step 5:** Tune thresholds (complexity indicators, escalation triggers) based on observed patterns

No changes to MCP server or advisory panel required. This spec operates entirely within the governor-executor contract layer.

---

## 9. Design constraints

1. **No fictional CLI flags** — all mechanisms use TOML config, dispatch contract fields, and prompt instructions. No `--max-turns`, `--tools`, or `--approval-mode` references.
2. **TOML is source of truth for model selection** — `executor-heavy.toml` defines the heavy model, not prose.
3. **Governor decides, executor implements** — the executor never self-escalates to a different model. It can only request governor intervention via escalation artifact.
4. **MCP hard limits are unaffected** — this spec does not modify MCP quotas or tool access. The heavy executor has the same (no) MCP access as the standard executor.
5. **Existing validation gates unchanged** — Tier 1 (build), Tier 2 (test), Tier 3 (eval) remain as defined in autonomous_execution_spec.md. This spec adds behavior after Tier 3 failure, not alternative gates.
6. **Per-key merge applies** — `executor-heavy.toml` inherits unset keys from user-level config, overriding only the keys it explicitly sets.

---

## 10. Operational readiness requirements

### 10.1 Session-level executor smoke test

Before the first substantive executor dispatch in a fresh session, after a
container restart, after modifying `.codex/agents/*.toml`, or whenever
executor trust is uncertain, the governor SHOULD run a bounded executor smoke
test from the repo root.

Minimum smoke-test contract:
- declare one scratch artifact path under `.agent/smoke/`
- verify the executor writes only declared files
- if an undeclared-path temptation is present, verify the executor refuses it

Failure of the smoke test is a runtime-alignment blocker. The governor must
stop substantive executor-only work until the runtime path is repaired or the
human authorizes an alternative.

### 10.2 Heavy-executor model availability

E1 is only valid when the model configured in `.codex/agents/executor-heavy.toml`
is actually supported by the active runtime.

If the heavy model is unavailable:
- do NOT claim heavy escalation occurred
- do NOT silently keep retrying on the standard executor as a substitute
- record the condition as a runtime-alignment blocker
- repair the runtime/config alignment or escalate to the human

### 10.3 Retry handoff discipline

Retries should not be vague "try again" loops. When the governor retries a
failed task, it SHOULD attach a `retry_handoff` with:
- exact failing validator
- exact failing artifact path
- exact failing key path
- exact source schema or contract reference
- exact expected artifact reference
- expected vs observed value summary

If the governor cannot provide the exact failing key path, source schema, and
expected artifact, the next task SHOULD remain in diagnosis mode rather than
retrying a patch blindly.

### 10.4 Diagnosis vs patch separation

The governor SHOULD separate executor work into two tracks:
- `diagnosis`: evidence-building, trace review, comparison, bounded instrumentation
- `patch`: localized implementation against an already-isolated failure surface

Patch retries are appropriate only when the diagnosis artifact or retry
handoff has already made the failing surface explicit.
