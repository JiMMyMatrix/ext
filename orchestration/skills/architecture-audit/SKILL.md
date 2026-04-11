---
name: architecture-audit
description: Read-only audit skill for checking that orchestration docs, prompts, runtime configs, and scripts still agree.
---

# Architecture Audit

Run:

```bash
python3 orchestration/scripts/orchestrate.py audit verify-architecture
```

Then spot-check:
- `AGENTS.md`
- `orchestration/README.md`
- `orchestration/enforcement.md`
- `orchestration/authority.md`
- `orchestration/contracts/`
- `orchestration/prompts/`
- `orchestration/runtime/actors/`

Confirm:
- only Governor may use advisor tools
- prompts reference `orchestration/`, not the legacy workflow tree
- intake remains separate from dispatch truth
- orchestration remains harness-rule enforcement, not a second governor
