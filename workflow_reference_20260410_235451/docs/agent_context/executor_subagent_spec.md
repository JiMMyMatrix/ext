---
title: Executor Subagent Architecture
purpose: Rules for the standard executor subagent including hybrid execution modes, guardrails, and failure cascade
when_to_read: Read when dispatching tasks to the executor, reviewing executor behavior, or debugging executor failures
priority: high
status: active
---

# Executor Subagent Architecture

> This document defines how the executor operates as a Codex CLI subagent
> running gpt-5.3-codex under a governor running gpt-5.4 with xhigh reasoning effort.
>
> The core design principle: the governor must compensate for the executor's
> weaker reasoning by producing dispatch artifacts precise enough that
> correct execution requires minimal interpretation.
>
> The executor remains the single substantive writer even when a reviewer is
> active. Review is a read-only post-execution verification step, not a second
> implementation channel.

---

## 1. Model asymmetry and its consequences

### The capability gap

| Role     | Model          | Strength               | Weakness                     |
|----------|----------------|------------------------|------------------------------|
| Governor | gpt-5.4 + xhigh reasoning | deep reasoning, planning, multi-step logic | expensive per token |
| Executor | gpt-5.3-codex   | fast, cheap, good at following concrete instructions | weak at ambiguous interpretation, architectural judgment, multi-step reasoning |

### What this means in practice

The governor can think in abstractions: "restructure the window-birth
policy to gate on burst context." The executor cannot reliably translate
that abstraction into correct code. But the executor CAN reliably follow:
"in `src/pipeline/window_birth.cpp`, add an `if (burst_context > threshold)`
guard at line 147, before the existing `open_window()` call."

**Design rule: the governor's job is not just to decide WHAT to do, but to
pre-digest it into a form that the standard executor can execute without interpretation.**

---

## 2. Hybrid execution modes

Instead of choosing between "process" and "agent" globally, the execution
mode is selected per-dispatch based on how much interpretation the task
requires.

### Mode A — Deterministic (process-like)

**When to use:**
- the governor can specify the exact change (file, line, old code, new code)
- the task is a localized bug fix, config change, or mechanical edit
- no code comprehension is needed beyond "apply this diff"

**How it works:**
- the governor emits a `command_chain` dispatch with explicit commands
- the executor runs commands sequentially, captures output, validates
- the executor has NO discretion to modify anything beyond the commands
- if a command fails, the executor reports the failure — it does NOT
  attempt to fix it

**Governor dispatch format:**
```json
{
  "execution_mode": "command_chain",
  "execution_payload": {
    "commands": [
      {"argv": ["sed", "-i", "s/old_code/new_code/", "src/file.cpp"], "name": "apply_fix"},
      {"argv": ["make", "-j4"], "name": "build", "timeout_sec": 300},
      {"argv": ["pytest", "tests/"], "name": "test", "timeout_sec": 600}
    ]
  }
}
```

**Executor behavior:**
- execute each command in order
- stop at first failure
- report results
- no interpretation, no improvisation

**Cost:** minimal — the standard executor barely needs to reason, just orchestrate commands.

### Mode B — Guided agent (constrained autonomy)

**When to use:**
- the governor knows WHAT to change but the exact implementation requires
  reading existing code to determine HOW
- the task is a feature implementation, complex bug fix, or structural
  refactor that cannot be expressed as a simple sed command
- the governor can define clear boundaries and acceptance criteria

**How it works:**
- the governor emits a `guided_agent` dispatch with a structured task spec
- the executor operates as a subagent with READ + WRITE access to declared
  files only
- the executor must follow the governor's plan step-by-step
- the executor may NOT deviate from the declared file set or task scope
- validation gates are mandatory before any commit

**Governor dispatch format:**
```json
{
  "execution_mode": "guided_agent",
  "execution_payload": {
    "plan_steps": [
      {
        "step": 1,
        "action": "read",
        "target": "src/pipeline/window_birth.cpp",
        "purpose": "find the open_window() call site around line 140-160"
      },
      {
        "step": 2,
        "action": "edit",
        "target": "src/pipeline/window_birth.cpp",
        "instruction": "Add a burst_context threshold guard before open_window(). The guard should check burst_context > BURST_GATE_THRESHOLD. If below threshold, skip the open_window() call and log a debug message.",
        "constraints": [
          "do not modify any other function in this file",
          "do not change the function signature",
          "use the existing logging macro LOG_DEBUG"
        ]
      },
      {
        "step": 3,
        "action": "read",
        "target": "include/pipeline/constants.h",
        "purpose": "check if BURST_GATE_THRESHOLD already exists"
      },
      {
        "step": 4,
        "action": "edit",
        "target": "include/pipeline/constants.h",
        "instruction": "If BURST_GATE_THRESHOLD does not exist, add it with default value 3. Place it near other window-related constants.",
        "constraints": [
          "do not modify existing constants",
          "use the same naming convention as surrounding constants"
        ]
      }
    ],
    "declared_files": [
      "src/pipeline/window_birth.cpp",
      "include/pipeline/constants.h"
    ],
    "validation": {
      "tier_1": {"command": "make -j4", "timeout_sec": 300},
      "tier_2": {"command": "pytest tests/", "timeout_sec": 600},
      "tier_3": {"command": "python3 scripts/eval_guard_set.py --samples sample2,sample5,sample8", "timeout_sec": 1800}
    }
  }
}
```

**Executor behavior:**
- follow plan_steps in order
- for each "read" step: read the file and understand the local context
  needed for the next "edit" step
- for each "edit" step: implement the instruction within the stated
  constraints
- if confused about an instruction: stop and return `status = "blocked"`
  with `blocker = "ambiguous_instruction"` and a description of what is
  unclear — do NOT guess
- after all steps: run validation tiers in order
- if validation passes: auto-commit with structured trailer
- if validation fails: report failure, do NOT attempt to fix

**Cost:** moderate — the standard executor needs to read code and make localized edits, but
the governor has pre-decomposed the task into concrete steps with constraints.

### Mode C — Strict refactor (behavior-preserving)

**When to use:**
- the change must be strictly behavior-preserving
- examples: rename a symbol, extract a function, move code between files
- the test suite is the source of truth for "behavior unchanged"

**How it works:**
- the governor emits a `strict_refactor` dispatch
- the executor runs the full test suite BEFORE making any change
- the executor implements the refactor
- the executor runs the full test suite AFTER the change
- commit is allowed ONLY if the test results are identical

**Governor dispatch format:**
```json
{
  "execution_mode": "strict_refactor",
  "execution_payload": {
    "refactor_type": "extract_function",
    "instruction": "Extract the frame-differencing logic in process_frame() (lines 89-134) into a new function called compute_frame_diff(). Keep the same parameters. Call the new function from the original location.",
    "target_files": ["src/pipeline/frame_processor.cpp"],
    "baseline_command": "pytest tests/ -v --tb=short",
    "post_command": "pytest tests/ -v --tb=short"
  }
}
```

**Executor behavior:**
- run baseline_command, capture output
- implement the refactor
- run post_command, capture output
- compare: same number of tests, same pass/fail per test
- if ANY test changes status (pass→fail OR fail→pass): do NOT commit,
  report as `blocker = "behavior_change_detected"`
- if identical: auto-commit

**Cost:** minimal reasoning + two test runs.

### Mode selection rule

The governor selects the mode based on task complexity:

```
Can I express the exact change as shell commands?
  → YES: Mode A (command_chain)
  → NO:
    Is the change behavior-preserving?
      → YES: Mode C (strict_refactor)
      → NO:
        Can I decompose it into read/edit steps with constraints?
          → YES: Mode B (guided_agent)
          → NO:
            The task is too complex for the standard executor.
            Options:
            a) further decompose into smaller tasks
            b) use consult_claude_headless for analysis, then re-plan
            c) escalate to human
```

**Rule: if the governor cannot decompose a task into a form that fits
Mode A, B, or C, the task must NOT be dispatched to the standard executor.**
This is the fundamental safety constraint for the model asymmetry.

---

## 3. Guardrails for the standard executor

### 3.1 File scope enforcement

File scope is enforced through three layers:

1. **Dispatch prompt** (soft): the governor lists DECLARED_FILES in the
   spawn prompt. The executor is instructed to modify only these files.

2. **developer_instructions** (soft): the executor TOML contains a
   standing instruction to modify only declared files.

3. **Post-hoc verification** (hard): after the executor completes, the
   governor runs `git diff --name-only` and compares the actually
   modified files against the declared set. If undeclared files were
   touched, the governor rejects the result with
   `blocker = "undeclared_file_modification"`.

Layers 1 and 2 depend on model instruction-following and may fail,
especially with the standard executor model. Layer 3 is deterministic and catches
any violation. The governor MUST always run the post-hoc check.

### 3.2 Execution budget

Each execution mode has a budget. Because Codex does not expose per-subagent
turn limits, the budget is enforced through:

1. **developer_instructions**: the executor TOML instructs the agent to
   count its tool uses and stop after the budget is reached, reporting
   `blocker = "budget_exhausted"`.

2. **Wall-clock timeout**: if the executor exceeds the mode's time limit,
   the governor should close the agent thread.

3. **Governor monitoring**: the governor can inspect subagent progress
   via `/agent` and close runaway threads.

| Mode | Tool-use budget (soft) | Wall-clock timeout |
|------|----------------------|-------------------|
| Mode A (command_chain) | 5 | 60s |
| Mode B (guided_agent) | 15 | 300s |
| Mode C (strict_refactor) | 10 | 180s |

These are advisory limits enforced by instruction-following and governor
monitoring, not by runtime mechanisms.

### 3.3 Ambiguity protocol

When the executor encounters something unclear, it must NOT improvise.
The executor's prompt must contain:

```
If any instruction is ambiguous or you are unsure how to proceed:
1. STOP immediately
2. Return status = "blocked"
3. Set blocker = "ambiguous_instruction"
4. Describe exactly what is unclear
5. Do NOT attempt to resolve the ambiguity yourself
6. Do NOT make assumptions about the intended behavior

It is always better to block and ask than to guess wrong.
```

This is critical for the standard executor — stronger models can often resolve ambiguity
correctly, but the standard executor is more likely to guess wrong. Blocking is cheaper
than a wrong edit that passes tests but introduces a subtle behavior change.

### 3.4 No self-repair

Unlike a full agent that might try to fix its own mistakes, the standard executor
executor must NOT attempt self-repair:

```
If a validation tier fails after your change:
1. Report the failure with the full error output
2. Do NOT attempt to fix the issue
3. Do NOT modify your changes
4. Return status = "failed" with the validation output
5. The governor will decide whether to retry, revise, or escalate
```

The governor has the reasoning capacity to diagnose what went wrong and
issue a corrected dispatch. The executor does not.

### 3.5 Diff size limit

To prevent runaway edits:

| Mode | Max lines changed | Consequence if exceeded |
|------|------------------|----------------------|
| Mode A | N/A (commands are explicit) | N/A |
| Mode B | 200 lines | block with `blocker = "diff_size_exceeded"` |
| Mode C | 300 lines | block with `blocker = "diff_size_exceeded"` |

The executor must run `git diff --stat` before committing and check the
total lines changed. If over the limit, block.

---

## 4. Governor-to-executor communication contract

### 4.1 Dispatch prompt structure

Every dispatch to the standard executor must follow this template:

```
You are the executor for a bounded coding task. Follow these rules exactly.

RULES:
1. Modify ONLY the files listed in DECLARED_FILES.
2. Follow PLAN_STEPS in order. Do not skip, reorder, or add steps.
3. For each edit step, respect all CONSTRAINTS listed.
4. If anything is unclear, STOP and report blocker=ambiguous_instruction.
5. If validation fails, STOP and report the failure. Do not attempt fixes.
6. Do not refactor, optimize, or "improve" anything not specified.
7. Do not add comments, documentation, or formatting changes unless specified.

TASK_CLASS: <bug_fix | feature_impl | refactor>
DISPATCH_REF: <dispatch_ref>

DECLARED_FILES:
- <file1>
- <file2>

PLAN_STEPS:
<step-by-step instructions>

VALIDATION:
After completing all steps, run these commands in order:
1. <build command>
2. <test command>
3. <eval command if applicable>

If all pass, commit with this exact message:
<type>(<scope>): <description> [auto]

Include this trailer:
Dispatch-Ref: <dispatch_ref>
Validation-Tiers: <1,2,3>
Auto-Commit: true
```

### 4.2 Governor pre-flight checklist

Before dispatching to the standard executor, the governor must verify:

1. ☐ task fits Mode A, B, or C
2. ☐ declared file set is explicit and minimal
3. ☐ every edit step has concrete constraints (not just "do the right thing")
4. ☐ validation commands are specified and tested
5. ☐ the plan is ordered so each step builds on the previous
6. ☐ ambiguous terms are resolved — no "improve", "optimize", "clean up"
   without exact specification of what that means
7. ☐ turn budget is set appropriately for the mode
8. ☐ diff size limit is set

If the governor cannot check all 8 boxes, the task needs further
decomposition before dispatch.

---

## 5. Failure cascade rules

When the standard executor fails, the governor follows this decision tree:

```
Executor returned status = "blocked"
├── blocker = "ambiguous_instruction"
│   → Governor rewrites the ambiguous step with more precision
│   → Re-dispatch (same dispatch_ref, incremented attempt)
│   → Max 2 rewrites. After that, governor must re-plan the whole task.
│
├── blocker = "undeclared_file_modification"
│   → Governor reviews whether the file set needs expanding
│   → If yes: update dispatch with expanded file set, re-dispatch
│   → If no: the executor deviated — log the incident, re-dispatch
│     with stricter constraints
│
├── blocker = "diff_size_exceeded"
│   → Governor decomposes the task into smaller sub-tasks
│   → Dispatch each sub-task separately
│
└── blocker = "turn_budget_exhausted"
    → Task is too complex for the standard executor
    → Governor must further decompose or escalate to human

Executor returned status = "failed"
├── tier_1_failed (build)
│   → Governor reads the build error
│   → May consult advisor for diagnosis
│   → Issues a corrected dispatch (Mode A if the fix is clear)
│   → Max 3 attempts per build failure
│
├── tier_2_failed (test)
│   → Governor reads which tests failed
│   → Determines if the failure is in the executor's change or pre-existing
│   → If executor's change: corrected dispatch
│   → If pre-existing: record and continue (do not block on pre-existing failures)
│
├── tier_3_failed (eval regression)
│   → Governor reviews which sample regressed
│   → This is a HIGH severity signal — eval regressions are expensive
│   → Governor should consult advisor before retrying
│   → Max 2 eval-regression retries, then escalate to human
│
└── behavior_change_detected (Mode C only)
    → The refactor was not behavior-preserving
    → Governor must revert and re-plan
    → Do NOT retry the same refactor — the approach is wrong

After 3 total failed dispatches on the same task:
→ Governor writes a ceiling report
→ Escalates to human
→ Does NOT continue retrying
```

---

## 6. Cost model

### Per-dispatch cost estimate

| Mode | Mini tokens (approx) | Advisory calls | Total relative cost |
|------|---------------------|----------------|-------------------|
| Mode A | ~500-2K | 0 | $ |
| Mode B | ~3K-8K | 0-1 (if governor pre-consults) | $$ |
| Mode C | ~2K-5K | 0 | $$ |
| Failed dispatch + retry | above × 2-3 | 0-1 | $$-$$$ |

### Budget awareness

The governor should track cumulative executor token spend per session.
If total executor spend exceeds a configurable threshold (suggest:
100K tokens per autonomous session), the governor should pause and
report spend to the human.

This is separate from the MCP aggregate quota (which tracks advisory
calls, not executor calls).

---

## 7. Integration with existing architecture

### Dispatch contract changes

Add `guided_agent` and `strict_refactor` to the supported execution modes
in `governor_executor_dispatch_contract.md`:

```
Supported execution modes:
- manual_artifact_report
- command_chain
- report_only_demo
- sample_correctness_chain
- aggregate_report_refresh
- guided_agent          ← NEW
- strict_refactor       ← NEW
```

### AGENTS.md changes

Update the AgentB section to reflect subagent status:

```
### AgentB: Executor (Subagent)
AgentB is implemented as a Codex CLI subagent running gpt-5.3-codex.
AgentB is the single writer.

AgentB operates in one of three modes per dispatch:
- Mode A (command_chain): deterministic command execution, no interpretation
- Mode B (guided_agent): step-by-step implementation with declared file
  scope and explicit constraints
- Mode C (strict_refactor): behavior-preserving changes validated by
  identical test results

AgentB must not:
- interpret ambiguous instructions (must block instead)
- attempt self-repair when validation fails
- modify files outside the declared set
- exceed the turn budget or diff size limit
- make architectural decisions
```

### Subagent invocation

Read this section together with:
- `docs/operations/governor_workflow.md` for the canonical call site
- `docs/operations/governor_executor_dispatch_contract.md` for bridge and dispatch artifacts

The governor invokes the executor by asking Codex to spawn the `executor`
custom agent defined in `.codex/agents/executor.toml`:

Before that live handoff, the governor should call the thin spawn bridge so
the dispatch-to-spawn boundary becomes explicit and machine-readable through
`spawn_bridge.json` plus the prepared handoff artifact.

Example:

"Spawn executor to implement this task: <dispatch prompt>"

That TOML file specifies:
- model: gpt-5.3-codex
- model_reasoning_effort: xhigh
- sandbox_mode: workspace-write
- developer_instructions: the full executor protocol

The governor must include all dispatch details in the spawn prompt because
the subagent has no shared memory with the governor's conversation thread.

The executor TOML does NOT include MCP server configuration. This ensures
the executor cannot call advisory tools directly. If the executor needs
advisory input, it must stop and return to the governor.

---

## 8. Precedence

This document sits alongside the autonomous execution spec:

```
1. AGENTS.md
2. active lane spec
3. operating spec
4. autonomous execution spec
5. executor subagent architecture (this document)
6. MCP runtime policy
7. governor-executor enhancement spec (draft guidance only)
8. templates and protocols
9. handoff/history artifacts
```

Amendments require human approval.

## Executor Communication Obligations

These obligations apply to ALL executor variants (standard and heavy).

### Checkpoint reporting (E3)

- Any task with estimated_complexity >= medium MUST produce a checkpoint artifact upon completion
- Any task with batch_context MUST produce a checkpoint at the path in required_checkpoint_artifact
- Checkpoint format is defined in the executor prompt (agentB_executor_prompt.txt)
- The governor will NOT dispatch the next batch until the checkpoint is reviewed

### Escalation requests (E3)

- Executors SHOULD produce an escalation request and STOP rather than guessing when:
  - Requirements are ambiguous and the choice matters
  - Unexpected errors outside the task domain are encountered
  - Scope creep is detected (files outside declared scope need modification)
  - Self-assessed confidence < 50% of passing Tier 3 eval
  - Required capabilities are unavailable
- An escalation request is NOT a failure — it is a structured communication
- The governor handles escalation requests without counting them as failed attempts

### Execution plan validation (E3)

- When a dispatch includes execution_plan, the executor MUST validate it before starting
- Discrepancies are reported via escalation request, not silently worked around

### Heavy executor additional obligations (E1)

- The heavy executor (executor-heavy.toml) MUST read escalation_context.prior_attempts before starting
- The heavy executor MUST address the specific quality gaps identified in prior eval feedback
- The heavy executor follows all standard executor obligations above

### Diagnosis vs patch obligations

- If a dispatch is explicitly marked as diagnosis work, the executor MUST stay on evidence-building or bounded instrumentation unless the dispatch explicitly authorizes otherwise
- If a dispatch is explicitly marked as patch work, the executor MUST treat the supplied diagnosis artifact or retry handoff as the failure contract to implement against
- If patch instructions do not identify the failure surface precisely enough, the executor SHOULD block or escalate rather than turning the task into open-ended diagnosis
- A runtime patch inside an active lane is allowed only when the governor explicitly authorizes `task_track = patch` and the declared file set is explicit and minimal
- Even for an authorized runtime patch, the executor still has no write authority outside the declared file set; any undeclared file touch invalidates the result
