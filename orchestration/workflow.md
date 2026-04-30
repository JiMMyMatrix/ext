# Runtime Flow

## End-To-End Shape
1. Human submits a request through the local VS Code Extension UX.
2. Intake handles raw natural language and asks bounded clarification when
   needed.
3. Orchestration accepts intake and binds lane/branch/task context.
4. Governor reads the accepted intake plus current lane state.
5. Governor decides the next bounded work-plane action.
6. When the Governor encounters a truly difficult, high-risk, ambiguous, or
   repeatedly failing problem, it may consult Governor-only advisors through
   the advisory MCP server before deciding.
7. Orchestration executes actor launches and transition control based on
   Governor-authorized intent.
8. Executor performs substantive work inside declared scope.
9. Reviewer verifies outputs in read-only advisory mode when required.
10. Governor accepts, rejects, redispatches, routes review, integrates, or
   escalates.
11. Human interruption happens only if the legal stop conditions are actually
    met.

## Human Stop Semantics
Legal human-facing stops are intentionally narrow:
- merge checkpoint
- real blocker
- missing permission or missing resource
- authority boundary
- safety boundary
- human decision that cannot be reduced safely inside the governed flow

These are not legal stop reasons by themselves:
- one dispatch completed
- one review completed
- one validator completed
- an internal checkpoint was reached
- context rollover happened

## Runtime Discipline
- Dispatch-first discipline remains intact.
- Orchestration must not invent child work that Governor did not authorize.
- Clean completed work should be finalized before any human-facing pause.
- Merge-ready remains a gated truth, not a casual status label.

## Governor Advisory Loop
Advisor MCP tools are a standard Governor capability, not an experimental side
path. They are also cost-gated. The Governor should not consult advisors for
routine work or questions it can answer confidently.

The normal routing is:
- `consult_minimax` for bounded general reasoning or option comparison without
  repo file access
- `consult_claude_headless` for read-only multi-file repo/code analysis
- `consult_architect` for repeated or non-trivial debugging with a likely
  root-cause file
- `routine_code_review` for one completed file after a bounded change

Use one advisor first. Use both MiniMax and Claude Headless only when the issue
is truly difficult and a wrong decision would cost more than two consultations.

Advisor output remains advisory only. It cannot create workflow truth, dispatch
truth, merge authority, interrupt authority, permission state, or actor launch
authority. The Governor remains the decider and orchestration still enforces
legal state transitions.

## Where Enforcement Lives
This workflow is enforced through aligned surfaces:
- policy and precedence docs define the rule
- prompts and skills mirror the rule for model behavior
- runtime config constrains role capability
- lifecycle scripts fail closed when the state is illegal

That relationship is part of the orchestration design, not accidental
documentation overlap.
