#!/bin/bash
set -e

echo "=== Architecture Verification ==="
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Branch: $(git branch --show-current 2>/dev/null || echo 'unknown')"
echo ""

PASS=0
FAIL=0

check() {
    if eval "$2" > /dev/null 2>&1; then
        echo "  PASS: $1"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $1"
        FAIL=$((FAIL + 1))
    fi
}

echo "--- Runtime Config ---"
check ".codex/config.toml exists" "test -f .codex/config.toml"
check "Governor model is gpt-5.4" "grep -q 'model = \"gpt-5.4\"' .codex/config.toml"
check "Governor reasoning is xhigh" "grep -q 'model_reasoning_effort = \"xhigh\"' .codex/config.toml"
check "agents section exists" "grep -q '\[agents\]' .codex/config.toml"
check "spawn_bridge MCP config exists" "grep -q '\[mcp_servers\\.spawn_bridge\]' .codex/config.toml"
check "spawn_bridge command is python3" "grep -q 'command = \"python3\"' .codex/config.toml"
check "spawn_bridge args point to repo-local server" "grep -q 'args = \\[\"mcp/spawn_bridge_server.py\"\\]' .codex/config.toml"
check "spawn_bridge server file exists" "test -f mcp/spawn_bridge_server.py || git cat-file -e HEAD:mcp/spawn_bridge_server.py"
check ".codex/agents/executor.toml exists" "test -f .codex/agents/executor.toml"
check "Executor model is gpt-5.3-codex" "grep -q 'model = \"gpt-5.3-codex\"' .codex/agents/executor.toml"
check "Executor reasoning is xhigh" "grep -q 'model_reasoning_effort = \"xhigh\"' .codex/agents/executor.toml"
check "Executor sandbox is workspace-write" "grep -q 'sandbox_mode = \"workspace-write\"' .codex/agents/executor.toml"
check "Executor has ambiguity protocol" "grep -q 'ambiguous_instruction' .codex/agents/executor.toml"
check "Executor blocks advisory tools" "grep -q 'advisory MCP tools' .codex/agents/executor.toml"
check ".codex/agents/executor-heavy.toml exists" "test -f .codex/agents/executor-heavy.toml"
check "Heavy executor model is gpt-5.4" "grep -q 'model = \"gpt-5.4\"' .codex/agents/executor-heavy.toml"
check "Heavy executor reasoning is xhigh" "grep -q 'model_reasoning_effort = \"xhigh\"' .codex/agents/executor-heavy.toml"
check ".codex/agents/reviewer.toml exists" "test -f .codex/agents/reviewer.toml"
check "Reviewer model is gpt-5.4" "grep -q 'model = \"gpt-5.4\"' .codex/agents/reviewer.toml"
check "Reviewer reasoning is xhigh" "grep -q 'model_reasoning_effort = \"xhigh\"' .codex/agents/reviewer.toml"
check "Reviewer sandbox is read-only" "grep -q 'sandbox_mode = \"read-only\"' .codex/agents/reviewer.toml"

echo ""
echo "--- Governance Docs ---"
check "AGENTS.md exists" "test -f AGENTS.md"
check "INDEX.md exists" "test -f docs/agent_context/INDEX.md"
check "Operating spec exists" "test -f docs/agent_context/operating_spec.md"
check "Advisory protocol exists" "test -f docs/agent_context/advisory_protocol.md"
check "Autonomous execution spec exists" "test -f docs/agent_context/autonomous_execution_spec.md"
check "Executor subagent spec exists" "test -f docs/agent_context/executor_subagent_spec.md"
check "Reviewer subagent spec exists" "test -f docs/agent_context/reviewer_subagent_spec.md"
check "Weakness registry exists" "test -f docs/agent_context/executor_known_weaknesses.md"
check "Dispatch contract exists" "test -f docs/operations/governor_executor_dispatch_contract.md"
check "Governor prompt exists" "test -f docs/operations/prompts/agentA_governor_prompt.txt"
check "Executor prompt exists" "test -f docs/operations/prompts/agentB_executor_prompt.txt"
check "Reviewer prompt exists" "test -f docs/operations/prompts/agentR_reviewer_prompt.txt"
check "Harness lane spec exists" "test -f docs/agent_context/harness_stabilization_lane_spec.md"
check "Harness runtime helper exists" "test -f scripts/harness_runtime.py"
check "Harness artifact helper exists" "test -f scripts/harness_artifacts.py"
check "Sample acceptance runner exists" "test -f scripts/run_sample_acceptance.py"
check "Reviewer consume helper exists" "test -f scripts/reviewer_consume_dispatch.py"
check "Reviewer contract helper exists" "test -f scripts/reviewer_contract.py"
check "Governor finalize helper exists" "test -f scripts/governor_finalize_dispatch.py"

echo ""
echo "--- Model Name Consistency ---"
check "No gpt-5.4-xhigh anywhere" "! grep -rq 'gpt-5\.4-xhigh' AGENTS.md docs/ .codex/"
check "No gpt5.4 (missing hyphen) anywhere" "! grep -rq 'gpt5\.4' AGENTS.md docs/ .codex/"
check "No plain gpt-5.3 anywhere" "! grep -rPq 'gpt-5\\.3(?!-codex)' AGENTS.md docs/ .codex/"
check "No fictional --tools Read flag in docs" "! grep -rq '\-\-tools \"Read(' docs/"
check "No fictional --max-turns in subagent spec" "! grep -rq '\-\-max-turns' docs/agent_context/executor_subagent_spec.md 2>/dev/null; true"
check "No fictional --approval-mode in docs" "! grep -rq '\-\-approval-mode full-auto' docs/"

echo ""
echo "--- MCP Server ---"
MCP_PATH=""
if [ -f "/root/mcp_server.py" ]; then
    MCP_PATH="/root/mcp_server.py"
elif [ -f "mcp/mcp_server.py" ]; then
    MCP_PATH="mcp/mcp_server.py"
elif [ -f "mcp_server.py" ]; then
    MCP_PATH="mcp_server.py"
fi

if [ -n "$MCP_PATH" ]; then
    check "MCP server file found at $MCP_PATH" "true"
    check "Aggregate quota defined" "grep -q 'AGGREGATE_MAX_CALLS' $MCP_PATH"
    check "Cycle ID validation defined" "grep -q '_VALID_CYCLE_ID' $MCP_PATH"
    check "Section validation defined" "grep -q '_validate_sections' $MCP_PATH"
    check "State persistence defined" "grep -q 'STATE_DUMP_PATH\|_dump_state' $MCP_PATH"
else
    echo "  FAIL: MCP server file not found"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "--- Dispatch Contract ---"
DC="docs/operations/governor_executor_dispatch_contract.md"
if [ -f "$DC" ]; then
    check "guided_agent mode documented" "grep -q 'guided_agent' $DC"
    check "strict_refactor mode documented" "grep -q 'strict_refactor' $DC"
    check "sample_acceptance mode documented" "grep -q 'sample_acceptance' $DC"
    check "forbidden_command_patterns documented" "grep -q 'forbidden_command_patterns' $DC"
    check "injected_weakness_guards documented" "grep -q 'injected_weakness_guards' $DC"
    check "cycle identity contract documented" "grep -qi 'cycle.*identity\|cycle_id.*dispatch_ref' $DC"
    check "task_track documented" "grep -q 'task_track' $DC"
    check "retry_handoff documented" "grep -q 'retry_handoff' $DC"
    check "failure_category documented" "grep -q 'failure_category' $DC"
    check "durable eval storage documented" "grep -q '\.agent/runs/evals' $DC"
    check "depends_on_dispatches documented" "grep -q 'depends_on_dispatches' $DC"
    check "scope_reservations documented" "grep -q 'scope_reservations' $DC"
    check "overlap_isolation documented" "grep -q 'overlap_isolation' $DC"
    check "overlap integration policies documented" "grep -q 'choose_one' $DC && grep -q 'can_stack' $DC"
else
    echo "  FAIL: Dispatch contract not found at $DC"
    FAIL=$((FAIL + 1))
fi

echo ""
echo "--- Workflow Alignment ---"
check "Governor workflow documents executor smoke test" "grep -qi 'Executor availability smoke test' docs/operations/governor_workflow.md"
check "Governor workflow documents harness runtime preflight" "grep -qi 'Harness runtime preflight' docs/operations/governor_workflow.md"
check "Governor workflow documents durable eval and checkpoint storage" "grep -qi 'Durable eval and checkpoint storage' docs/operations/governor_workflow.md"
check "Governor workflow documents heavy runtime alignment" "grep -qi 'Heavy-executor runtime alignment' docs/operations/governor_workflow.md"
check "Governor workflow documents diagnosis-first discipline" "grep -qi 'Diagnosis-first dispatch discipline' docs/operations/governor_workflow.md"
check "Governor workflow documents in-lane runtime patch authorization" "grep -qi 'Runtime patch authorization inside an active lane' docs/operations/governor_workflow.md"
check "Governor workflow documents retry handoff" "grep -qi 'Retry handoff template' docs/operations/governor_workflow.md"
check "Governor workflow documents reviewer protocol" "grep -qi 'Reviewer protocol' docs/operations/governor_workflow.md"
check "Governor workflow documents governor finalize helper" "grep -q 'governor_finalize_dispatch.py' docs/operations/governor_workflow.md"
check "Governor workflow documents tracked-path discipline" "grep -qi 'Tracked-path discipline' docs/operations/governor_workflow.md"
check "Governor workflow documents silent-by-default behavior" "grep -qi 'Silent-by-default branch behavior' docs/operations/governor_workflow.md"
check "Governor workflow documents limited parallelism" "grep -qi 'Limited safe parallelism' docs/operations/governor_workflow.md"
check "Governor workflow documents optional overlap isolation" "grep -qi 'Optional overlap isolation' docs/operations/governor_workflow.md"
check "Governor workflow documents merge-ready gate" "grep -qi 'Merge-ready gate' docs/operations/governor_workflow.md"
check "Governor workflow documents micro-dispatch eligibility" "grep -qi 'Micro-dispatch eligibility' docs/operations/governor_workflow.md"
check "AGENTS documents missing-dispatch violation" "grep -qi 'substantive lane work' AGENTS.md && grep -qi 'dispatch' AGENTS.md && grep -qi 'workflow' AGENTS.md && grep -qi 'violation' AGENTS.md"
check "AGENTS documents silent-by-default behavior" "grep -qi 'routine dispatch/review/validation loops are internal' AGENTS.md"
check "AGENTS documents finalize-before-pause rule" "grep -qi 'finalize it through' AGENTS.md && grep -qi 'governor_decision.json' AGENTS.md && grep -qi 'human-facing pause' AGENTS.md"
check "AGENTS documents interrupt gate" "grep -q 'proposed_transition.json' AGENTS.md && grep -q 'check_governor_interrupt_gate.py' AGENTS.md && grep -q 'check_governor_liveness.py' AGENTS.md"
check "AGENTS documents governor stall rule" "grep -qi 'governor_stall' AGENTS.md"
check "AGENTS documents context rollover as internal continuation" "grep -qi 'Context-window rollover or session handoff is an internal continuation point' AGENTS.md"
check "AGENTS documents micro-dispatch helper" "grep -q 'governor_emit_micro_dispatch.py' AGENTS.md"
check "AGENTS documents dependency completion rule" "grep -qi 'governor_decision.json' AGENTS.md && grep -qi 'non-empty validation evidence' AGENTS.md"
check "AGENTS documents optional overlap isolation" "grep -qi 'optional git-worktree overlap isolation' AGENTS.md"
check "AGENTS documents merge-ready gate" "grep -q 'check_lane_merge_ready.py' AGENTS.md"
check "Modes and roles documents finalize-before-pause rule" "grep -qi 'governor_decision.json' docs/governance/modes_and_roles.md && grep -qi 'human-facing pause' docs/governance/modes_and_roles.md"
check "Modes and roles document interrupt gate" "grep -q 'proposed_transition.json' docs/governance/modes_and_roles.md && grep -q 'interrupt gate' docs/governance/modes_and_roles.md && grep -q 'liveness gate' docs/governance/modes_and_roles.md"
check "Modes and roles documents context rollover as internal continuation" "grep -qi 'internal continuation point' docs/governance/modes_and_roles.md"
check "Runtime rules document finalize-before-pause discipline" "grep -qi 'governor_decision.json' docs/governance/runtime_and_executor.md && grep -qi 'human-facing pause' docs/governance/runtime_and_executor.md"
check "Runtime rules document interrupt gate" "grep -q 'proposed_transition.json' docs/governance/runtime_and_executor.md && grep -q 'interrupt gate' docs/governance/runtime_and_executor.md && grep -q 'liveness gate' docs/governance/runtime_and_executor.md"
check "Runtime rules document reviewer contract violation" "grep -qi 'reviewer_contract_violation' docs/governance/runtime_and_executor.md"
check "Lane authority documents finalize-before-pause before human interruption" "grep -qi 'governor_decision.json' docs/governance/lane_and_authority.md && grep -qi 'human-facing pause' docs/governance/lane_and_authority.md"
check "Lane authority documents governor stall handling" "grep -qi 'governor_stall' docs/governance/lane_and_authority.md && grep -q 'check_governor_interrupt_gate.py' docs/governance/lane_and_authority.md"
check "Governance README documents interrupt/liveness gate" "grep -q 'interrupt gate' docs/governance/README.md && grep -q 'liveness gate' docs/governance/README.md"
check "Artifact contracts document checkpoint artifact" "grep -qi '## Checkpoint artifact' docs/agent_context/artifact_contracts.md"
check "Artifact contracts document approved interpreter" "grep -q 'abba/.venv/bin/python' docs/agent_context/artifact_contracts.md"
check "Governor prompt documents executor smoke test" "grep -qi 'Executor availability smoke test' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents reviewer protocol" "grep -qi 'Reviewer protocol' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents reviewer contract violation handling" "grep -qi 'reviewer_contract_violation' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents task_track" "grep -q 'task_track' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents integrated baseline" "grep -qi 'Integrated baseline on \`main\`' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents missing-dispatch violation" "grep -qi 'Missing dispatch for substantive lane work is a workflow violation' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents silent-by-default rule" "grep -qi 'Silent-by-default rule' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents finalize-before-pause rule" "grep -qi 'finalize it through' docs/operations/prompts/agentA_governor_prompt.txt && grep -qi 'governor_decision.json' docs/operations/prompts/agentA_governor_prompt.txt && grep -qi 'human-facing pause' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents context rollover as internal continuation" "grep -qi 'context-window rollover or session handoff is an internal continuation point' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents limited parallel dispatch" "grep -qi 'Limited parallel dispatch' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents optional overlap isolation" "grep -qi 'Optional overlap isolation' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents merge-ready gate" "grep -qi 'Merge-ready gate' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor prompt documents micro-dispatch boundary" "grep -qi 'Use micro-dispatch only for clearly low-risk' docs/operations/prompts/agentA_governor_prompt.txt"
check "Governor executor workflow documents finalize-before-pause rule" "grep -qi 'governor_decision.json' docs/operations/governor_executor_workflow.md && grep -qi 'human-facing pause' docs/operations/governor_executor_workflow.md"
check "Governor executor workflow documents reviewer contract violation" "grep -qi 'reviewer_contract_violation' docs/operations/governor_executor_workflow.md"
check "Governor executor workflow documents context rollover as internal continuation" "grep -qi 'internal continuation point' docs/operations/governor_executor_workflow.md"
check "Executor prompt documents task-track discipline" "grep -qi 'Task-Track Discipline' docs/operations/prompts/agentB_executor_prompt.txt"
check "Executor prompt documents reviewer handoff" "grep -qi 'Reviewer Handoff Expectations' docs/operations/prompts/agentB_executor_prompt.txt"
check "Executor prompt documents retry handoff" "grep -qi 'Retry Handoff Consumption' docs/operations/prompts/agentB_executor_prompt.txt"
check "Executor prompt documents integrated baseline" "grep -qi 'Integrated baseline on \`main\`' docs/operations/prompts/agentB_executor_prompt.txt"
check "Executor prompt blocks missing dispatch" "grep -q 'blocker=missing_dispatch' docs/operations/prompts/agentB_executor_prompt.txt"
check "Executor prompt documents isolated worktree discipline" "grep -qi 'isolated worktree' docs/operations/prompts/agentB_executor_prompt.txt && grep -qi 'do not merge' docs/operations/prompts/agentB_executor_prompt.txt"
check "Runtime bootstrap documents governor decision artifact" "grep -q 'governor_decision.json' docs/operations/executor_runtime_bootstrap.md"
check "Runtime bootstrap documents reviewer contract guard" "grep -qi 'reviewer_contract.py' docs/operations/executor_runtime_bootstrap.md && grep -qi 'reviewer_contract_violation' docs/operations/runtime_bootstrap_guide.md"
check "Runtime bootstrap documents start guard" "grep -qi 'Helper-runtime start guard' docs/operations/executor_runtime_bootstrap.md"
check "Runtime bootstrap documents finalize-before-pause rule" "grep -qi 'governor_decision.json' docs/operations/executor_runtime_bootstrap.md && grep -qi 'human-facing' docs/operations/executor_runtime_bootstrap.md && grep -qi 'pause, summary, or handoff' docs/operations/executor_runtime_bootstrap.md"
check "Runtime bootstrap documents interrupt gate" "grep -q 'proposed transition' docs/operations/executor_runtime_bootstrap.md && grep -q 'interrupt/liveness gate' docs/operations/executor_runtime_bootstrap.md"
check "Runtime guide documents governor decision artifact" "grep -q 'governor_decision.json' docs/operations/runtime_bootstrap_guide.md"
check "Runtime guide documents micro-dispatch helper" "grep -q 'governor_emit_micro_dispatch.py' docs/operations/runtime_bootstrap_guide.md"
check "Runtime guide documents merge-ready requirements" "grep -qi 'needs_review' docs/operations/runtime_bootstrap_guide.md && grep -qi 'completion signals' docs/operations/runtime_bootstrap_guide.md"
check "Runtime guide documents merge-ready gate" "grep -q 'check_lane_merge_ready.py' docs/operations/runtime_bootstrap_guide.md"
check "Runtime guide documents finalize-before-pause rule" "grep -qi 'dispatch finished cleanly' docs/operations/runtime_bootstrap_guide.md && grep -qi 'human-facing pause' docs/operations/runtime_bootstrap_guide.md && grep -qi 'governor_decision.json' docs/operations/runtime_bootstrap_guide.md"
check "Runtime guide documents interrupt gate" "grep -q 'proposed transition' docs/operations/runtime_bootstrap_guide.md && grep -q 'interrupt/liveness gates' docs/operations/runtime_bootstrap_guide.md"
check "Micro-dispatch helper script exists" "test -f scripts/governor_emit_micro_dispatch.py"
check "Merge-ready gate script exists" "test -f scripts/check_lane_merge_ready.py"
check "Dispatch start guard script exists" "test -f scripts/dispatch_start_guard.py"
check "Overlap worktree helper script exists" "test -f scripts/overlap_worktree.py"
check "Sample6 lane is frozen reference" "grep -qi 'frozen as a completed reference' docs/agent_context/sample6_missed_window_lane_spec.md"
check "Escalation spec uses gpt-5.4 heavy model" "grep -q 'gpt-5.4' docs/agent_context/executor_escalation_spec.md"
check "Escalation spec documents harness dependency note" "grep -qi 'Harness dependency note' docs/agent_context/executor_escalation_spec.md"

echo ""
echo "--- Skill Alignment ---"
SKILL_ROOT="/workspace/.codex_brain/skills"
if [ -d "$SKILL_ROOT" ]; then
    if [ -f "$SKILL_ROOT/governor-workflow/SKILL.md" ]; then
        check "Governor workflow skill documents overlap isolation" "grep -qi 'Optional overlap isolation' $SKILL_ROOT/governor-workflow/SKILL.md"
        check "Governor workflow skill documents governor-only overlap integration" "grep -qi 'only integration authority' $SKILL_ROOT/governor-workflow/SKILL.md && grep -qi 'governor_decision.json' $SKILL_ROOT/governor-workflow/SKILL.md"
        check "Governor workflow skill documents interrupt gate" "grep -q 'proposed_transition.json' $SKILL_ROOT/governor-workflow/SKILL.md && grep -q 'check_governor_interrupt_gate.py' $SKILL_ROOT/governor-workflow/SKILL.md && grep -q 'check_governor_liveness.py' $SKILL_ROOT/governor-workflow/SKILL.md"
        check "Governor workflow skill documents governor stall" "grep -qi 'governor_stall' $SKILL_ROOT/governor-workflow/SKILL.md"
    fi
    if [ -f "$SKILL_ROOT/spawn-bridge/SKILL.md" ]; then
        check "Spawn bridge skill documents overlap-isolated handoff" "grep -qi 'overlap isolation' $SKILL_ROOT/spawn-bridge/SKILL.md && grep -qi 'isolated worktree' $SKILL_ROOT/spawn-bridge/SKILL.md"
        check "Spawn bridge skill treats bridge steps as internal" "grep -qi 'internal workflow steps' $SKILL_ROOT/spawn-bridge/SKILL.md"
    fi
    if [ -f "$SKILL_ROOT/architecture-audit/SKILL.md" ]; then
        check "Architecture audit skill checks overlap isolation" "grep -qi 'optional overlap isolation' $SKILL_ROOT/architecture-audit/SKILL.md && grep -qi 'governor-only integration' $SKILL_ROOT/architecture-audit/SKILL.md"
        check "Architecture audit skill checks interrupt gate" "grep -qi 'interrupt/liveness gate' $SKILL_ROOT/architecture-audit/SKILL.md && grep -qi 'governor_stall' $SKILL_ROOT/architecture-audit/SKILL.md"
    fi
fi

echo ""
echo "==============================="
echo "Results: $PASS passed, $FAIL failed"
echo "==============================="
if [ $FAIL -gt 0 ]; then
    echo "STATUS: FAIL — $FAIL checks need attention"
    exit 1
else
    echo "STATUS: PASS — all checks passed"
    exit 0
fi
