---
name: routing
description: Single source of truth for which advisory MCP tool to call and when. Supports single-advisor and panel (dual-advisor) consultation modes.
---

# MCP Routing Rules

## Canonical Tool Names
- `consult_claude_headless`
- `consult_architect`
- `routine_code_review`
- `consult_minimax`

`consult_grok_advisor` exists only as a backward-compatible alias. New code and docs must use `consult_minimax`.

## Consultation Modes

### Panel mode (dual-advisor)
Send the SAME question to both `consult_minimax` and `consult_claude_headless`.
Governor cross-references both answers before deciding.

Use panel mode when:
- the decision directly affects runtime behavior or architecture
- design tradeoffs with no clearly dominant option
- executor result review where validation passed but subtle issues are suspected
- pre-flight review of high-risk dispatches (3+ files, 4+ steps)
- diagnosing a bug that survived 2+ fix attempts
- a wrong answer would cost more than two advisor calls

### Single-advisor mode
Use one advisor only when:
- simple factual lookup (MiniMax only)
- pure code-location search (headless only)
- routine code review (use routine_code_review tool)
- advisory quota near limit
- governor just needs confirmation of an obvious answer

### No-advisor mode
- governor already knows the answer with high confidence
- task is a simple command_chain dispatch
- advisory quota exhausted

## Routing Table
QUESTION TYPE                          MODE
─────────────────────────────────────  ────────────────
Simple factual lookup                  MiniMax only
Pure code-location search              Headless only
Routine code review                    routine_code_review
Single-file debug                      consult_architect

Design tradeoff analysis               Panel (both)
Knowledge + code cross-reference       Panel (both)
High-risk pre-flight review            Panel (both)
Executor result deep review            Panel (both)
Post-failure diagnosis (attempt 2+)    Panel (both)
Architecture understanding             Panel (both)

Quota near limit                       MiniMax only
Simple confirmation                    MiniMax only
Governor already confident             No advisor

## MCP Hard Limits
- `consult_claude_headless`: max 15 calls per rolling hour
- distinct advisor tools: max 3 per cycle
- `consult_architect`: escalate only after 3 same-bug failures on the same file/signature
- `routine_code_review`: max 1 review per file per cycle
- aggregate advisor calls: max 40 calls per rolling hour across all tools

Governance-layer documents cannot override these MCP runtime hard limits.

## Precedence
When docs disagree:
1. server implementation
2. this routing file
3. individual skill docs
