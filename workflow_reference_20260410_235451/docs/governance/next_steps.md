# Next Steps

This document tracks the current branch direction.
Keep it short, current, and branch-specific.

## Current direction

- Branch: `main`
- Active lane: none
- Focus:
  - keep `main` as the integrated baseline and governance branch
  - preserve the new interrupt/liveness gate as baseline workflow behavior
  - use a fresh dedicated branch for the next substantive workflow or runtime lane
  - keep sample evidence as guard/reference material rather than the main unit of development on `main`

## Immediate next steps

1. Push the newly integrated workflow hardening when ready.
2. Choose the next dedicated branch before any fresh substantive runtime or product work.
3. Keep `main` limited to governance, validation review, and merge/push housekeeping until that branch is opened.

## If work continues from here

1. Treat `lane/window-quality-generalization` and `lane/window-quality-generalization-resume` as evidence/reference history.
2. Keep optional overlap isolation available but non-default.
3. Preserve `choose_one` as the default isolated integration policy.
4. Use sample evidence as guards/reference material when the next dedicated runtime lane is authorized.

## Deferred after branch completion

- No deferred item is currently active on `main`; open a dedicated branch for the next substantive fix.

## Do not do next in this lane

- start fresh substantive runtime patching directly on `main`
- let isolated executor candidates integrate directly into the lane branch
- broaden into a heavy scheduler or worktree orchestration system
- treat internal workflow checkpoints as human-stop signals without a valid interrupt gate
