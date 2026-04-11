# Orchestration Scripts

This directory contains the shipped orchestration implementation that
supplements the Codex runtime substrate.

## Canonical Public Entry Point
- `orchestrate.py`

`orchestrate.py` is the only canonical public runtime command surface.

Everything else in this directory is an implementation module, migration
wrapper, validator, or internal helper behind that command surface.

The code-first orchestration implementation now lives in
`orchestration/harness/`.
Files in `orchestration/scripts/` should stay thin where practical.

## Intake
- `orchestrate.py intake ...`
- `orchestrate.py session ...`

## Dispatch And Lifecycle
- `orchestrate.py dispatch ...`
- `orchestrate.py transition ...`

Current helper-runtime support is intentionally narrow:
- shipped helper-runtime modes: `command_chain`, `manual_artifact_report`
- live-subagent modes stay separate: `guided_agent`, `strict_refactor`
- unported legacy/demo/sample helper modes must fail closed

## Audit
- `orchestrate.py audit verify-architecture`

## Rule
Runtime-facing docs, prompts, skills, and the VS Code extension should point to
`orchestrate.py`, not to a pile of individual script files and not to the
legacy workflow reference tree.
