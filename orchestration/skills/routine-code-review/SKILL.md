---
name: routine-code-review
description: Governor-only lightweight one-file review via routine_code_review after a bounded implementation change.
---

# Routine Code Review Advisor

Use this only in Governor context.

## MCP Tool
`routine_code_review(feature_goal, file_path, cycle_id, stack_hint)`

## Use When
- One completed file needs a quick correctness or performance sanity check.
- A bounded implementation changed a file and validation passed.
- The Governor wants a small risk check before finalizing or continuing.

## Do Not Use When
- Review spans multiple files; use `consult_claude_headless`.
- The issue is repeated debugging; use `consult_architect`.
- No bounded implementation change has completed.

## Runtime Rules
- `cycle_id` is required.
- The same file may be reviewed only once per cycle.
- Advisor output is advice only; it cannot approve, merge, or authorize work.

## Invocation Guidance
Include:
- feature or change goal
- file path to review
- required `cycle_id`
- optional `stack_hint`

Expected sections:
- `STATUS: OK`
- `MODEL:`
- `SUMMARY:`
- `TOP_ISSUES:`
- `SUGGESTED_FIXES:`
- `RISK_LEVEL:`
