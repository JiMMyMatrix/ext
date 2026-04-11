---
name: claude-headless
description: Read-only multi-file analysis and panel advisor via Claude Code headless. Used for cross-file inspection, design comparison, knowledge cross-referencing with code context, and executor result deep review.
---

# Claude Code Headless Protocol

You are the implementation agent. The `consult_claude_headless` tool invokes Claude Code in headless mode for **read-only cross-file analysis**.

## Trigger Conditions
Call the tool when the task requires **multi-file awareness** and cannot be solved cheaply:
- Cross-file logic tracing across several modules.
- Repo-wide search for where a behavior is implemented.
- Multi-file debugging diagnosis that needs code and git inspection.
- Architecture understanding from existing code structure.
- panel mode participation, where headless provides the code-aware perspective.
- Knowledge + code cross-reference, where the answer needs both concept explanation and repo usage evidence.
- Design option comparison, where the governor needs to know which approach fits the current codebase better.
- Executor result deep review, where validation passed but integration risks may remain.

Do NOT call the tool if:
- It is a single-file bug. Use `consult_architect`.
- It is a simple factual lookup where code context adds no value. Use `consult_minimax`.
- It is a lightweight review of one completed file. Use `routine_code_review`.
- You can answer it yourself quickly.

## Cost Rules
- Max **15 calls per rolling hour** unless the user explicitly approves more.
- One external consultation event per action-test cycle. Panel mode counts as one cycle with 2 calls.
- Panel consultations count against both headless quota and aggregate quota.
- Use only when cheaper tools are insufficient.

## Panel Mode Invocation
```python
consult_claude_headless(
  prompt="CONTEXT:\n<lane and recent changes>\n\nQUESTION:\n<same question sent to MiniMax>\n\nCONSTRAINTS:\n<scope>\n\nProvide: ASSESSMENT, RECOMMENDATION, CONFIDENCE (high/medium/low), RISKS",
  work_dir="<project_root>",
  cycle_id="<dispatch_ref>"
)
```

## Capability Boundary
Allowed:
- read files
- grep/search
- list directories
- inspect git with read-only commands

Not allowed:
- file editing
- writes
- arbitrary shell commands
- build/test execution

## Pre-Invocation Rules
The tool is stateless. Every call must be self-contained. Include:
1. exact file paths or directories to inspect
2. the question to answer
3. the expected output shape
4. constraints and non-goals

Keep the prompt short. Prefer file paths over pasted code.

## Invocation
```python
consult_claude_headless(
  prompt="<precise read-only analysis request>",
  work_dir="<project_root>",
  cycle_id="<action-test-cycle-id>"
)
```

## Required Output Format
The tool must return structured text with exactly these sections:

```text
SUMMARY:
...

KEY_FINDINGS:
- ...

RECOMMENDED_ACTIONS:
- ...

VERIFICATION_HINTS:
- ...

LIMITATIONS:
- ...
```

For panel mode, also include:

```text
CONFIDENCE:
high / medium / low

RISKS:
- ...
```
