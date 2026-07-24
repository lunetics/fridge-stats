# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.4] - 2026-07-24

### Added

- `analysis/plot_diagnostics.py`: read-only diagnostic plots for any installation — interior
  temperature with detected openings shaded by class, the compressor sawtooth "equalized" against
  a rolling ceiling, a compressor-cycle phantom zoom, and an adaptive rolling-ceiling detector
  view. Re-simulates the detector from the temperature series (blueprint rules), so it needs no
  live helpers; REST history or `--from-csv`.
- `analysis/make_demo_data.py`: deterministic synthetic fridge series (no real data) that
  reproduces the sawtooth, grabs, a long opening, compressor-cycle phantoms, and a blip — a way
  to try `plot_diagnostics.py` without a live instance.
- Documentation figures (`docs/img/`, rendered from the reference installation) embedded in the
  README and physics.md; an installation section on reading `ajar_warn_temp` / `rise_rate_min`
  off the plots.
- `docs/ideas.md`: adaptive rolling-ceiling detector as a v2 candidate (self-tuning alternative
  to the fixed `ajar_warn_temp`), with the causal back-test result.

### Changed

- installation.md troubleshooting: the false door-ajar / over-long-opening row now leads with
  `ajar_warn_temp` as the primary fix (introduced in 0.1.3), with `rise_rate_min` as the
  complementary "don't book it at all" remedy.

## [0.1.3] - 2026-07-24

### Added

- `ajar_warn_temp` blueprint input (default 8 °C, the EU chilled-food ceiling): the
  door-ajar warning now fires only once the interior has actually reached this
  temperature. Rejects the compressor-off-drift phantom — during a compressor pause the
  passive warming ramp crosses `rise_rate_min`, opens the door state, and never registers
  a close until the next cooling cycle, so it sat "open" past `ajar_minutes` and raised a
  spurious ajar alarm even though the interior only drifted up within its normal cycle
  ceiling (~7–8 °C). Measured on the reference fridge: 5 of 8 ajar warnings over a 3-day
  window were such phantoms; the warmth gate removes them while keeping the
  genuinely-warm openings (peaks 13–15 °C).
- `compressor_cycle` event class: a long "open" (≥ `ajar_minutes`) whose peak never
  crossed `ajar_warn_temp` is discarded on close with a logbook note instead of being
  counted, so phantom episodes no longer inflate the opening statistics.

### Changed

- The ajar warning is gated on interior temperature, not door-state duration alone. A
  door "open" long enough but still cold (below `ajar_warn_temp`) logs a suppression note
  instead of alarming; the `critical_temp` backstop still covers a real door left open,
  since a genuinely open door climbs past the threshold within minutes.

## [0.1.2] - 2026-07-21

### Changed

- Troubleshooting docs: added the false door-ajar / over-long-opening symptom — a
  compressor-off warming ramp misread as an opening that never registers a close until
  the next cooling cycle — with the `calibrate_tau.py --rate-check` + `rise_rate_min`
  remedy, and extended the sensor-reposition note to cover `rise_rate_min` recalibration
  in addition to τ.

## [0.1.1] - 2026-07-21

### Added

- Sensor-silence watchdog blueprint (`fridge_sensor_watchdog`): alerts when the
  monitored sensor stops reporting (dead battery, dropped link) and, optionally, again
  on recovery. Uses `last_reported`, so a steady-but-healthy sensor never false-alarms.
- `calibrate_tau.py --rate-check`: recommends `rise_rate_min` from the measured
  separation between compressor and door-opening rise rates (always read-only).
- English (canonical) and German (`.de.yaml`) variants of both blueprints and the
  package; `deploy.sh --lang en|de` selects the entity-id set to deploy.
- `docs/conventions.md`: °C-first temperature notation convention.
- My Home Assistant one-click blueprint import badge in the README.

### Changed

- Recalibrated default alarm thresholds: door-ajar warning 20 → 15 min, critical
  over-temperature 11 → 10 °C held 10 → 30 min; `sustained_warmup` classification
  coupled to the `ajar_minutes` input instead of a hard-coded 25 min.
- Honest documentation: reference-fridge rise rates are labelled measured values, not
  physical constants, with calibration pointers; the ambient sensor is documented as a
  required input.
- Examples use a placeholder fridge sensor id instead of the author's real entity.

### Fixed

- Watchdog: guard the trigger/action race so a sensor that reports in the gap between
  the silence trigger and the queued action no longer raises a false alarm.
- Backfill `--seed`: the seeded last-event class now applies both legs of the live
  `sustained_warmup` test (wall-clock ≥ `ajar_minutes` **or** peak rise ≥ 2.5 °C) and
  follows the deployed package's entity-id language variant.
- `calibrate_tau.py --rate-check`: isolated door rises that never resolve to a full
  burst are kept out of the compressor population, so they can no longer inflate the
  compressor ceiling and push the recommended `rise_rate_min` above real door rates.

## [0.1.0] - 2026-07-21

### Added

- `fridge_door_monitor` automation blueprint: temperature-physics door detection with
  configurable sensors and thresholds, five bus events, event classification, logbook
  history, door-ajar warning, critical over-temperature backstop, and an auxiliary-sensor
  input reserved for sensor fusion.
- `fridge_stats` package: state helpers, mirror sensors with long-term statistics, 7-day
  median/max statistics sensors, daily/weekly/monthly utility meters.
- Offline analysis toolkit (`analysis/`): historical burst detection, episode
  classification, τ self-calibration, and the 2026 event dataset of the reference
  installation.
- Portable τ calibration script (`analysis/calibrate_tau.py`): estimates the time constant
  from any instance's recorder history via the REST API; dry-run by default, `--apply`
  writes the tau helper.
- Statistics backfill script (`analysis/backfill_statistics.py`): reconstructs pre-install
  door statistics from Home Assistant's own data (recorder raw history + hourly long-term
  statistics of the fridge sensor) and imports them via `recorder/import_statistics`;
  optional helper seeding and utility-meter calibration. The LTS branch is a documented
  lower bound (at most one detectable opening per hour).
- Event-gated duration mirror sensor: available only for one hour after an opening, so
  long-term statistics average event durations instead of a permanently held last value.
- Human-readable duration display sensors ("42 s" / "26 min" / "9,9 h") for compact
  dashboard rows; raw second-valued sensors remain for statistics and automations.
- Stale-state guard (`stale_hours` blueprint input, default 6 h): a closing report arriving
  later than this after the recorded opening is discarded as `stale_reset` instead of
  booking an absurd duration — the state machine self-heals after being paused mid-event.
- Backfill `--seed` also sets the last-event class and duration helpers from the newest
  reconstructed event.
- Example dashboard views (`examples/dashboard-views.yaml`, German + English): temperature
  plot with door markers, status and statistics rows, daily/weekly statistics graphs.
- Deploy script for a Samba-mounted Home Assistant config directory.
- Documentation: reference, installation how-to, physics/design explanation, research-backed
  roadmap notes.
