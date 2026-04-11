# Run Workflow

This repository uses a run directory for every non-trivial task.

## Canonical run identifier

```text
run_ref = <cycle>/<scope_type>/<scope_ref>/<artifact_kind>/<attempt>
```

Examples:

- `evidence_expansion.c02/sample/sample2/window_eval/a01`
- `evidence_expansion.c02/sample/sample2/guard_review/a01`
- `evidence_expansion.c02/aggregate/multi_sample/phase_snapshot/a01`

## Run directory

```text
.agent/runs/<cycle>/<scope_type>/<scope_ref>/<artifact_kind>/<attempt>/
```

## Minimum files

- `task.json`
- `status.json`
- `report.json`
- optional `review.json` when a read-only reviewer verifies the run output

## Execution order

### 1. Scaffold the run

Use:

```bash
python scripts/scaffold_run.py ...
```

### 2. Fill `status.json` before touching non-`.agent` files

Minimum required fields:

- `current_branch`
- `git_status_short`
- `planned_file_touch_list`
- `read_list`
- `produce_list`
- `scope`
- `non_goals`
- `stop_conditions`

Rule:
do not touch files outside `planned_file_touch_list`.

### 3. Execute the bounded task

Allowed work:
- only the declared scope
- only the declared files
- only the declared artifacts

### 4. Fill `report.json` after execution

Minimum required fields:

- `summary`
- `claims`
- `evidence`
- `outputs`
- `blocking`
- `next_action`

Recommended additional field:

- `decision`: `advance` / `stay` / `block`

### 4b. Fill `review.json` when review is required

Minimum recommended fields:

- `dispatch_ref`
- `verdict`
- `validator_assessment`
- `scope_assessment`
- `findings`
- `residual_risks`
- `recommendation`

### 5. Validate the run contract

```bash
python scripts/validate_run_contract.py .agent/runs/<...>
```

## Suggested conventions

### cycle

Use durable cycle names, for example:

- `evidence_expansion.c02`
- `artifact_observability.c01`
- `guard_review.c03`

### scope_type

Common values:

- `sample`
- `aggregate`
- `doc`
- `script`

### artifact_kind

Use the concrete bounded output, for example:

- `window_eval`
- `pairwise_eval`
- `guard_review`
- `supervisor_decision`
- `phase_snapshot`

### attempt

Use monotonic attempts:

- `a01`
- `a02`

Do not overload this with free-form labels.

## Suggested CI hook later

A later CI step can reject any non-trivial PR that:
- touches non-`.agent` files
- but has no matching run directory
- or has a run directory with missing required fields
- or claims reviewer-gated acceptance without a corresponding `review.json`
