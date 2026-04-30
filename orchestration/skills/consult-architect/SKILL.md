---
name: consult-architect
description: Governor-only bounded debugging advisor via consult_architect for repeated or non-trivial single-file root-cause issues.
---

# Architect Debugging Advisor

Use this only in Governor context.

## MCP Tool
`consult_architect(task_description, file_path, error_log, cycle_id, stack_hint)`

## Use When
- A bug has a likely root-cause file.
- The same error signature survived repeated fix attempts.
- A single-file correctness issue needs diagnosis before dispatching a fix.
- The Governor needs a bounded root-cause and verification plan.

## Do Not Use When
- The problem needs repo-wide tracing; use `consult_claude_headless`.
- The question is conceptual and file-free; use `consult_minimax`.
- A completed file just needs a light review; use `routine_code_review`.

## Runtime Behavior
The MCP server tracks escalation by absolute file path plus normalized first
error line. It escalates only after repeated failures for the same bug
signature.

## Invocation Guidance
Include:
- concise task description
- exact root-cause file path
- relevant error lines
- `cycle_id` when part of a dispatch/action-test cycle
- optional `stack_hint`

Expected sections:
- `STATUS: STANDARD` or `STATUS: ESCALATED`
- `MODEL:`
- `ATTEMPT:`
- `SUMMARY:`
- `ROOT_CAUSE:`
- `FIX_PLAN:`
- `RISKS:`
- `VERIFY:`
