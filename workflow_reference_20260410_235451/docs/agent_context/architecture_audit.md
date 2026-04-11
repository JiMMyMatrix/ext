---
title: Architecture Audit
purpose: Historical audit and resolution record for the governor/executor hardening work
when_to_read: Read when reviewing why the architecture-audit hardening changes were made or reconciling repo docs with the deployment note
priority: medium
status: reference
---

# Governor-Executor Architecture: Structural Audit & Resolution Plan

> Produced from cross-referencing: `AGENTS.md`, `governor_executor_dispatch_contract.md`,
> `governor_workflow.md`, `operating_spec.md`, `advisory_protocol.md`, `sample5_window_birth_lane_spec.md`,
> `INDEX.md`, `agentA_governor_prompt.txt`, `agentB_executor_prompt.txt`,
> `mcp_server.py`, and all 5 MCP skill files (routing, claude-headless, consult-architect,
> routine-code-review, minimax-advisor).

> **Revision history**
> - v1: initial audit (7 concerns identified)
> - v1.1: post-implementation review corrections
>   - Concern 1: relaxed `_VALID_CYCLE_ID` regex — fifth segment now accepts
>     alphanumeric attempt IDs (e.g., `a01`) to match repo's actual `dispatch_ref` convention
>   - Concern 6: clarified that `_consume_aggregate_quota()` covers **all** tools
>     including headless, resolving the inconsistency between the description
>     ("all non-headless tools") and the implementation instruction ("every tool handler")
> - All 7 concerns implemented on branch `lane/architecture-audit-hardening`
>   (commits `9b2e24b` through `59c91e7`)

---

## Concern 1 — cycle_id / dispatch_ref identity gap

### What is wrong

The dispatch contract defines `dispatch_ref` as the canonical identifier for every
governor-to-executor work unit:

```
dispatch_ref = <cycle>/<scope_type>/<scope_ref>/<dispatch_kind>/<attempt>
```

The MCP server independently defines `cycle_id` as its own throttle key for
per-cycle tool limits, review dedup, and quota tracking. These two identifiers
serve the same conceptual purpose — "which unit of work is this advisory call
attached to?" — but nothing in the codebase or documentation binds them together.

**Consequences if left unresolved:**
- Governor can pass any arbitrary string (or None) as `cycle_id`, bypassing
  per-cycle limits by minting new IDs.
- Post-hoc audit is impossible: you cannot trace which dispatch caused which
  advisory spend.
- `cycle_tool_tracker` and `review_tracker` accumulate entries keyed by
  meaningless strings instead of real dispatch references.

### Resolution

**Documentation fix (advisory_protocol.md + dispatch contract):**
Add a normative rule:

> When the governor invokes any MCP advisory tool during a dispatch cycle,
> `cycle_id` MUST be the `dispatch_ref` of the active dispatch. If no dispatch
> is active (e.g., governor-only planning), `cycle_id` MUST be a governor-scoped
> planning identifier of the form `governor/<timestamp>`.

**MCP server fix (mcp_server.py):**
Add a lightweight format assertion at the top of `_register_cycle_call`:

```python
import re
_VALID_CYCLE_ID = re.compile(
    r"^(governor/[\w.-]+|[\w.-]+/[\w.-]+/[\w.-]+/[\w.-]+/[\w.-]+)$"
)

async def _register_cycle_call(cycle_id: str | None, tool_name: str) -> str | None:
    if cycle_id and not _VALID_CYCLE_ID.match(cycle_id):
        return (
            f"POLICY_ERROR: cycle_id='{cycle_id}' does not match "
            "dispatch_ref or governor/<id> format."
        )
    # ... rest of existing logic
```

The fifth segment accepts any `[\w.-]+` pattern (e.g., `a01`, `003`, `retry-2`),
matching the repo's actual dispatch_ref convention where attempt identifiers
are alphanumeric (e.g., `dataset_refresh.c07/repo/event-normalization-model/refreshed_failure_diagnostic/a01`).

---

## Concern 2 — command_chain has no destructive-command guardrail

### What is wrong

The dispatch contract defines `command_chain` as an execution mode where the
runtime directly executes shell commands provided by the governor. The contract
specifies optional fields like `allow_failure` and `timeout_sec` per command,
but has **no mechanism to reject destructive commands**.

Meanwhile, AGENTS.md explicitly forbids AgentB from:
- push, merge, or history rewrite
- broad runtime policy changes
- architecture rewrite

These constraints exist only as prose in AGENTS.md and `agentB_executor_prompt.txt`.
If a `command_chain` dispatch contains `git push origin main`, nothing in the
dispatch contract, executor runtime, or MCP layer prevents execution.

**Consequences if left unresolved:**
- A governor hallucination or prompt injection could produce a dispatch with
  `git push --force` inside a command chain.
- The executor has no machine-readable filter to reject it — only a prose
  instruction saying "do not push."
- The `whitelist_class` field in the dispatch contract is defined but never
  given concrete values or enforcement semantics.

### Resolution

**Dispatch contract fix:**
Add a `forbidden_commands` field to the contract with hardcoded defaults:

```
## Command safety contract

Every `command_chain` dispatch implicitly carries these defaults unless
the human explicitly overrides them:

forbidden_command_patterns:
  - "git push"
  - "git merge"
  - "git rebase"
  - "git reset --hard"
  - "rm -rf /"
  - "rm -rf /*"
  - any command containing "force" combined with "push" or "reset"

The executor runtime MUST reject any command matching a forbidden pattern
before execution. Rejection is a hard stop, not a warning.

whitelist_class semantics:
  - "read_only": only allow commands that do not modify the filesystem
  - "repo_local_write": allow file writes but not git remote operations
  - "full": allow all commands except forbidden patterns (requires human override)

Default whitelist_class: "repo_local_write"
```

**Executor prompt fix (agentB_executor_prompt.txt):**
Add a machine-actionable rule:

> Before executing any `command_chain` dispatch, scan every command against the
> forbidden_command_patterns. If any command matches, stop and return a `blocked`
> result with `blocker = "forbidden_command_detected"`.

---

## Concern 3 — MCP runtime policy has no position in the precedence chain

### What is wrong

AGENTS.md defines a clear precedence chain:

```
1. AGENTS.md
2. active lane spec
3. operating spec
4. templates and protocols
5. handoff/history artifacts
```

The MCP server enforces its own hard limits:
- `HEADLESS_MAX_CALLS_PER_WINDOW = 8`
- `MAX_DISTINCT_TOOLS_PER_CYCLE = 3`
- `ARCHITECT_ESCALATION_THRESHOLD = 3`
- one review per file per cycle

These limits can **conflict** with governance-layer decisions. Example: the
advisory_protocol.md says the governor may "assemble a bounded advisory team
view" using multiple specialists. But if the governor has already used 3
distinct tools in the current cycle, the MCP server returns `POLICY_ERROR`
regardless of whether the governance layer considers this legitimate.

Neither layer knows about the other's constraints.

**Consequences if left unresolved:**
- Governor makes a legitimate multi-advisor decision, MCP server blocks it,
  governor has no documented fallback behavior.
- Or conversely: someone relaxes MCP limits without realizing they are the
  last line of defense against runaway advisory spend.

### Resolution

**AGENTS.md fix:**
Insert MCP runtime policy into the precedence chain:

```
When documents conflict, use this order:
1. AGENTS.md
2. active lane spec
3. operating spec
4. MCP runtime policy (mcp_server.py hard limits)
5. templates and protocols
6. handoff/history artifacts
```

Add a normative note:

> MCP runtime policy enforces hard resource limits (quota, rate, per-cycle caps).
> These limits cannot be overridden by governance-layer documents. They can only
> be changed by modifying the MCP server source and redeploying.
> If a governance-layer decision is blocked by MCP policy, the governor must
> record the block in the dispatch result and either (a) restructure the
> advisory approach to fit within limits, or (b) escalate to the human for
> a policy override.

**MCP skill fix (routing SKILL.md):**
Add a section documenting the hard limits and their governance-layer implications:

```
## MCP Hard Limits (cannot be overridden by governance docs)
- headless: max 15 calls per rolling hour
- distinct tools per cycle: max 3
- architect escalation: after 3 same-bug failures
- review: max 1 per file per cycle

If a governance-layer decision conflicts with these limits, the MCP server
returns POLICY_ERROR. The governor must restructure or escalate.
```

---

## Concern 4 — in-memory state is volatile and unauditable

### What is wrong

All MCP server state is held in Python process memory:
- `headless_call_timestamps` (deque)
- `architect_tracker` (dict)
- `review_tracker` (set)
- `cycle_tool_tracker` (dict)

If the MCP server process restarts (container restart, OOM kill, crash), all
state is lost. This means:
- Headless quota resets to zero — a restart mid-hour gives 15 fresh calls.
- Architect escalation counters reset — a restart mid-debugging resets the
  3-attempt escalation to zero, permanently keeping the system on Haiku for
  a bug that genuinely needs Sonnet.
- Review dedup resets — the same file gets reviewed multiple times.
- Cycle tool tracker resets — per-cycle limits become unenforceable.

**Consequences if left unresolved:**
- Cost controls are unreliable in the exact scenarios where they matter most
  (long debugging sessions where containers may restart).
- No audit trail of advisory calls for post-hoc analysis.

### Resolution

**Short-term (low effort):**
Add a periodic state-dump to a file on the persistent volume:

```python
import json

STATE_DUMP_PATH = "/workspace/.codex_brain/mcp_state.json"

async def _dump_state():
    state = {
        "headless_timestamps": list(headless_call_timestamps),
        "architect_tracker": {
            f"{k[0]}||{k[1]}": v for k, v in architect_tracker.items()
        },
        "review_tracker": [
            [fp, cid] for fp, cid in review_tracker
        ],
        "cycle_tool_tracker": {
            k: sorted(v) for k, v in cycle_tool_tracker.items()
        },
    }
    with open(STATE_DUMP_PATH, "w") as f:
        json.dump(state, f)

async def _load_state():
    # Call once at startup
    try:
        with open(STATE_DUMP_PATH, "r") as f:
            state = json.load(f)
        # ... restore each tracker from state
    except (FileNotFoundError, json.JSONDecodeError):
        pass  # fresh start
```

Call `_dump_state()` after every successful tool invocation. Call `_load_state()`
at server startup.

**Long-term (higher effort):**
Replace in-memory state with a SQLite database on the persistent volume.
This gives you atomicity, crash safety, and queryable audit logs for free.

---

## Concern 5 — governor "minor direct work" escape hatch is unbounded

### What is wrong

Multiple documents grant AgentA the right to do "very minor direct repo work":

- AGENTS.md: "perform very minor direct repo work when it is governance-supporting
  or lower-cost than dispatching AgentB"
- operating_spec.md: "AgentA may perform very minor direct work when it is
  governance-supporting and materially cheaper than dispatching AgentB"
- sample5 lane spec: "AgentA may do very minor governance-supporting work
  directly, but substantive repo writing should still flow through AgentB"

The word "minor" is never defined. There is no line-count limit, no file-scope
limit, no list of allowed file types, and no requirement to record the direct
edit in any dispatch or artifact.

**Consequences if left unresolved:**
- Governor drift: over time, AgentA starts doing more and more "minor" edits
  directly, bypassing the entire dispatch/executor/validation loop.
- Unauditable changes: direct edits have no dispatch_ref, no executor_run,
  no validation evidence, and no result artifact.
- The clear separation between "governor decides, executor writes" erodes silently.

### Resolution

**AGENTS.md fix:**
Replace the vague "very minor" clause with a concrete boundary:

```
AgentA may perform direct repo work only when ALL of these are true:
1. The edit touches only files under `docs/agent_context/` or `.agent/`.
2. The edit is fewer than 20 lines changed.
3. The edit does not change any runtime behavior, evaluation logic, or
   model code.
4. AgentA records the direct edit in a structured note in the current
   dispatch or planning artifact, including file path and summary.

If any condition is not met, the work must flow through an AgentB dispatch.
```

---

## Concern 6 — no circuit breaker for advisor-loop cost runaway

### What is wrong

The governor_workflow.md defines a loop:

```
1. inspect → 2. choose task → 3. consult advisors → 4. emit dispatch →
5. let executor run → 6. consume results → 7. decide continue or escalate
```

If the executor keeps returning `partial` or `failed` results, the governor
loops back to step 2. Each loop iteration may trigger one or more advisory
calls. The MCP layer has per-hour and per-cycle caps, but there is no
**cross-cycle budget** — the governor can start a new cycle every few minutes,
each with its own fresh `cycle_id` and fresh per-cycle limits.

Over a long debugging session (common with CUDA/OpenCV bugs), this loop can
burn through significant advisory budget without any aggregate circuit breaker.

**Consequences if left unresolved:**
- A stuck bug triggers dozens of dispatch cycles, each consuming up to 3
  advisory calls, with no aggregate warning or halt.
- The per-hour headless cap (8) helps, but architect (Haiku) and minimax
  calls have no hourly aggregate limit at all.

### Resolution

**MCP server fix:**
Add a rolling-window aggregate counter across **all advisory tools** (including headless):

```python
AGGREGATE_WINDOW_SECONDS = 3600
AGGREGATE_MAX_CALLS = 30  # all advisor calls combined (headless + architect + review + minimax)

aggregate_timestamps: Deque[float] = deque()

async def _consume_aggregate_quota() -> str | None:
    now = time.time()
    async with policy_lock:
        while (aggregate_timestamps and
               now - aggregate_timestamps[0] > AGGREGATE_WINDOW_SECONDS):
            aggregate_timestamps.popleft()
        if len(aggregate_timestamps) >= AGGREGATE_MAX_CALLS:
            return (
                "POLICY_ERROR: aggregate advisor budget exhausted "
                f"({AGGREGATE_MAX_CALLS} calls per rolling hour). "
                "Governor should escalate to human or pause advisory."
            )
        aggregate_timestamps.append(now)
    return None
```

Call `_consume_aggregate_quota()` at the top of **every** tool handler
(`consult_claude_headless`, `consult_architect`, `routine_code_review`,
`consult_minimax`). Headless calls count against both the per-tool headless
quota (15/hour) and this aggregate quota (40/hour).

**Governor workflow fix (governor_workflow.md):**
Add a loop-budget rule:

```
## Loop budget rule
If the governor has dispatched more than 5 consecutive cycles on the same
bounded hypothesis without achieving a `completed` result, the governor must:
1. stop dispatching
2. write a structured ceiling-report summarizing all attempts and results
3. escalate to the human with the ceiling-report attached
```

---

## Concern 7 — structured output format is unenforced

### What is wrong

Every MCP tool prepends a structured-output instruction to its prompt:

```
"Return structured text only.\n\n"
"Use exactly these sections:\n"
"SUMMARY:\n" ...
```

But LLMs do not reliably follow formatting instructions. The MCP server
returns the raw LLM response as-is, with no validation that the expected
sections are actually present.

The governor and skills assume the response will have sections like
`SUMMARY:`, `ROOT_CAUSE:`, `FIX_PLAN:`, etc. If the LLM omits a section
or uses different headers, downstream parsing by the governor silently
receives malformed data.

**Consequences if left unresolved:**
- Governor receives a wall of prose instead of structured sections, wastes
  tokens re-parsing or misinterprets the response.
- No way to distinguish "advisor had nothing to say about RISKS" from
  "advisor ignored the format instruction."

### Resolution

**MCP server fix:**
Add a post-response validator for each tool that checks whether required
sections are present. If not, prepend a warning:

```python
def _validate_sections(response: str, required: list[str]) -> str:
    missing = [s for s in required if s not in response]
    if missing:
        warning = (
            f"FORMAT_WARNING: response missing sections: {missing}. "
            "Treat this response as unstructured fallback.\n\n"
        )
        return warning + response
    return response
```

Call after every LLM response:

```python
# In consult_architect:
text = response.content[0].text
text = _validate_sections(text, ["SUMMARY:", "ROOT_CAUSE:", "FIX_PLAN:", "RISKS:", "VERIFY:"])
return f"{prefix}\n{text}"
```

This is a soft validation — it does not reject the response, but it gives
the governor a machine-readable signal that the format is degraded.

---

## Summary table

| # | Concern | Severity | Fix effort | Layer |
|---|---------|----------|-----------|-------|
| 1 | cycle_id / dispatch_ref identity gap | High | Low | MCP + docs |
| 2 | command_chain has no destructive-command guardrail | High | Medium | dispatch contract + executor |
| 3 | MCP policy missing from precedence chain | Medium | Low | AGENTS.md + routing skill |
| 4 | In-memory state is volatile and unauditable | Medium | Medium | MCP server |
| 5 | Governor "minor direct work" is unbounded | Medium | Low | AGENTS.md |
| 6 | No aggregate advisor-loop circuit breaker | Medium | Medium | MCP server + governor workflow |
| 7 | Structured output format is unenforced | Low | Low | MCP server |

---

## Recommended implementation order

1. **Concern 1** (cycle_id binding) — smallest change, highest auditability payoff.
2. **Concern 5** (governor direct-work boundary) — pure documentation, prevents drift.
3. **Concern 3** (precedence chain) — pure documentation, prevents confusion.
4. **Concern 2** (command_chain guardrail) — medium effort but critical safety.
5. **Concern 7** (structured output validation) — small code change, quality-of-life.
6. **Concern 6** (aggregate circuit breaker) — medium effort, cost protection.
7. **Concern 4** (state persistence) — medium effort, reliability improvement.
