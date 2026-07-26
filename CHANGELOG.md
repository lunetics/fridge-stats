# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.1] - 2026-07-26

Fixes from the retroactive internal review of v0.4.0 (findings internal-1…7; 2 MEDIUM,
5 LOW, no CRITICAL/HIGH).

### Fixed

- Humidity monitor (both variants): **restart guard** — after a Home Assistant restart
  every entity's `last_reported` resets to startup time, so the first report pair after a
  restart could pair a full report interval's humidity rise with a near-zero gap, defeat
  the rate gate and book a phantom short grab (internal-1). Runs are now suppressed until
  the automation has been up longer than `max_report_gap`. The guard computes via
  `as_timestamp()` on purpose: `this` is built from `State.as_dict()`, so
  `this.last_changed` is an ISO string in automation templates — the first-cut direct
  datetime subtraction raised a TemplateError on every evaluation and would have killed
  detection entirely; caught by the fix-loop delta review (delta-breadth-1) before merge
  and verified against Home Assistant core source plus the live template engine.
  **Manual-run hardening** — a UI "Run" / `automation.trigger` no longer errors while
  rendering variables; `from_ok` tolerates a missing state trigger like the sibling
  blueprints do (internal-3).
- Evidence honesty (internal-2): the v0.4.0 validation is now labeled as what it is — a
  `last_changed`-based recorder approximation of the shipped `last_reported` rule, one-sided
  (live sensitivity ≥ backtest; booked counts are lower bounds; the night-zero result was
  measured on the approximation) — in CHANGELOG/README/reference, and the backtest is
  committed as `analysis/backtest_short_grab.py` so the numbers are reproducible.
- `short_grab` class documentation states that the duration/opened-at helpers keep showing
  the last temperature-channel event (internal-4), and the `helper_last_class` input says
  plainly that this blueprint writes it. Acceptance test corrected: the booking appears
  AFTER the claim window elapses, not within it (internal-5). The `mode: single` rationale
  now names the real folding target — follow-on reports that clear the amplitude gate —
  and its deliberate cost (internal-6).
- Package comments no longer carry a `fridge_`-prefixed blueprint-file token, which the
  generator's slug rewrite turned into a non-existent per-appliance blueprint name inside
  generated second-appliance packages (internal-7).

### Added

- docs/conventions.md: git-workflow section — `main` is PR-only (branch protection incl.
  admins); behaviour-carrying PRs get a review pass before merge.

## [0.4.0] - 2026-07-26

### Added

- `blueprints/fridge_humidity_monitor.yaml` (+ `.de` variant): optional companion blueprint
  that books openings BELOW the temperature detection floor (`short_grab` class) from an
  in-fridge humidity sensor. Room air carries far more absolute moisture than the dried
  fridge air, so a stopwatched 5 s grab that produced zero temperature report deltas spiked
  humidity +12 %RH within one report. Detection gates on per-report rate plus single-step
  amplitude (defaults 0.2 %RH/s and 4 %RH; the slowest stopwatched door event measured
  +0.29 %RH/s, the evaporator's moisture cycle ≈ +0.05 %RH/s); a claim window (default
  5 min) hands real, longer openings to the temperature channel — reference claims arrived
  within 71 s. Runs `mode: single` + `max_exceeded: silent` so the aftershock reports of the
  same grab fold into the episode instead of booking again. Fires `fridge_short_grab` with
  rate/amplitude payload, increments its own counter, writes the logbook.
- Package (both language variants): `counter.fridge_short_grabs_total`, mirror
  `sensor.fridge_short_grabs` (`total_increasing`), daily meter `fridge_short_grabs_today`.
  `make_package.py` maps `counter_short_grabs` in the printed blueprint-input mapping and
  validates the new entities like the rest (27 → 30 entities).
- Validation on the reference kitchen (11 days of recorder history, rule backtest incl.
  claim window — a `last_changed`-based approximation of the shipped rule, since recorder
  history carries no `last_reported`; precised in 0.4.1): 4.0 booked grabs/day on top of
  3.3 temperature-detected openings/day — consistent with the documented undercount of
  brief openings — and ZERO bookings between 01:00 and 05:00 (the compressor's humidity
  cycle never triggered). Both stopwatched ground-truth events on the second appliance rank
  as its top-2 per-report rates and are the only threshold passers in 33 h.
- Pressure-confounder check (same 11 days, in-fridge barometer vs a room barometer):
  weather-scale pressure is uncorrelated with in-fridge humidity rates (r ≈ −0.03), so the
  humidity detector needs no pressure compensation. The humidity–pressure co-movement that
  does exist lives entirely in the internal pressure component (fridge minus room, r ≈ +0.6
  on 30 min–12 h differences) and is consistent with vapor-pressure transience in the leaky
  cavity — a co-symptom of the same events, not a false-trigger source.

### Changed

- `deploy.sh` ships the humidity blueprint alongside the other two; docs
  (README/reference/installation) and examples cover the humidity channel.

## [0.3.0] - 2026-07-25

### Added

- `make_package.py`: generates a prefix-parameterised copy of the package for a second
  appliance (`--prefix freezer`, `--lang en|de`). Entity ids in the package arise two
  different ways — helper ids from the YAML object keys, sensor ids from the slugified
  display names (which is why the German variant carries `sensor.kuhlschrank_*`) — so a
  hand-duplicated copy easily leaves dangling references. The generator rewrites all id
  families consistently, enforces that the display name's slug equals the prefix (the
  invariant keeping name-derived sensor ids aligned with rewritten references), and
  validates the output: every internal reference must resolve to an entity the package
  defines, and every defined entity must carry the new prefix. Prints the blueprint-input
  mapping for the new helper set.
- `deploy.sh --prefix <p>`: deploys the generated package as `packages/<p>_stats.yaml`
  alongside the stock fridge package (left untouched); blueprints are shared and refreshed
  either way. The closing hint now names the prefixed τ helper and points to per-appliance
  calibration instead of suggesting the reference fridge's 1028 s for every appliance.

### Changed

- installation.md: the second-appliance section now uses the generator instead of manual
  block duplication, and warns that a freezer's `ajar_warn_temp` must sit far below the
  fridge default. README, reference.md and ideas.md updated accordingly.

## [0.2.0] - 2026-07-25

Two false-reading fixes to the detector's alarm and close rules, plus a diagnostic
plotting toolkit. Both fixes came out of measuring the deployed detector against its own
recorded history; the second was confirmed against a real, user-verified door opening.

### Added

- `ajar_warn_temp` blueprint input (default 8 °C, the EU chilled-food ceiling): the
  door-ajar warning fires only once the interior has actually reached this temperature.
  Rejects the compressor-off-drift phantom — during a compressor pause the passive warming
  ramp crosses `rise_rate_min`, opens the door state, and never registers a close until the
  next cooling cycle, so it sat "open" past `ajar_minutes` and raised a spurious ajar alarm
  even though the interior only drifted up within its normal cycle ceiling (~7–8 °C).
  Measured on the reference fridge: 5 of 8 ajar warnings over a 3-day window were such
  phantoms; the warmth gate removes them while keeping the genuinely-warm openings
  (peaks 13–15 °C).
- `compressor_cycle` event class: a long "open" (≥ `ajar_minutes`) whose peak never crossed
  `ajar_warn_temp` is discarded on close with a logbook note instead of being counted, so
  phantom episodes no longer inflate the opening statistics.
- `fall_from_peak` blueprint input (default 0.4 °C) and the `helper_peak` state helper
  (`input_number.fridge_peak`, new in the package): the event closes only once the interior
  has fallen a confirmed distance below the **highest temperature reached during the
  opening**, instead of on the first report dipping `fall_confirm` (0.05 °C) below its
  predecessor. A peak-tracking branch runs ahead of the close branch, so a rising report
  updates the peak rather than being read as a close candidate. Set `fall_from_peak: 0` for
  the previous behaviour.
- `analysis/plot_diagnostics.py`: read-only diagnostic plots for any installation — interior
  temperature with detected openings shaded by class, the compressor sawtooth "equalized"
  against a rolling ceiling, a compressor-cycle phantom zoom, and a rolling-ceiling detector
  view. Re-simulates the detector from the temperature series (blueprint rules), so it needs
  no live helpers; REST history or `--from-csv`.
- `analysis/make_demo_data.py`: deterministic synthetic fridge series (no real data)
  reproducing the sawtooth, grabs, a long opening, compressor-cycle phantoms and a blip — a
  way to try `plot_diagnostics.py` without a live instance.
- Documentation figures (`docs/img/`, rendered from the reference installation) embedded in
  the README and physics.md; an installation section on reading `ajar_warn_temp` /
  `rise_rate_min` off the plots.
- `docs/ideas.md`: the adaptive rolling-ceiling gate recorded as an investigated dead end —
  evaluated at the decision moment it *suppressed* the warning for the longest real opening
  (52 min, 15 °C), because the trailing estimate is contaminated by the ongoing and recent
  openings; the fixed threshold fired on every real opening in the same test. Also records
  that the aux door sensor's highest-value use is validation: every shipped threshold was
  tuned against labels the detector itself produced, so the true false-positive, miss and
  short-opening-floor rates stay unmeasured until an external reference is logged alongside.

### Changed

- The ajar warning is gated on interior temperature, not door-state duration alone. A door
  "open" long enough but still cold logs a suppression note instead of alarming; the
  `critical_temp` backstop still covers a real door left open, since a genuinely open door
  climbs past the threshold within minutes.
- Duration is computed from the tracked peak rather than from the report that closed the
  event, so it no longer depends on which report happened to trigger the close.
- The opening counter and accumulated open time now exclude compressor-cycle phantoms.
  Existing totals are left as booked, so expect a visible discontinuity — see upgrade notes.
- installation.md troubleshooting: the false door-ajar / over-long-opening row leads with
  `ajar_warn_temp` as the primary fix, with `rise_rate_min` as the complementary
  "don't book it at all" remedy.

### Fixed

- One long warm period was chopped into several short "openings". While the door is open the
  interior sits on a plateau near room temperature, where a single noisy report 0.05 °C below
  its predecessor satisfied the old close rule — so a cooking session was booked as a chain
  of fragments, each with an understated duration. Measured on the reference fridge over
  10 days: 7 of 23 booked closes carried the signature (temperature still rising afterwards
  and/or a re-open within ~1 min); one dinner cluster was split into 5 fragments
  (3/3/3/7/29 min) that the confirmed-fall rule merges into the single 59-minute period it
  was. Verified against a user-confirmed real closing: the event closes 2.7 min later than
  before (waiting for genuine cooling), still classified and alarmed correctly.
- Knock-on of the above: because fragments no longer hide below the `ajar_minutes` mark, the
  `compressor_cycle` rule now catches them — 10 episodes that were counted as openings while
  peaking at only 5.0–7.5 °C (pure compressor sawtooth) are correctly discarded.
- `make_demo_data.py`: the post-opening recovery multiplied one term by zero (reducing the
  line to scaling the sawtooth toward 0 °C despite a "keep sawtooth" comment) and its window
  was shorter than a few of its own time constants, so it was truncated while still well
  above the sawtooth. Both produced abrupt steps up to 1.94 °C in the generated series; a
  shared `ease_back()` crossfade brings the largest step down to 0.49 °C, which is an
  intentionally scripted event.

### Upgrade notes

- **A Home Assistant restart is required**, not just a blueprint re-import: the package adds
  `input_number.fridge_peak`, and packages load at startup. Without it the close rule falls
  back on its `99` guard and the event will not close.
- Both new inputs ship defaults, so existing automations upgrade without edits — but the
  behaviour changes deliberately: long-but-cold "openings" no longer alarm and no longer
  count. The opening counter will grow more slowly than before; that is the correction, not
  a regression.
- The 8 °C `ajar_warn_temp` default suits a fridge cycling to ~7 °C. Set it just above your
  own compressor-cycle ceiling — `analysis/plot_diagnostics.py` shows where that sits.

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
