---
name: minimax-advisor
description: Cost-effective general advisor for knowledge lookup, option comparison, bounded reasoning, and dual-advisor panel participation. No project filesystem access.
---

# MiniMax Advisor Protocol

Use `consult_minimax` for cheap general reasoning and bounded Q&A.

## Panel Mode
When the governor runs a dual-advisor consultation, MiniMax provides the
general-knowledge perspective while Claude headless provides the code-aware
perspective.

In panel mode, use this system_hint:
"You are one of two independent advisors. Answer based on your general knowledge and reasoning. Do not assume you can see the repository. Provide: ASSESSMENT, RECOMMENDATION, CONFIDENCE (high/medium/low), RISKS."

## Best Use Cases
- concept clarification
- option comparison
- quick bounded research questions
- drafting recommendations before any heavier tool
- panel mode: conceptual or knowledge-side of dual-advisor consultation
- design option comparison: theoretical tradeoffs

## Do Not Use For
- repo file inspection
- file editing
- runtime execution
- multi-file code tracing

## Invocation
```python
consult_minimax(
  prompt="<specific question>",
  system_hint="<optional steering hint>",
  cycle_id="<optional cycle id>"
)
```

## Rules
- Default tool for cheap consultation.
- No filesystem access.
- Keep the prompt focused.
- Use `cycle_id` when the answer is part of an action-test cycle.

## Required Output Format
```text
SUMMARY:
...

REASONING:
...

RECOMMENDED_ACTIONS:
- ...

LIMITATIONS:
- ...
```
