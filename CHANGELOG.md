# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
