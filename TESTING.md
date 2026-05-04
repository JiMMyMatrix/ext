# Corgi Testing Phases

## Phase 1: Process Correctness

Use command-only tests when the question is whether the workflow is legal and
error-free. These tests do not open VS Code.

Run:

```bash
npm run test:prompts
npm run test:process
npm run test:process:modules
```

Useful variants:

```bash
npm run test:process:all
npm run test:process:executor
npm run test:process:reviewer
npm run test:process:review-replan
node scripts/corgi-process-test.cjs --prompt architecture
node scripts/corgi-process-test.cjs --prompt develop-internet --through-executor
```

Phase 1 covers orchestration/session correctness: intake, clarification,
permission, Governor plan completion, plan-ready state, dispatch creation,
Executor/Reviewer consumption, and fail-closed behavior. It uses an isolated
`.agent/command-test` runtime root so command tests do not mutate the normal
development session.

Use `test:process:modules` when the Governor path is already known-good and
the question is specifically whether Executor, Reviewer, or the
Reviewer-requested replan loop still works. The replan module uses a dedicated
test helper to force reviewer feedback outside the production dispatch helper,
then verifies that the revised plan stays in the same work folder and that the
next dispatch targets the latest plan context.

## Phase 2: UI/UX Correctness

Use window tests when the question is whether the VS Code webview looks and
feels correct.

Run:

```bash
npm run test:window
npm run test:window:architecture
npm run test:window:feature
npm run test:window:progress
```

Phase 2 covers rendering, click targets, scroll behavior, animation feel,
composer layout, visible goal state, and extension-host launch stability.

Command-only tests are not a substitute for UI/UX verification. They are the
fast first gate before opening a test window.
