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
