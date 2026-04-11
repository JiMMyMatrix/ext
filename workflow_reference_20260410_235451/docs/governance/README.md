# Governance Docs

This folder holds the detailed governance material that no longer fits in
`AGENTS.md`.

Use `AGENTS.md` as the entrypoint:
- current branch and lane posture
- mode summary
- critical hard rules
- read order and precedence

Then use the files here for the detailed governance rules:

- `docs/governance/next_steps.md`
  - current branch-level next actions
  - immediate checkpoint and recommended follow-up
- `docs/governance/modes_and_roles.md`
  - CHAT vs GOVERNOR mode
  - quiet flag behavior
  - AgentA / AgentB / reviewer / executor-heavy / specialists
  - substantive lane work requires explicit dispatch
  - GOVERNOR is silent by default for routine internal workflow events
  - clean completed dispatches are finalized before any human-facing pause
  - human-facing stops require the interrupt gate and liveness gate
- `docs/governance/runtime_and_executor.md`
  - runtime source of truth in `.codex/`
  - executor smoke test, reviewer runtime, helper-backed review/finalizer path, and heavy-model alignment
  - helper-backed vs live-subagent tracked paths
  - micro-dispatch helper, conservative parallel-start rules, and optional overlap isolation
  - reviewer advisory-only contract and fail-closed overreach handling
  - finalize-before-pause runtime discipline for clean completed dispatches
  - stop/continue control through proposed transition intent plus interrupt/liveness gates
  - diagnosis vs patch discipline
  - harness runtime requirements
- `docs/governance/lane_and_authority.md`
  - lane lifecycle and branch discipline
  - dispatch-first discipline for substantive lane work
  - `main` restrictions
  - consultation policy
  - human escalation gate
  - legal human-stop allowlist and stall handling
  - merge-ready notification gate
  - default authority model
- `docs/governance/reference_lanes.md`
  - frozen lane references
  - default sample guard references

## Practical doc map

Use the governance docs for policy and authority.

Use the operating docs for mechanics:
- `docs/operations/governor_workflow.md`
  - canonical governor loop, including dispatch-first discipline, the mandatory spawn-bridge boundary call, optional overlap isolation, finalize-before-pause behavior, and the hard interrupt/liveness gate
- `docs/operations/governor_executor_workflow.md`
  - concise system map across governor, executor, reviewer, helper runtime, and live subagent path
  - silent-by-default branch behavior, including context rollover as internal continuation
- `docs/operations/governor_executor_dispatch_contract.md`
  - request/state/result/review/bridge artifact contracts, including overlap-isolation metadata, proposed transition intent, lane completion rules, and governor-owned integration truth
- `docs/operations/executor_runtime_bootstrap.md`
  - helper-runtime behavior only; does not replace the live subagent path
  - helper/runtime finalization expectations for clean completed dispatches
- `docs/operations/runtime_bootstrap_guide.md`
  - concrete helper-runtime command examples and finalize-before-pause usage
- `docs/agent_context/operating_spec.md`
- `docs/agent_context/autonomous_execution_spec.md`
- `docs/agent_context/executor_subagent_spec.md`
- `docs/agent_context/reviewer_subagent_spec.md`
