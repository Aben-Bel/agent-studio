# Fab Process & Failure-Mode Reference (sample)

## Etch process — common defect modes
High chamber temperature during etch increases etch rate variability and is a
leading cause of critical-dimension (CD) loss and sidewall roughness. When the
etch_rate_nm_min drifts above the control limit, inspect temperature_c and
gas_flow_sccm first; a high temperature with low gas flow strongly correlates
with over-etch defects.

## Deposition step — particle and uniformity defects
Pressure excursions (pressure_torr) during deposition cause film-thickness
non-uniformity and particle defects. A sudden pressure drop is a known signature
for flaking from chamber walls, which shows up as random-cluster defects on the
wafer map.

## Lithography step — overlay and focus
Voltage instability (voltage_v) on the stage and current spikes (current_ma)
correlate with overlay errors and focus-spot defects during lithography. If
defect_label rises on the Lithography process_step, check voltage_v stability
before blaming the reticle.

## General root-cause guidance
Yield loss is usually multi-parameter. Start by ranking parameters by their
correlation with defect_label, then pull FDC traces for the top driver, then
compare against historical cases with the same defect signature. Document the
confirmed root cause and countermeasure so the case base improves over time.
