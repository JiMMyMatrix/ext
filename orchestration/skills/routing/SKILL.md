---
name: routing
description: Governor-only routing rules for selecting advisory MCP tools, including single-advisor and panel consultation.
---

# Advisory MCP Routing

Read:
- `orchestration/advisory.md`
- `orchestration/authority.md`

## Canonical MCP Tools
- `consult_claude_headless`
- `consult_architect`
- `routine_code_review`
- `consult_minimax`

`consult_grok_advisor` exists only as a backward-compatible alias for
`consult_minimax`. New Governor usage should prefer `consult_minimax`.

## Core rules
- only the Governor may use advisor tools
- this advisory path is cost-gated
- use advisory tools only for truly difficult, high-risk, ambiguous, or
  repeatedly failing decisions
- default to no advisor for routine work
- prefer one advisor first to save cost
- advisory output is never workflow truth
- advisory output never grants interrupt or merge authority
- runtime quotas and cycle limits outrank prose docs

## Single Advisor Routing
- Use `consult_minimax` for concept clarification, option comparison, and
  bounded questions that do not need repo files.
- Use `consult_claude_headless` for multi-file repo analysis, architecture
  tracing, code-location search, and code-aware design comparison.
- Use `consult_architect` for repeated or non-trivial debugging when there is a
  likely root-cause file and error signature.
- Use `routine_code_review` for one completed file after a bounded change.

## Panel Mode
Use both `consult_minimax` and `consult_claude_headless` with the same core
question when:
- a decision affects runtime behavior or architecture
- design tradeoffs have no obvious winner
- a wrong answer would cost more than two advisor calls
- executor output passed validation but subtle integration risks remain

Panel mode is expensive. Do not use both advisors just because the question is
interesting; use both only when the risk justifies the cost.

## No Advisor
Do not call an advisor when:
- the Governor can decide confidently
- the task is routine and low-risk
- advisory quota is exhausted
- the answer would not change the next action

## Hard Limits Mirrored From MCP Server
- `consult_claude_headless`: max 15 calls per rolling hour
- aggregate advisor calls: max 40 calls per rolling hour
- distinct advisor tools: max 3 per cycle
- `consult_architect`: escalates only after repeated same-file/same-error
  failures
- `routine_code_review`: one review per file per cycle

## Precedence
When docs disagree:
1. advisory MCP server implementation
2. this routing skill
3. individual advisor skill docs
