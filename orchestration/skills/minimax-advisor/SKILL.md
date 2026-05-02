---
name: minimax-advisor
description: Governor-only general reasoning advisor via consult_minimax for bounded questions that do not require repository file access.
---

# MiniMax Advisor

Use this only in Governor context.

## MCP Tool
`consult_minimax(prompt, system_hint, cycle_id)`

`consult_grok_advisor` is a backward-compatible alias. Prefer
`consult_minimax` in new prompts, docs, and Governor usage.

## Use When
- The Governor needs quick conceptual reasoning or option comparison.
- The question does not require repo file access.
- Panel mode needs a general-knowledge advisor alongside Claude Headless.
- Advisory cost or quota favors the lighter advisor.

## Do Not Use When
- Repo inspection is required; use `consult_claude_headless`.
- A root-cause file needs debugging; use `consult_architect`.
- A completed file needs review; use `routine_code_review`.

## Boundary
MiniMax has no project filesystem access. Do not ask it to inspect files or
verify repo contents.

## Runtime Configuration
`consult_minimax` prefers the direct MiniMax OpenAI-compatible API when
`MINIMAX_API_KEY` is set. Optional overrides:
- `MINIMAX_OPENAI_BASE_URL` or `MINIMAX_BASE_URL`
- `MINIMAX_MODEL`
- `MINIMAX_MAX_TOKENS`

Local development may also put the MiniMax token in the ignored file
`.agent/orchestration/advisory/minimax_api_key`, or set
`MINIMAX_API_KEY_FILE` to another private path. If direct API credentials are
not available, the Grok fallback requires the MiniMax-documented npm CLI
`@vibe-kit/grok-cli`; set `MINIMAX_GROK_COMMAND` if another `grok` binary is
earlier on PATH.

## Invocation Guidance
Keep the prompt focused. Use `system_hint` for panel mode or role steering. Use
`cycle_id` when the advice belongs to a dispatch or Governor action-test cycle.

Expected sections:
- `SUMMARY:`
- `REASONING:`
- `RECOMMENDED_ACTIONS:`
- `LIMITATIONS:`
