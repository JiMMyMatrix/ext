---
name: spawn-bridge
description: Governor-only boundary skill for actor launch intent versus technical launch execution.
---

# Spawn Bridge Skill

Use this only after a dispatch exists.

Read:
- `orchestration/authority.md`
- `orchestration/workflow.md`

## Rules
- actor launch intent belongs to the Governor
- technical launch execution belongs to orchestration
- dispatch emission alone does not prove work started
- bridge preparation, helper-vs-live resolution, and reviewer routing are
  internal workflow steps, not human-stop reasons
