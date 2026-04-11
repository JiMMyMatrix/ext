# AGENTS.md

## Mission
This repository is evolving into one unified product that replaces the stock
VS Code Codex extension workflow with a custom system:

Human
-> VS Code Extension UX (local)
-> Orchestration Layer (remote)
-> Actor Layer
   - Governor
   - Executor
   - Reviewer
-> Codex runtime substrate
-> Repo + authoritative workflow artifacts

The real goal is not "more workflow docs" and not "another planner."
The real goal is to make the remote Codex agent obey the user's harness rules
reliably.

## Read First
Use [orchestration/README.md](orchestration/README.md)
as the runtime doc entrypoint, and use
[`python3 orchestration/scripts/orchestrate.py`](orchestration/scripts/orchestrate.py)
as the canonical orchestration command surface.

## Critical Runtime Rules
- The orchestration layer supplements the Codex runtime substrate with
  project-specific gates, artifacts, and role constraints. It must not become a
  second governor or a replacement runtime.
- High-risk harness rules should be aligned across policy docs, prompts/skills,
  runtime constraints, and fail-closed code.
- Dispatch-first discipline is mandatory for substantive governed work.
- Normal internal dispatch, execution, review, and validation loops should not
  interrupt the human.
- `checkpoint != pause`.
- Context rollover is an internal continuation point, not a human checkpoint.
- Human interruption is legal only at a true blocker, authority boundary,
  safety boundary, or merge checkpoint.
- `request.json` remains dispatch truth only.
- Only the Governor may use advisor tools.

## Runtime Authority
- VS Code Extension UX is human-facing only.
- Intake handles raw natural-language intake and bounded clarification only.
- Codex runtime substrate remains the primary chat/runtime/tool execution
  surface.
- Orchestration owns the supplemental project layer: intake acceptance, lane
  binding, stop/continue gates, actor launch control, and artifact discipline.
- Governor is the single work-plane decision owner.
- Executor is the single substantive writer.
- Reviewer is read-only and advisory only.
- Advisory MCP tools are Governor-only support, never a separate authority
  layer.

## Reference Material
The folder
[workflow_reference_20260410_235451](workflow_reference_20260410_235451)
is development/reference material.

It is useful source material, but it is not the runtime authority surface the
shipped system should rely on directly.

## Precedence
When runtime-facing materials disagree, use this order:
1. runtime-enforced policy in `orchestration/` code/config
2. contracts under [`orchestration/contracts/`](orchestration/contracts)
3. `AGENTS.md` and supporting docs under [`orchestration/`](orchestration)
4. development/reference material under
   [`workflow_reference_20260410_235451/`](workflow_reference_20260410_235451)
