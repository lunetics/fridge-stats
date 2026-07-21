# Conventions

Documentation and code-style rules for this project. Keep new docs and strings consistent
with these.

## Temperatures: always "°C (°F)"

Every **absolute** temperature in the docs and in user-facing strings is written in Celsius
with the Fahrenheit equivalent in parentheses, e.g. `8 °C (46 °F)`. Compute
`°F = °C × 9/5 + 32` and round to the nearest whole degree (one decimal only for sub-degree
source values).

Do **not** convert:

- **rates** (`°C/min`) — a `°F/min` figure is confusing and rarely what a reader wants;
- **temperature differences / deltas** (ΔT, values in K, a sensor resolution like `0.1 °C`) —
  a difference expressed in °F reads as an absolute temperature and is ambiguous.

Leave those in Celsius / Kelvin, as they already are.

## Thresholds are instance-specific unless stated otherwise

The detection thresholds (`rise_rate_min`, `rise_amp_min`, `fall_confirm`) and the calibration
constant τ were **measured on the reference fridge**, not derived from first principles.
Wherever a doc quotes one of these numbers, frame it as a measured/reference value the user
should calibrate — never as a universal constant. τ has `analysis/calibrate_tau.py`; the rate
thresholds have `analysis/calibrate_tau.py --rate-check`.

## Evidence honesty

A claim backed by a single un-instrumented observation, a recollection, or the model's own
output is **not** presented as "ground truth" or "proof". Say what the evidence actually is (a
plausibility check, a self-consistency check, an assumption) and name what would upgrade it to
a real validation (e.g. an auxiliary door sensor giving independent open/close truth).
