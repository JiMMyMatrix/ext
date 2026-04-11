# Authority Matrix

## VS Code Extension UX
- Human-facing only
- Receives user input
- Renders status, approvals, interrupts, artifacts, and execution activity
- Sends user actions downward
- Must not own workflow authority
- Must not use advisor tools

## Intake
- Handles raw human natural language
- Produces a bounded request draft
- May ask bounded clarification
- Must not use advisor tools
- Must not write dispatch truth
- Must not decide merge-ready, interrupt legality, actor authority, or work
  intent

## Orchestration
- Owns intake acceptance
- Owns lane binding
- Owns stop/continue control
- Owns actor launch execution
- Owns transition arbitration
- Enforces harness rules
- Must not become a second governor
- Must not independently use advisor tools as its own authority path

## Governor
- Highest authority in the work plane
- Owns work intent
- Owns dispatch intent
- Owns child-work intent
- Owns review-routing intent
- Owns integration intent
- Only role allowed to use advisor tools

## Executor
- Single substantive writer
- Executes bounded work only
- Must not use advisor tools
- Must not reinterpret authority or broaden scope

## Reviewer
- Read-only verifier
- Advisory only
- Must not use advisor tools
- Must not write workflow-control state

## Advisory MCP Server
- Governor-only support channel
- Provides bounded advice, not decisions
- Does not write workflow truth
- Does not gain actor authority
