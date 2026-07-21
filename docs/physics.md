# Physics and design

Explanation document: why the detector is built the way it is, how the duration model is
derived and calibrated, and what the validation against seven months of real data showed.
Reference facts (thresholds, entities, payloads) live in [reference.md](reference.md).

## The signal

A fridge's interior temperature is a compressor sawtooth: slow warming while the compressor
rests, faster cooling while it runs. In the reference installation the band is roughly
4.3–5.9 °C (40–43 °F) with a ~45-minute period, and the passive warming edge never exceeds
~0.06 °C/min. These figures are measured on one fridge, not universal constants.

A door opening injects room air. The sensed temperature then rises at ≥0.3 °C/min — a 5–12×
rate separation from the compressor edge. This separation, not any absolute threshold, is
the primary detection signal; it stays valid as the baseline drifts with season and setpoint.
The fall of the temperature after the door closes ends the event.

## Duration model

While the door is open, interior air (and the sensor in it) relaxes toward room temperature
as a first-order system:

```
dT/dt = (T_room − T)/τ
⇒  ΔT_peak = (T_room − T₀) · (1 − e^(−t_open/τ))
⇒  t_open  = −τ · ln(1 − ΔT_peak / (T_room − T₀))
```

- `T₀` — interior temperature immediately before the rise (the last pre-rise report).
- `T_room` — the ambient sensor at event start. It is the thermal driving force and the
  reason an ambient input is required: the drive is ~14 K in winter and ~21 K in summer, so
  the same 60-second opening produces a ~30 % larger excursion in summer. Without the
  normalization, seasonal comparisons are systematically wrong.
- `τ` — an effective time constant lumping air-exchange rate, sensor thermal lag, and
  placement. It is a property of one fridge–sensor–shelf combination.

## τ calibration

Every rise segment inside a detected event yields an estimator `τ̂ = (T_room − T̄)/slope`.
The door may be open for only part of a segment, which biases each `τ̂` upward — never
downward. The 10th percentile of per-event minima therefore approaches the true constant
from above. On the reference dataset this yields τ ≈ 1030 s, with the estimator median at
~2500 s; the spread is the honest absolute-scale uncertainty (roughly factor 2). A single
stopwatch-timed opening collapses that uncertainty to about ±20 %
([procedure](installation.md#calibrate-τ)).

The full-open τ (~17 min) and the door-ajar τ (~62 min, see below) measure different
bottlenecks: with the door wide open, air exchanges within seconds and the constant is
sensor-lag- and thermal-mass-limited; through a narrow gap, the buoyancy counterflow itself
is the bottleneck. Applying the full-open inversion to an ajar episode therefore produces
nonsense — which is why `sustained_warmup` events report wall-clock time instead.

## Validation against seven months of data

The detector design was validated offline on January–July recorder/InfluxDB history of the
reference installation (34,000 fridge samples, 11,000 ambient samples, 292 detected events):

- **Independent channel agreement**: 96 % of detected events coincide with a humidity spike
  from the same multisensor (humid room air entering). Humidity plays no role in detection,
  making this a genuinely independent confirmation.
- **Night-time false-positive rate**: 0.7 % of events fall into 02:00–06:00.
- **Plausibility profile**: the hour-of-day histogram peaks at lunch and dinner; nights show
  a pure compressor sawtooth.
- **Threshold sensitivity**: halving or raising the rate/amplitude thresholds by 50 % moves
  the median duration between 48 s and 87 s — the ranking and shape of the distribution are
  stable.

### The door-ajar case

One incident is *qualitatively consistent* with a door left ajar — a plausibility check, not
independent ground truth. The interior climbed monotonically from 6.3 °C to 20.9 °C (43 °F to
70 °F) over 163 minutes and turned to steady decline the minute the door was closed. An
exponential fit gives τ_ajar ≈ 62 min with an asymptote 1.8 K below room temperature — the
compressor was running against the leak (a switched-off fridge equilibrates at room
temperature). Buoyancy counterflow through a vertical slot, `Q = (C_d/3)·w·H·√(g·H·ΔT/T̄)`,
predicts 1.3–4.9 h to reach that temperature for a 2–6 cm crack with realistic contents — the
observed 2.7 h sits inside the band, and the fitted τ back-implies a 4–6 cm gap.

Read this honestly, though: the "2–6 cm crack" is the user's own recollection, given roughly
two months after the fact, with no door sensor, photo, or contemporaneous log — an assumption,
not a measurement. And it is circular — duration, τ_ajar, and the back-implied gap width are
all derived from the *same single temperature curve* the model produces, so the "match" is the
model agreeing with itself inside a wide, memory-based range. What this genuinely demonstrates
is internal self-consistency: the curve's shape (monotonic rise, kink at close, sub-room
asymptote) and its order-of-magnitude agreement with buoyancy physics hold together. It does
**not** validate the regime split against an external reference — that would need an actual
door sensor (the planned aux input).

## Design decisions

- **Rate over absolute threshold**: absolute thresholds break when the baseline drifts
  (season, setpoint, load). The rate criterion survives drift; the critical-temperature
  backstop is the only absolute threshold, and it is deliberately far above the band.
- **Trigger-pair slope instead of derivative/trend helpers**: a state trigger delivers the
  previous and current report including timestamps, giving the segment slope and the exact
  pre-rise T₀ in one step. Derivative/trend helpers add entities, smoothing lag, and (for
  the derivative UI helper) a known source-picker bug, without adding information.
- **Temperature over power monitoring**: a smart-plug-only detector misses the failure mode
  where a broken compressor draws power while cooling nothing; community experience confirms
  temperature-based monitoring as the stronger primary signal.
- **Counting at close, not at open**: all counters and logbook writes happen in the
  close branch, so sub-threshold blips can be discarded without rolling anything back.
- **`queued` automation mode**: the detector is a state machine over an ordered report
  stream; parallel processing of two reports would race the helper state.

## Known limitations

- **Censored minimum**: a short opening produces only a small cumulative rise; below ~15–30 s
  it falls under the detector's own `rise_amp_min` (0.30 °C) blip threshold and is discarded.
  This is a design choice, not a hardware limit — the sensor resolves 0.01 °C, far finer than
  the floor. The floor is a physics estimate, never tested below 30 s; counted openings are a
  lower bound, biased toward longer events, with no independent ground truth (a door sensor) to
  quantify the undercount.
- **Merging**: openings separated by less than the reporting interval merge into one event;
  cooking sessions become episodes.
- **Ambiguity of sustained warm-ups**: a monotone half-hour warming is equally consistent
  with a door ajar, a warm pot inside, or rapid repeated access. Temperature alone cannot
  separate these; an auxiliary door sensor can.
- **Ambient proxy**: the ambient sensor may sit in a different room than the fridge; a
  systematic offset between rooms shifts absolute durations, not comparisons.
