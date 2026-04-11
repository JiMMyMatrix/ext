# Reference Lanes

## Active baseline references

Unless a new lane says otherwise:
- keep `sample2` as the repaired baseline reference
- keep accepted `sample5` as a guard reference
- keep accepted `sample8` as a guard reference

## Frozen lane references

The following lanes are frozen references and should not be resumed unless the
human explicitly switches lanes:

- offline training lane
- sample2 runtime lane
- sample2 replay-state-edges diagnosis lane
- flash-classification lane
- executor weakness registry lane
- sample5 window-birth lane
- sample6 missed-window lane
- sample8 spell-ready lane
- sample3 extra-window diagnosis lane
- sample5 diagnosis lane
- sample4 diagnosis lane
- post-integration evidence refresh lane
- blue_p5 vision-state lane
- sample8 state-history lane
- post-integration validation refresh lane
- docs/scripts cleanup lane
- wider sample evidence refresh lane

Current high-value frozen references:
- `post_integration_evidence_refresh`
- `sample5_diagnosis`
- `sample6_missed_window_diagnosis`
- `sample3_extra_window_diagnosis`
- `sample4_diagnosis`
- `sample2_replay_state_edges_diagnosis`
- `wider_sample_evidence_refresh`
