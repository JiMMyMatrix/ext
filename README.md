# Custom Codex Workflow System

This repository is evolving into a unified system that replaces the stock VS
Code Codex extension workflow with a custom harness-driven product.

High-level shape:

Human
-> VS Code Extension UX (local)
-> Orchestration Layer (remote)
-> Actor Layer
   - Governor
   - Executor
   - Reviewer
-> Codex runtime substrate
-> Repo + authoritative workflow artifacts

## Real Goal
The real goal is to make the remote Codex agent obey the user's harness rules
reliably.

That means:
- new feature/debug/refactor work should run on the correct branch/lane
- routine internal workflow loops should continue without unnecessary human
  interruption
- the human should only be interrupted at a real blocker, authority boundary,
  safety boundary, or merge checkpoint
- workflow truth should remain artifact-based
- large goals should advance through bounded Governor / Executor / Reviewer
  steps until the goal is complete or blocked

## Current Capability Kernel
Corgi is organized around a governed G/E/R lifecycle:
- the Governor owns planning, dialogue, goal decomposition, and final decisions
- the Executor is the only actor that may perform substantive project writes
- the Reviewer is read-only and advisory
- orchestration validates permission, session/context freshness, dispatch
  legality, authorship evidence, recovery safety, and continuation rules

Current work supports goal programs, per-step work bundles, bounded retry,
declared-output recovery, conservative parallel dispatch metadata, and compact
activity readouts for Executor / Reviewer / finalization events. Goal progress
lives under `.agent/goals/`; accepted step work remains under `.agent/work/`;
`request.json` remains dispatch truth only.

## Canonical Docs
Start here:
- [AGENTS.md](AGENTS.md)
- [orchestration/README.md](orchestration/README.md)

The canonical runtime command surface is
[`python3 orchestration/scripts/orchestrate.py`](orchestration/scripts/orchestrate.py).
These docs explain that harness; they are not the primary runtime authority.

## Reference Material
The folder
[workflow_reference_20260410_235451](workflow_reference_20260410_235451)
contains development/reference material from the current remote workflow
baseline.

It is useful source material, but it should not remain the final agent-facing
runtime surface of the shipped system.

## Current Local Surface
The repo currently contains a VS Code extension prototype in
[`src/`](src) with a Codex-style
sidebar UX.

The long-term direction is:
- keep the UI concise and Codex-like
- keep the backend architecture custom and harness-driven
- show one active goal, one current step, and compact activity/status rows
- keep raw workflow refs, signatures, and source artifacts behind details

## Local Development
Install dependencies once with `npm install`, then use the scripts below for
repeatable development checks.

Common checks:
- `npm run check-types`
- `npm run lint`
- `npm test`
- `npm run test:orchestration`
- `npm run test:process:completion`

Command-only process tests are the first correctness gate. They run Corgi
against isolated scratch workspaces and prove real project creation, bugfix,
feature, retry, reviewer, executor, and multi-step goal flows without opening a
UI window.

## Test Window
Use the test-window scripts for UI/UX verification after command-only process
checks pass.

Default scratch test window:

```sh
npm run test:window
```

Automated scratch E2E:

```sh
npm run test:window:auto
```

Useful variants:
- `npm run test:window:empty` opens an empty isolated workspace.
- `npm run test:window:project:auto` runs the Pet Life Diary bugfix flow.
- `npm run test:window:feature-app:auto` runs the existing-app feature flow.
- `npm run test:window:project-retry:auto` runs the reviewer-retry flow.
- `npm run test:window:close` closes the Corgi test window safely.
- `npm run test:window:status` prints the latest monitored test-window state.

The test window is intentionally isolated from the development repo by default.
Its root is under `~/.corgi/test-window/extension-ext/`, and scratch workspaces
live under that root's `scratch-workspaces/` directory. Repo-mode test scripts
exist for architecture smoke tests, but real project creation and mutation
tests should use scratch mode so project files are never written into this
source tree.

If you ever see canned artifact references like `orchestration/README.md` or
`orchestration/contracts/intake.json` as the active runtime state, that means
you are on an old mock/demo path rather than the real orchestration-backed
sidebar flow.
