# Enforcement Model

## Core Conclusion
The workflow reference tree shows that the orchestration layer is not just a
set of docs and not just a set of scripts.

Its key principle is alignment across multiple control surfaces:
- policy docs define what must be true
- prompts and skills translate that policy into model behavior
- runtime config constrains who can do what
- scripts enforce the lifecycle fail-closed
- architecture checks verify those surfaces still agree

The final orchestration layer should preserve this relationship while reducing
the number of runtime-facing files an agent has to synthesize.

## The Five Control Surfaces

### 1. Policy And Precedence
Policy docs define authority, stop rules, workflow truth, and sequencing.

Examples from the workflow reference:
- `AGENTS.md`
- `docs/governance/`
- `docs/operations/governor_workflow.md`
- `docs/operations/governor_executor_dispatch_contract.md`

These answer: "what should the system do?"

### 2. Model-Facing Mirrors
Prompts and skills compress policy into instructions models can actually
follow during execution.

Examples from the workflow reference:
- `docs/operations/prompts/agentA_governor_prompt.txt`
- `docs/operations/prompts/agentB_executor_prompt.txt`
- `docs/operations/prompts/agentR_reviewer_prompt.txt`
- `skills/governor-workflow/SKILL.md`
- `skills/spawn-bridge/SKILL.md`
- `skills/routing/SKILL.md`

These answer: "how should the model behave under that policy?"

### 3. Runtime Role Constraints
Runtime config turns role semantics into concrete limits.

Examples from the workflow reference:
- `.codex/config.toml`
- `.codex/agents/executor.toml`
- `.codex/agents/executor-heavy.toml`
- `.codex/agents/reviewer.toml`

These answer: "what is this role allowed to do at runtime?"

### 4. Fail-Closed Lifecycle Code
Scripts enforce the state machine and reject illegal transitions.

Examples from the workflow reference:
- `scripts/governor_emit_dispatch.py`
- `scripts/validate_dispatch_contract.py`
- `scripts/dispatch_start_guard.py`
- `scripts/spawn_bridge_core.py`
- `scripts/executor_consume_dispatch.py`
- `scripts/reviewer_consume_dispatch.py`
- `scripts/governor_finalize_dispatch.py`
- `scripts/governor_transition.py`
- `scripts/check_governor_interrupt_gate.py`
- `scripts/check_governor_liveness.py`
- `scripts/check_lane_merge_ready.py`

These answer: "what happens if the model drifts or the state is illegal?"

### 5. Alignment Audit
The system also needs a way to check that policy, prompts, config, and code
still match.

Example from the workflow reference:
- `scripts/verify_architecture.sh`
- `skills/architecture-audit/SKILL.md`

These answer: "do the rule surfaces still agree?"

## Why This Matters
The workflow reference is valuable because it already demonstrates that the
real orchestration problem is not "write more docs."

The real problem is making sure critical harness rules exist in more than one
place and that those places reinforce each other.

High-risk rules should not exist in prose only.
High-risk rules should not exist in prompts only.
High-risk rules should not exist in scripts only.

For the shipped system, the important rules should appear in aligned forms.

## Examples

### Human Interrupt Discipline
The rule "do not interrupt the human for routine internal churn" appears in:
- policy docs
- governor prompt and workflow skill
- transition and interrupt-gate code

That is the correct pattern.

### Dispatch-First Discipline
The rule "substantive governed work must begin with a dispatch" appears in:
- top-level policy
- governor loop docs
- governor prompt
- dispatch emission and validation code

That is the correct pattern.

### Reviewer Advisory-Only
The rule "reviewer is advisory only" appears in:
- authority/governance docs
- reviewer prompt
- reviewer runtime config
- reviewer contract validation

That is the correct pattern.

### Governor-Only Advisors
The rule "only the Governor may use advisor tools" should appear in:
- authority docs
- governor-facing skills
- non-governor prompts/configs as explicit prohibition
- advisory runtime wiring

That is the correct pattern.

## Implication For The Final Orchestration Layer
The final orchestration layer should not merely copy the workflow reference
tree. It should distill it into one narrower runtime-facing surface while
preserving the control-surface pattern above.

The final structure should ensure:
- one canonical policy surface
- one model-facing instruction surface
- one runtime constraint surface
- one fail-closed enforcement surface
- one audit surface

The key design goal is not fewer rules.
The key design goal is fewer scattered places an agent must read while still
keeping important rules reinforced and enforceable.
