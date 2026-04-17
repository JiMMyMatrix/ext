# Scenario Fixtures

These fixtures seed reusable repo-like orchestration state for tests and manual
sidebar runs.

Each scenario is a file-tree overlay rooted like a repo workspace. The fixture
contents use the same on-disk truth surfaces that the harness already reads:

- `.agent/orchestration/ui_session.json`
- `.agent/intakes/...`
- `.agent/dispatches/...`
- `.agent/governor/...`

## Scenarios
- `idle_ready`: a clean idle session with no active governed work.
- `clarification_analysis_focus`: intake is waiting on analysis-focus
  clarification choices.
- `ready_for_acceptance`: intake is complete and orchestration is waiting for
  approval or full access.
- `accepted_idle`: an intake has been accepted and the lane is bound, but no
  dispatch is currently active.
- `running_dispatch`: accepted work is running under Governor-led execution with
  an active dispatch.
- `completed_with_governor_decision`: the lane has a completed dispatch, a
  governor decision artifact, and a proposed transition.

## Automated Use
Python tests should use `orchestration.harness.scenario_fixtures` to copy a
named scenario into a temp repo before running harness commands.

## Manual Use
To seed the current repo for local sidebar testing, run:

```bash
python3 orchestration/scripts/load_scenario_fixture.py \
  --scenario completed_with_governor_decision \
  --root . \
  --replace
```

This is a developer-only workflow. The script copies fixture files into the
working tree and can replace the existing `.agent` overlay so the sidebar reads
the seeded state immediately.

After seeding:
1. Keep this repo open as the active VS Code workspace.
2. Press `F5`.
3. In the Extension Development Host, click the `Corgi` Activity Bar icon.

If Corgi reports that it cannot find `orchestration/scripts/orchestrate.py`,
the extension host was not opened on the correct repo workspace.
