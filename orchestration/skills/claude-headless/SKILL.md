---
name: claude-headless
description: Governor-only read-only multi-file analysis via the consult_claude_headless advisory MCP tool.
---

# Claude Headless Advisor

Use this only in Governor context.

## MCP Tool
`consult_claude_headless(prompt, work_dir, cycle_id)`

## Use When
- The Governor needs code-aware multi-file tracing or subsystem analysis.
- Architecture, integration seams, or design choices need repo context.
- Executor output passed basic checks but still needs deeper integration review.
- Panel mode needs a code-aware advisor alongside MiniMax.

## Do Not Use When
- The issue is a single root-cause file; use `consult_architect`.
- The question does not need repo files; use `consult_minimax`.
- One completed file needs a lightweight review; use `routine_code_review`.
- The Governor can decide confidently without advisor help.

## Boundary
Allowed:
- read files
- search/list repo files
- inspect git with read-only commands

Not allowed:
- edits or writes
- build/test execution
- arbitrary shell commands

## Invocation Guidance
Keep the prompt self-contained and path-oriented:
- exact paths or directories to inspect
- the concrete question
- constraints and non-goals
- desired output shape

Use `work_dir` for the repo root when code context matters. Use `cycle_id` when
the advice belongs to a dispatch or Governor action-test cycle.

Expected sections:
- `SUMMARY:`
- `KEY_FINDINGS:`
- `RECOMMENDED_ACTIONS:`
- `VERIFICATION_HINTS:`
- `LIMITATIONS:`
