# Orchestration Layer

## Purpose
This directory houses the repo-local orchestration harness for the custom
system.

Its job is to enforce the user's harness rules clearly enough that the remote
Codex agent follows them consistently.

The orchestration layer is:
- the harness-rule enforcement core
- the intake acceptance and lane-binding surface
- the stop/continue and actor-launch control plane

The orchestration layer is not:
- a second governor
- a generic planning brain
- a second workflow-truth system

## Canonical Runtime Surface
The canonical public runtime entrypoint is:

- `python3 orchestration/scripts/orchestrate.py`

The code-first authority behind that command lives in:

- `orchestration/harness/`

The Markdown files in this directory are supporting spec and explanation.
They are not the primary runtime authority surface.

## Shipped Structure
- `harness/`: code-first orchestration authority
- `contracts/`: canonical repo-local contracts
- `scripts/`: the CLI wrapper, migration shims, and fail-closed adapters
- `prompts/`: actor and intake instructions that reference only orchestration
- `skills/`: runtime-relevant supporting skills
- `runtime/`: advisory/runtime-adjacent support and actor config templates

## Architecture
Human
-> VS Code Extension UX (local)
-> Orchestration Layer (remote)
-> Actor Layer
   - Governor
   - Executor
   - Reviewer
-> Codex runtime substrate
-> Repo + authoritative workflow artifacts

## Read Order
1. [principles.md](principles.md)
2. [enforcement.md](enforcement.md)
3. [authority.md](authority.md)
4. [artifacts.md](artifacts.md)
5. [workflow.md](workflow.md)
6. [intake.md](intake.md)
7. [advisory.md](advisory.md)
8. [ui.md](ui.md)
9. [contracts/](contracts)
10. [scripts/](scripts)

## Design Corrections Captured Here
- The final goal is harness-rule compliance, not just workflow packaging.
- The product is one unified whole, not a set of unrelated plugins.
- The UI may closely imitate the VS Code Codex extension.
- The backend architecture remains custom and harness-driven.
- Only the Governor may use advisor tools.
- `request.json` remains dispatch truth only.
- The workflow reference tree is development/reference material, not the
  canonical runtime-facing surface.
- The canonical runtime command surface is the orchestration CLI harness, not a
  broad doc-reading surface.
- The workflow reference is still useful because it shows the orchestration
  pattern: policy, model instructions, runtime constraints, fail-closed code,
  and alignment audit working together.
