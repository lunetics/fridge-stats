# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
