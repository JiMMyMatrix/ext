#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

PASS=0
FAIL=0

check() {
  if eval "$2" > /dev/null 2>&1; then
    echo "PASS: $1"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $1"
    FAIL=$((FAIL + 1))
  fi
}

echo "ARCHITECTURE AUDIT"
echo "Repo: $ROOT"
echo

check "AGENTS entrypoint exists" "test -f AGENTS.md"
check "Orchestration README exists" "test -f orchestration/README.md"
check "Harness package exists" "test -f orchestration/harness/cli.py && test -f orchestration/harness/session.py && test -f orchestration/harness/intake.py && test -f orchestration/harness/contracts.py && test -f orchestration/harness/dispatch.py && test -f orchestration/harness/transition.py && test -f orchestration/harness/audit.py && test -f orchestration/harness/paths.py"
check "Canonical orchestration CLI exists" "test -f orchestration/scripts/orchestrate.py"
check "orchestrate wrapper imports harness entrypoint" "rg -n 'from orchestration\\.harness\\.cli import main' orchestration/scripts/orchestrate.py > /dev/null"
check "Contracts exist" "test -f orchestration/contracts/intake.json && test -f orchestration/contracts/dispatch.md && test -f orchestration/contracts/ux.md && test -f orchestration/contracts/transition.md"
check "Prompts exist" "test -f orchestration/prompts/intake_shell.txt && test -f orchestration/prompts/governor.txt && test -f orchestration/prompts/executor.txt && test -f orchestration/prompts/reviewer.txt"
check "Runtime actor configs exist" "test -f orchestration/runtime/actors/executor.toml && test -f orchestration/runtime/actors/executor-heavy.toml && test -f orchestration/runtime/actors/reviewer.toml"
check "Advisory runtime exists" "test -f orchestration/runtime/advisory/mcp_server.py"
check "Intake runtime exists" "test -f orchestration/scripts/intake_shell.py && test -f orchestration/scripts/orchestrator_accept_intake.py && test -f orchestration/scripts/validate_intake_contract.py && test -f orchestration/scripts/ui_session_action.py"
check "Dispatch lifecycle scripts exist" "test -f orchestration/scripts/governor_emit_dispatch.py && test -f orchestration/scripts/validate_dispatch_contract.py && test -f orchestration/scripts/check_governor_interrupt_gate.py && test -f orchestration/scripts/check_governor_liveness.py && test -f orchestration/scripts/check_lane_merge_ready.py"
check "Surface path helper exists" "test -f orchestration/scripts/surface_paths.py"
check "Extension uses canonical orchestration CLI" "rg -n 'orchestrate\\.py' src/executionTransport.ts > /dev/null && ! rg -n 'ui_session_action\\.py' src/executionTransport.ts > /dev/null"
check "Audit skill uses canonical orchestration CLI" "rg -n 'orchestrate\\.py audit verify-architecture' orchestration/skills/architecture-audit/SKILL.md > /dev/null"
check "Prompts do not reference legacy workflow tree" "! rg -n 'workflow_reference_20260410_235451' orchestration/prompts > /dev/null"
check "Skills do not reference legacy workflow tree" "! rg -n 'workflow_reference_20260410_235451' orchestration/skills > /dev/null"
check "Runtime has no legacy docs references" "! rg -n 'docs/(operations|agent_context|governance)/' orchestration/scripts orchestration/runtime orchestration/harness --glob '*.py' --glob '!**/__pycache__/**' > /dev/null"
check "Runtime has no legacy actor-config references" "! rg -n '\\.codex/agents/' orchestration/scripts orchestration/runtime orchestration/harness --glob '*.py' --glob '!**/__pycache__/**' > /dev/null"
check "Governor-only advisor rule is documented" "rg -n 'Only the Governor may use advisor tools|only the Governor may use advisor tools' AGENTS.md orchestration > /dev/null"
check "Non-governor prompts forbid advisor use" "rg -n 'do not use advisor tools|must not use advisor tools' orchestration/prompts/intake_shell.txt orchestration/prompts/executor.txt orchestration/prompts/reviewer.txt > /dev/null"
check "request.json remains dispatch truth" "rg -n 'request\\.json' AGENTS.md orchestration > /dev/null && rg -n 'dispatch truth' AGENTS.md orchestration > /dev/null"
check "Intake artifacts remain distinct" "rg -n 'accepted_intake\\.json|request_draft\\.json|raw_human_request\\.md' orchestration > /dev/null"
check "Orchestration tests include structure audit" "test -f orchestration/tests/test_structure.py"
check "Workflow reference marked as reference only" "rg -n 'development/reference material' AGENTS.md orchestration/README.md > /dev/null"

echo
echo "SUMMARY: $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
