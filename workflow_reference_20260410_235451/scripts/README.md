# Scripts

This folder contains repo-local helpers for agent coordination, dataset generation, diagnostics, and validation.
The current layout is intentionally flat; use the categories below to find the right helper without moving files yet.

## Agent-context maintenance

- `generate_agent_context_index.py`
- `check_agent_context_index.py`
- `install_agent_context_hooks.sh`
- `watch_agent_context.py`

## Dispatch, review, and run helpers

- `governor_emit_dispatch.py`
- `governor_emit_micro_dispatch.py`
- `executor_consume_dispatch.py`
- `reviewer_consume_dispatch.py`
- `reviewer_contract.py`
- `governor_finalize_dispatch.py`
- `dispatch_start_guard.py`
- `check_lane_merge_ready.py`
- `spawn_bridge_core.py`
- `validate_dispatch_contract.py`
- `validate_run_contract.py`
- `scaffold_run.py`

## Harness runtime and acceptance helpers

- `harness_runtime.py`
- `harness_artifacts.py`
- `run_sample_acceptance.py`
- `refresh_post_integration_aggregate_snapshot.py`
- `refresh_post_integration_guard_acceptance.py`
- `refresh_sample5_correctness_chain.py`
- `refresh_sample_trace_evidence.py`

## Harness investigation queries

- `harness_queries.py`
- `query_lineage_event.py`
- `query_trigger_window.py`
- `compare_prune_cases.py`

## Event-normalization data and models

- `build_event_normalization_dataset.py`
- `compare_event_normalization_downstream.py`
- `inspect_event_normalization_failures.py`
- `train_event_normalization_logreg.py`
- `train_event_normalization_tiny_mlp.py`
- `refresh_wider_sample_aggregate_snapshot.py`
- `refresh_wider_sample_evidence_batch1.py`
- `refresh_wider_sample_evidence_batch2.py`
- `refresh_wider_sample_evidence_batch3.py`
- `refresh_wider_sample_evidence_batch4.py`

## Sample diagnostics and guard reviews

- `inspect_sample2_tail_drift.py`
- `inspect_sample5_birth_gap.py`
- `inspect_sample5_blue_p5_burst_context.py`
- `inspect_sample5_blue_p5_flash_source.py`
- `inspect_sample5_late_none_feature_diagnostic.py`
- `inspect_sample5_middle_window_miss.py`
- `inspect_sample5_red_p2_flash_path.py`
- `inspect_sample5_red_p2_slot_alignment.py`
- `inspect_sample5_window_birth_context.py`
- `inspect_sample5_window_competition_metrics.py`
- `inspect_sample8_batch_vs_single_parity.py`
- `inspect_sample8_blue_p5_spell_ready_source.py`
- `inspect_sample8_blue_p5_temporal_priming.py`
- `inspect_sample8_replay_transition_history.py`
- `inspect_sample8_second_region_split.py`
- `inspect_sample8_start_offset_state_history.py`
- `inspect_sample8_window_birth_stability.py`
- `inspect_blue_p5_spell2_offset_grid.py`
- `inspect_blue_p5_spell2_roi_bias.py`
- `inspect_blue_p5_spell2_threshold_margin.py`
- `inspect_blue_p5_state_history_boundary.py`
- `inspect_blue_p5_temporal_hysteresis_grid.py`
- `inspect_blue_p5_temporal_policy_combo_grid.py`
- `inspect_flash_guard_shared_path.py`
- `review_blue_p5_roi_offset_guard.py`
- `review_blue_p5_temporal_policy_guard.py`
- `review_blue_p5_temporal_policy_window_eval_truth.py`
- `review_sample5_window_birth_patch_guard.py`

## Validation and checks

- `check_correctness_requirements.py`
- `verify_architecture.sh`

## Conventions

- Keep scripts grouped by function when documenting or reviewing them.
- Prefer updating a script in place over proposing a mass move.
- Treat new scripts as belonging to one of the categories above so the folder stays navigable.
- The helper-backed dispatch path includes emit, consume, review/finalize, and spawn-bridge support; keep those helpers documented together so the current workflow stays discoverable.
- The harness investigation query tools currently target the committed `sample6` and `sample2` replay diagnosis surfaces first; expand support only after the narrow flow feels useful.
