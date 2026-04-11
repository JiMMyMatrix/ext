---
name: routine-code-review
description: Lightweight one-file review after a bounded change. One review per file per cycle.
---

# Routine Code Review Protocol

Use `routine_code_review` for a single completed file after implementation or refactor.

## Rules
- one review per file per cycle
- requires `cycle_id`
- not for repo-wide architecture questions
- not for debugging repeated failing fixes

## Invocation
```python
routine_code_review(
  feature_goal="...",
  file_path="/abs/path/to/file.py",
  cycle_id="<required cycle id>",
  stack_hint="<optional language/domain hint>"
)
```

## Required Output Format
```text
STATUS: OK
MODEL: ...

SUMMARY:
...

TOP_ISSUES:
- ...

SUGGESTED_FIXES:
- ...

RISK_LEVEL:
...
```
