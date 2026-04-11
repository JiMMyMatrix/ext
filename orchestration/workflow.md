# Runtime Flow

## End-To-End Shape
1. Human submits a request through the local VS Code Extension UX.
2. Intake handles raw natural language and asks bounded clarification when
   needed.
3. Orchestration accepts intake and binds lane/branch/task context.
4. Governor reads the accepted intake plus current lane state.
5. Governor decides the next bounded work-plane action.
6. Orchestration executes actor launches and transition control based on
   Governor-authorized intent.
7. Executor performs substantive work inside declared scope.
8. Reviewer verifies outputs in read-only advisory mode when required.
9. Governor accepts, rejects, redispatches, routes review, integrates, or
   escalates.
10. Human interruption happens only if the legal stop conditions are actually
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

## Where Enforcement Lives
This workflow is enforced through aligned surfaces:
- policy and precedence docs define the rule
- prompts and skills mirror the rule for model behavior
- runtime config constrains role capability
- lifecycle scripts fail closed when the state is illegal

That relationship is part of the orchestration design, not accidental
documentation overlap.
