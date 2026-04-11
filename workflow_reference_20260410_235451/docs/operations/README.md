# Operations

This directory contains the practical operating guidance for the multi-agent workflow.

Contents:
- `governor_executor_workflow.md`
- `governor_executor_dispatch_contract.md`
- `executor_runtime_bootstrap.md`
- `runtime_bootstrap_guide.md`
- `governor_workflow.md`
- `run_workflow.md`
- `prompts/agentA_governor_prompt.txt`
- `prompts/agentB_executor_prompt.txt`
- `prompts/agentR_reviewer_prompt.txt`

Recommended use:
- Start with `AGENTS.md` and `docs/governance/README.md` for posture, authority, and precedence.
- Read `governor_workflow.md` first for the canonical governor loop and dispatch-first discipline.
  That file also carries the silent-by-default governor rule, limited
  parallel-start rules, optional overlap isolation, the finalize-before-pause
  rule, the hard interrupt/liveness gate, and the merge-ready gate.
- Read `governor_executor_workflow.md` next for the short end-to-end system map.
- Read `governor_executor_dispatch_contract.md` for request/state/result/review/bridge artifact fields, overlap-isolation metadata, and contract rules.
- Read `executor_runtime_bootstrap.md` and `runtime_bootstrap_guide.md` only for helper-runtime mechanics. These files do not replace the live subagent path for `guided_agent` or `strict_refactor`, and they document the fail-closed reviewer helper boundary.
- Read `run_workflow.md` only when the run-based execution substrate itself is the task surface.
- Use the prompt files in `prompts/` as role mirrors of the active workflow, not as higher-precedence policy documents.

Document roles:
- `governor_workflow.md`: authoritative governor sequencing, dispatch-first discipline, finalize-before-pause behavior, hard stop/continue gating, and decision flow
- `governor_executor_workflow.md`: concise architecture map and silent-by-default branch behavior
- `governor_executor_dispatch_contract.md`: artifact schema, execution-mode contract, and overlap-isolation metadata
- `executor_runtime_bootstrap.md`: helper-backed runtime behavior
- `runtime_bootstrap_guide.md`: command examples for the helper-backed runtime
