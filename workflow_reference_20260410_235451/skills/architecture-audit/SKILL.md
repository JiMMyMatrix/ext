---
name: architecture-audit
description: Run this skill to verify the governor-executor architecture is correctly configured and all governance documents are internally consistent. Trigger after setup, after merging structural changes, after container rebuild, or when something feels off.
---

# Architecture Audit Protocol

This is a read-only structural audit. Do not modify files while running it.

Use it after workflow/config changes, after merging structural work, after a
container rebuild, or when the governor/executor behavior feels off.

## Step 1 — Fast repo verification
Run:

```bash
bash scripts/verify_architecture.sh
```

If it fails, report the exact failing checks first. Do not guess past a failed
architecture check.

## Step 2 — Runtime alignment
Verify the runtime source of truth is still:
- `.codex/config.toml`
- `.codex/agents/`

Check:
- governor config exists and is readable
- executor / executor-heavy / reviewer configs exist where expected
- project MCP registration includes the thin spawn bridge when this repo
  expects it
- runtime claims in docs do not outrank TOML/runtime-enforced limits

## Step 3 — Workflow-discipline alignment
Confirm the top-level and workflow docs agree on these rules:
- missing dispatch for substantive lane work is a workflow violation
- silent-by-default GOVERNOR behavior
- `checkpoint != pause`; completed subtasks remain internal unless a legal
  interrupt gate is satisfied
- helper-backed work may stay non-spawn but still needs a dispatch
- `guided_agent` and `strict_refactor` must cross the live spawn boundary
- micro-dispatch is low-risk helper-backed only
- parallel tracked work is conservative and defaults to serialization
- dependency satisfaction requires real completion signals, not acceptance alone
- merge-ready requires tracked coverage plus no unresolved required
  review/validation state
- human-facing stops require the proposed transition artifact plus
  interrupt/liveness gate validation
- unresolved quiet stops without active work or a queued next action surface
  explicit `governor_stall`

Primary files:
- `AGENTS.md`
- `docs/governance/runtime_and_executor.md`
- `docs/operations/governor_workflow.md`
- `docs/operations/governor_executor_dispatch_contract.md`
- `docs/operations/prompts/agentA_governor_prompt.txt`

## Step 4 — Skill-layer alignment
Check the environment-specific skills under `/workspace/.codex_brain/skills/`
when present.

Verify:
- `governor-workflow/SKILL.md` reflects:
  - silent-by-default branch behavior
  - hard interrupt/liveness gate behavior
  - tracked-path discipline
  - micro-dispatch boundary
  - conservative parallelism
  - optional overlap isolation for overlapping live-subagent patch candidates
  - start/worktree guard enforcement
  - governor-only integration of isolated candidates
  - stale / `rebase_needed` / `superseded` overlap outcomes
  - merge-ready gate
- `spawn-bridge/SKILL.md` reflects:
  - helper vs live path resolution
  - no fake hidden spawn API
  - optional isolated worktree preparation when overlap isolation is requested
  - reviewer handoff for live review
  - blocked start-guard results serialize instead of forcing human escalation

If the environment-specific skill root is missing, mark the skill-layer check
as `NOT AVAILABLE`, not `FAIL`.

## Step 5 — Manual spot checks
When the fast verification passes but drift still seems possible, spot-check:
- helper runtime still excludes live-subagent dispatches before claim
- merge-ready gate still checks unresolved review/validation state
- micro-dispatch helper still rejects riskier work
- docs and prompts do not normalize direct in-session substantive lane work

Use exact file paths and line references when reporting drift.

## Output format
Produce:

```text
ARCHITECTURE AUDIT

FAST CHECK:
- PASS/FAIL: ...

RUNTIME ALIGNMENT:
- PASS/FAIL: ...

WORKFLOW ALIGNMENT:
- PASS/FAIL: ...

SKILL ALIGNMENT:
- PASS/FAIL/NOT AVAILABLE: ...

FINDINGS:
- <path:line> <issue or confirmation>

OVERALL:
- PASS
- FAIL
```

Keep the report short and evidence-based.
