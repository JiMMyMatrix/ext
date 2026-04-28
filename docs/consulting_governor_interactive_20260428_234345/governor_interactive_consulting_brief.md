# Corgi Governor Runtime Consulting Brief

## Purpose
We want external review on whether Corgi should move the Governor from the current headless `codex exec` pattern to a more interactive or long-lived runtime pattern.

This is a consulting brief only. Do not treat it as an implementation plan unless the recommendation is accepted separately.

## Fixed Architecture
Corgi architecture is currently fixed:

Human
-> VS Code Extension UX
-> Dialog Controller
-> Semantic Sidecar
-> Orchestration
-> Governor / Executor / Reviewer
-> Codex runtime
-> repo artifacts

Authority rules:

- VS Code extension/webview is human-facing only.
- Dialog Controller is deterministic and single-voice.
- Semantic Sidecar is advisory-only and model-first for free-text routing.
- Orchestration owns permission, session, context, actor launch, and fail-closed legality.
- Governor owns planning/dialogue decisions.
- Executor is the only substantive writer.
- Reviewer is read-only advisory.
- Workflow truth remains artifact-based.
- `request.json` is dispatch truth only.
- `accepted_intake.json` is intake-level canonical artifact.

## Current Governor Runtime
The current Governor is headless per turn.

Evidence:

- `orchestration/harness/session.py` invokes the Governor with `subprocess.run`.
- The command is `codex exec ... --json -o <last_message.txt>`.
- The process uses `stdin=subprocess.DEVNULL`.
- Orchestration captures the final message from JSONL stdout or `last_message.txt`.
- Follow-up turns use `codex exec resume <thread_id> ...`.
- A `threadId` is stored in session metadata, so there is thread continuity.
- There is not a live interactive process/channel kept open by Corgi.

Key code references:

- `orchestration/harness/session.py:_run_governor_exec`
- `orchestration/harness/session.py:_continue_governor_dialogue`
- `src/executionTransport.ts:OrchestrationExecutionTransport.run`

Current runtime settings:

- Default Governor model: `gpt-5.4`
- Default reasoning: `xhigh`
- Config source: `orchestration/runtime/config.toml`
- Governor sandbox: `read-only`

## Current Extension Transport
The VS Code extension does not talk to Codex directly.

It shells out to the orchestration CLI:

`python3 orchestration/scripts/orchestrate.py session <command>`

The extension expects one complete JSON model response per command.

This means the current extension transport is request/response, not streaming and not persistent.

## Codex CLI Surface Observed Locally
`codex --help` says:

- If no subcommand is specified, options are forwarded to the interactive CLI.
- `codex exec` runs Codex non-interactively.
- `codex resume` resumes a previous interactive session.
- `codex mcp-server` starts Codex as an MCP server over stdio.
- `codex app-server` is experimental and can listen over `stdio://` or `ws://IP:PORT`.
- `codex exec-server` is experimental and can listen over WebSocket.

Important interpretation:

- A plain interactive `codex` TUI exists.
- The current Corgi Governor does not use it.
- Directly embedding the TUI is probably not the right interface for a VS Code webview.
- `app-server` or `exec-server` might be more promising, but they are explicitly experimental and need protocol investigation.

## User-Visible Problem
The user experiences Corgi as slower and less fluid than direct Codex chat.

Likely reasons:

- Semantic sidecar classification runs before the Governor path.
- Orchestration performs session, permission, context, and fail-closed validation.
- Current Governor call pays process startup cost per Governor turn.
- `gpt-5.4` with `xhigh` reasoning is relatively expensive for every Governor dialogue/planning response.
- The extension waits for authoritative session state and complete Governor output.
- Current transport is non-streaming request/response.

## What We Want From Consulting
Please assess whether moving the Governor to an interactive or long-lived runtime is worth doing, and what the safest minimal design would be.

Questions:

1. Should Corgi keep the current `codex exec resume <thread_id>` design and optimize around it, or move to a long-lived Governor runtime?
2. If moving to a long-lived runtime, should the candidate be:
   - plain interactive `codex` TUI through a PTY,
   - `codex app-server`,
   - `codex exec-server`,
   - `codex mcp-server`,
   - or a different bridge?
3. Which option can preserve the current authority model without making the extension a second Governor?
4. Which option supports streaming/progress without exposing internal control-plane details?
5. Which option can keep `context_ref`, `session_ref`, permission gating, and artifact truth fail-closed?
6. Can a long-lived Governor stay read-only while Executor remains the only writer?
7. What is the smallest Phase 1 experiment that proves latency improvement without redesigning Corgi?
8. How should failures be handled if a long-lived Governor process crashes, stalls, or loses sync?

## Non-Negotiable Constraints
Do not recommend changes that:

- Move workflow authority into the VS Code extension.
- Let model output directly authorize workflow actions.
- Bypass permission scope checks.
- Bypass `context_ref` or `session_ref` freshness checks.
- Turn Semantic Sidecar into workflow authority.
- Let Governor write files directly.
- Replace artifact-based workflow truth.
- Reopen the Observe / Plan / Execute permission model.
- Reintroduce production keyword routing.

## Candidate Options

### Option A: Keep Headless `codex exec`, Optimize It
Pros:

- Lowest architectural risk.
- Already implemented.
- Keeps clear request/response failure boundaries.
- Easy to test and fail closed.
- Thread continuity already exists through `threadId`.

Cons:

- Process startup per Governor response.
- No true streaming.
- UI feels slower.
- Governor cannot maintain an always-warm interaction channel.

Possible optimizations:

- Use a faster Governor model or lower reasoning for dialogue-only turns.
- Keep `gpt-5.4 xhigh` only for Plan-ready planning.
- Improve latency masking in UI.
- Add timing telemetry for semantic sidecar, orchestration, Governor runtime, and render.

### Option B: Long-Lived Governor via PTY Interactive `codex`
Pros:

- Closest to the direct Codex experience.
- Potentially lower latency after startup.
- May preserve richer interactive state.

Cons:

- TUI/PTY parsing is fragile.
- Hard to distinguish internal state from user-facing output.
- Harder to enforce clean JSON/protocol boundaries.
- Risk of extension/orchestration becoming a screen-scraper.
- Failure recovery and sync are more complex.

### Option C: Long-Lived Governor via `codex app-server`
Pros:

- More likely to expose structured events than a TUI.
- Supports `stdio` or WebSocket.
- Possibly closer to what first-party IDE integrations use.

Cons:

- Experimental.
- Protocol must be inspected.
- Needs authentication/session lifecycle handling.
- Could become a larger integration layer than intended.

### Option D: Long-Lived Governor via `codex exec-server`
Pros:

- Explicit server mode.
- WebSocket transport may fit VS Code extension/orchestration bridge.
- May reduce process startup overhead.

Cons:

- Experimental.
- Unknown support for Governor-style persistent conversation.
- Unknown event schema and stability.
- Needs careful fail-closed wrapper.

### Option E: `codex mcp-server`
Pros:

- Structured stdio server.
- Might provide stable tool-like integration.

Cons:

- MCP server may expose Codex as tools/resources rather than a Governor chat runtime.
- May not fit the desired "Governor as actor" model.
- Needs protocol investigation.

## Suggested Minimal Experiment
Before redesigning, run a bounded spike:

1. Measure current latency:
   - semantic sidecar start/end
   - orchestration command start/end
   - Governor subprocess start/end
   - first Governor output time if available
   - final state render time
2. Try `codex exec-server --listen ws://127.0.0.1:0` and inspect whether it exposes a suitable structured request/response or streaming API.
3. Try `codex app-server --listen ws://127.0.0.1:0` and inspect whether it exposes session events suitable for a Governor actor.
4. Do not route production Corgi traffic through these servers yet.
5. Compare end-to-end latency and failure behavior against current `codex exec`.

Success criteria for any long-lived runtime:

- Keeps Governor read-only.
- Emits structured user-facing messages or events.
- Can preserve session/thread identity.
- Can be wrapped by orchestration, not extension authority.
- Can fail closed on stale context/session.
- Can recover cleanly after crash/restart.
- Produces measurable latency improvement.

## Current Opinion
It is possible to use an interactive or long-lived mode, but plain interactive TUI mode is probably not the best target for Corgi.

The safest next investigation is not "replace `codex exec` with interactive TUI." It is:

1. Add timing telemetry to current headless Governor calls.
2. Check whether `app-server` or `exec-server` provides a structured protocol.
3. Only then decide whether to introduce a long-lived Governor bridge behind orchestration.

If no stable structured server protocol is available, keep `codex exec resume` and optimize model/reasoning/UX latency instead.
