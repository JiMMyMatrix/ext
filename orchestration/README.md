# Orchestration Layer

## Purpose
This directory houses the repo-local orchestration layer for the custom
system.

Its job is to supplement the Codex runtime substrate with the project-specific
rules, artifacts, and gates needed to keep the remote Codex agent aligned with
the user's harness rules.

The orchestration layer is:
- the project-specific intake acceptance and lane-binding surface
- the stop/continue and actor-launch control plane
- the artifact and role-boundary layer above the runtime substrate

The orchestration layer is not:
- a second governor
- a generic planning brain
- a replacement for Codex App Server or the Codex runtime substrate
- a second workflow-truth system

## Canonical Runtime Surface
The canonical public runtime entrypoint is:

- `python3 orchestration/scripts/orchestrate.py`

The code-first implementation behind that command lives in:

- `orchestration/harness/`

The extension-facing session commands include free-text intake/dialogue
submission, clarification answers, permission choices, plan-ready actions, stop,
and reconnect. Plan-ready actions are state-bound actions on the accepted plan,
not new free-text prompts.

Governor dialogue and Plan generation use the long-lived Codex App Server path
by default. Set `CORGI_GOVERNOR_RUNTIME=exec` or the VS Code setting
`corgi.governorRuntime = "exec"` to force the legacy `codex exec` /
`codex exec resume` path. App-server mode is limited to Governor dialogue and
Plan turns, expects ChatGPT authentication, keeps Executor and Reviewer on the
existing path, and falls back to `codex exec` if app-server startup, auth,
protocol handling, or message completion fails.
In Extension Development Host runs, app-server Governor threads are started as
ephemeral test threads and the local UI session snapshot is reset on launch;
production reloads keep authoritative session memory.

Free-text semantic routing remains sidecar-first by default. Set
`CORGI_SEMANTIC_MODE=governor-first` to try the experimental Governor semantic
intake path, where Governor proposes route/control intent and orchestration
validates the proposal before any state change.

The Markdown files in this directory are supporting spec and explanation.
They are not the primary runtime substrate.

## Shipped Structure
- `harness/`: code-first orchestration implementation
- `contracts/`: canonical repo-local contracts
- `scripts/`: the CLI wrapper, migration shims, and fail-closed adapters
- `prompts/`: actor and intake instructions that reference only orchestration
- `skills/`: runtime-relevant supporting skills
- `runtime/`: advisory/runtime-adjacent support and actor config templates

## Architecture
Human
-> VS Code Extension UX (local)
-> Orchestration Layer (remote supplement)
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
- The Codex runtime substrate remains primary.
- The backend architecture remains custom, but orchestration is supplemental to
  the runtime substrate rather than a replacement for it.
- Only the Governor may use advisor tools.
- `request.json` remains dispatch truth only.
- The workflow reference tree is development/reference material, not the
  canonical runtime-facing surface.
- The canonical runtime command surface is the orchestration CLI harness, not a
  broad doc-reading surface.
- The workflow reference is still useful because it shows the orchestration
  pattern: policy, model instructions, runtime constraints, fail-closed code,
  and alignment audit working together.
