---
name: governor-workflow
description: Governor-only workflow skill for quiet continuation, dispatch-first discipline, legal interrupt boundaries, and finalize-before-pause behavior.
---

# Governor Workflow Skill

Use this only in Governor context.

Read:
- `orchestration/principles.md`
- `orchestration/authority.md`
- `orchestration/workflow.md`
- `orchestration/contracts/dispatch.md`
- `orchestration/contracts/transition.md`

## Core rules
- continue quietly through routine internal workflow loops
- substantive governed work starts from dispatch
- `checkpoint != pause`
- finalize through `governor_decision.json` before any human-facing pause unless
  a real blocker prevents finalization
- use legal human interrupt reasons only
- only the Governor may use advisor tools
- orchestration launches actors technically but does not invent work-plane
  decisions
