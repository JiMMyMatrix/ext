---
name: consult-architect
description: Use for repeated or non-trivial debugging on a root-cause file. Escalates to a stronger model only after repeated failures on the same file and same error signature.
---

# Architect Debugging Protocol

Use `consult_architect` for bounded debugging and root-cause analysis.

## Trigger Conditions
- single-file bug with clear root-cause file
- repeated fix attempts on the same bug
- logic or correctness issue that needs diagnosis before editing

## Escalation Rules
- escalation is keyed by `(absolute file path, normalized first error line)`
- same bug signature repeated **3 times within 5 minutes** triggers escalation
- successful escalation resets the counter

## Invocation
```python
consult_architect(
  task_description="...",
  file_path="/abs/path/to/file.py",
  error_log="exact relevant error lines",
  cycle_id="<optional cycle id>",
  stack_hint="<optional language/domain hint>"
)
```

## Required Output Format
```text
STATUS: STANDARD|ESCALATED
MODEL: ...
ATTEMPT: ...

SUMMARY:
...

ROOT_CAUSE:
...

FIX_PLAN:
...

RISKS:
...

VERIFY:
...
```
