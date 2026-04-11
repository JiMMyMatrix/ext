# Governor Advisory Support

## Role
The advisory MCP server and its skills exist to help the Governor on difficult,
high-risk, or uncertain problems.

## Hard Boundary
Only the Governor may use advisor tools.

Not allowed:
- UX
- Intake
- Orchestration control-plane logic acting on its own
- Executor
- Reviewer

## Semantics
- advisor output is advice only
- advisor output is not workflow truth
- advisor output is not interrupt authority
- advisor output is not merge authority
- advisor output is not actor authority

## Runtime Meaning
Advisory tools are a Governor-scoped capability, not a shared system
capability.

They may help the Governor reason, but the Governor remains the single final
decider.
