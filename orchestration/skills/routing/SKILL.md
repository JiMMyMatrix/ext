---
name: routing
description: Governor-only advisor routing rules and guardrails.
---

# Advisor Routing

Read:
- `orchestration/advisory.md`
- `orchestration/authority.md`

## Core rules
- only the Governor may use advisor tools
- use advisory tools only for difficult, high-risk, or ambiguous decisions
- advisory output is never workflow truth
- advisory output never grants interrupt or merge authority
- runtime quotas and cycle limits outrank prose docs
