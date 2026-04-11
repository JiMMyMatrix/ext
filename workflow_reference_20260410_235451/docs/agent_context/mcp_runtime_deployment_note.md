---
title: MCP Runtime Deployment Note
purpose: Historical note about the external runtime and skill changes that accompanied the earlier architecture-audit hardening work
when_to_read: Read when reconciling older architecture-audit history with the current live MCP environment or reviewing why some runtime changes lived outside repo history
priority: high
status: reference
---

# MCP Runtime Deployment Note

This note is historical context, not an active deployment checklist.

The earlier architecture-audit hardening work included both repository changes
and environment-local runtime changes outside git history.

## Historical branch checkpoint

At the time this note was written, the following hardening commits were the
repo-side checkpoint:
- `9b2e24b` `fix(arch-audit): step 1 — bind cycle_id to dispatch_ref`
- `b5e469e` `fix(arch-audit): step 2 — bound governor direct-work scope`
- `c059f08` `fix(arch-audit): step 3 — document MCP hard-limit precedence`
- `276d4e9` `fix(arch-audit): step 4 — add command-chain safety contract`
- `c87d8d3` `fix(arch-audit): step 5 — add structured output validation`
- `d4b36e2` `fix(arch-audit): step 6 — add aggregate advisor circuit breaker`
- `59c91e7` `fix(arch-audit): step 7 — add MCP state persistence`
- `8a19e48` `fix(arch-audit): patch cycle_id regex and confirm aggregate quota scope`

## External runtime surface

The following files were environment-local and not tracked by this repository:
- `/root/mcp_server.py`
- `/workspace/.codex_brain/skills/routing/SKILL.md`

Those external updates covered:
- relaxed `cycle_id` validation that matches real `dispatch_ref` values
- structured output section validation
- aggregate advisor quota enforcement
- state persistence to `/workspace/.codex_brain/mcp_state.json`
- routing-skill documentation of MCP hard limits

## Interpretation rule

Do not treat this note as the current runtime source of truth.

Use current repo docs and live verification surfaces first:
- `.codex/config.toml`
- active docs under `docs/governance/` and `docs/operations/`
- `codex mcp list`
- `bash scripts/verify_architecture.sh`

This note exists only to explain why some earlier hardening work depended on
environment-local files that were never part of repo history.

## Historical verification commands

These were the environment checks used when the original hardening work was
validated:

```bash
python3 -c "import mcp_server"
python3 - <<'PY'
import asyncio
import mcp_server
print(asyncio.run(mcp_server.consult_minimax(prompt='noop', system_hint=None, cycle_id='governor/planning-1')))
PY
python3 - <<'PY'
import json
from pathlib import Path
path = Path('/workspace/.codex_brain/mcp_state.json')
print(path.exists())
if path.exists():
    print(sorted(json.loads(path.read_text()).keys()))
PY
```
