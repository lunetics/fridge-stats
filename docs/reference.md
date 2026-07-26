# Reference

Facts about every configurable input, entity, event, and classification the project ships.
For the reasoning behind the numbers, see [physics.md](physics.md).

## Blueprint inputs

File: `blueprints/fridge_door_monitor.yaml`, domain `automation`, minimum Home Assistant
version 2026.6.

### Sensors

| Input | Required | Selector | Purpose |
|---|---|---|---|
| `fridge_temp_sensor` | yes | entity: sensor, temperature | Temperature inside the fridge |
| `ambient_temp_sensor` | yes | entity: sensor, temperature | Room-temperature reference (thermal driving force) |
| `aux_open_sensor` | no | entity: binary_sensor | Motion/vibration/contact sensor on the door; logged for future sensor fusion |

### State helpers

All default to the entities the package creates; point them at a second helper set to monitor
another appliance.

| Input | Default |
|---|---|
| `helper_door_open` | `input_boolean.fridge_door_open` |
| `helper_t0` | `input_number.fridge_t0` |
| `helper_troom0` | `input_number.fridge_troom0` |
| `helper_peak` | `input_number.fridge_peak` |
| `helper_tau` | `input_number.fridge_tau` |
| `helper_opened_at` | `input_datetime.fridge_opened_at` |
| `helper_last_duration` | `input_number.fridge_last_open_duration` |
| `helper_last_class` | `input_text.fridge_last_event_class` |
| `counter_openings` | `counter.fridge_openings_total` |
| `helper_open_seconds_total` | `input_number.fridge_open_seconds_total` |

### Thresholds

| Input | Default | Meaning |
|---|---|---|
| `rise_rate_min` | 0.10 °C/min | Minimum single-segment rise rate to consider a door opening |
| `rise_amp_min` | 0.30 °C | Minimum total excursion; smaller rises are discarded as `blip` |
| `fall_confirm` | 0.05 °C | Minimum drop below the previous report for a close candidate — a cheap first filter |
| `fall_from_peak` | 0.4 °C | The decisive close test: the event closes only once the interior has fallen this far below the highest temperature reached during the opening (real cooling, not a transient dip). `0` restores the previous report-to-report behaviour |
| `ajar_minutes` | 15 min | Door-open time before the ajar warning fires |
| `ajar_warn_temp` | 8 °C (46 °F) | The ajar warning fires only once the interior actually reaches this; a long "open" whose peak never crosses it is discarded as `compressor_cycle` (not counted) — rejects a compressor-off warming ramp misread as a door left ajar. Set just above your fridge's normal compressor-cycle ceiling; the default is the EU chilled-food ceiling and sits below `critical_temp` |
| `critical_temp` | 10 °C (50 °F) | Interior temperature that, sustained 30 min, fires the critical alarm — above the 8 °C (46 °F) EU chilled-food ceiling with a grace window, so routine restocking transients do not trip it |
| `stale_hours` | 6 h | Closes arriving later than this after the opening are discarded (`stale_reset`) — self-heal after pausing the automation mid-event |

> The rate/amplitude defaults (`rise_rate_min`, `rise_amp_min`, `fall_confirm`) were
> **measured on the reference fridge**, not derived from first principles — a fridge with a
> faster compressor or a slower-reporting sensor needs different values. Compute your own with
> `analysis/calibrate_tau.py --rate-check` (see
> [installation.md](installation.md#calibrate-detection-thresholds)).

### Alarm actions

| Input | Default | Runs when |
|---|---|---|
| `warn_actions` | none | Door considered open/ajar for `ajar_minutes` |
| `critical_actions` | none | Interior above `critical_temp` for 30 minutes |

## Entities (package)

File: `package/fridge_stats.yaml` (English, canonical). The German variant
`package/fridge_stats.de.yaml` is identical logic but names its mirror/statistics/utility-meter
sensors in German — producing `sensor.kuhlschrank_*` entity ids instead of the `sensor.fridge_*`
ids below; the `input_*`/`counter` helper ids are the same in both. For a second appliance,
`make_package.py --prefix <p>` generates a validated copy with every id family under the new
prefix (see [installation.md](installation.md#monitor-a-second-appliance-freezer)); the tables
below list the stock `fridge_` ids. State helpers store the
detector's working state; mirror sensors expose it with `state_class` so the recorder keeps
long-term statistics.

| Entity | Type | Role |
|---|---|---|
| `input_boolean.fridge_door_open` | helper | Inferred door state; carries the logbook history |
| `input_number.fridge_t0` | helper | Interior temperature before the current opening |
| `input_number.fridge_troom0` | helper | Room temperature at opening |
| `input_number.fridge_peak` | helper | Highest interior temperature reached during the current opening (drives the confirmed-fall close) |
| `input_number.fridge_tau` | helper | Calibration constant τ in seconds |
| `input_datetime.fridge_opened_at` | helper | Opening timestamp (last pre-rise report) |
| `input_number.fridge_last_open_duration` | helper | Last estimated opening duration in seconds |
| `input_text.fridge_last_event_class` | helper | Last event class |
| `counter.fridge_openings_total` | helper | Openings since installation |
| `counter.fridge_short_grabs_total` | helper | Sub-floor openings booked by the optional humidity monitor; stays at 0 without it |
| `input_number.fridge_open_seconds_total` | helper | Accumulated open seconds |
| `sensor.fridge_door_last_opening_duration` | template mirror | Last duration, `measurement` — event-gated: available only for ~1 h after an opening, so its long-term statistics contain event hours only |
| `sensor.fridge_door_openings_total` | template mirror | Opening count, `total_increasing` |
| `sensor.fridge_door_open_time_total` | template mirror | Open seconds, `total_increasing` |
| `sensor.fridge_short_grabs` | template mirror | Short-grab count, `total_increasing` |
| `sensor.fridge_door_state` | template | `open`/`closed` plus last class, duration, timestamp as attributes |
| `sensor.fridge_opening_duration_median_7d` | statistics | Median opening duration over 7 days |
| `sensor.fridge_opening_duration_max_7d` | statistics | Maximum opening duration over 7 days |
| `sensor.fridge_openings_today` / `_week` / `_month` | utility_meter | Opening counts per day/week/month |
| `sensor.fridge_open_time_today` / `_month` | utility_meter | Open time per day/month |
| `sensor.fridge_short_grabs_today` | utility_meter | Short grabs per day |
| `sensor.fridge_open_time_today_readable` / `_month_readable` / `_total_readable` | template display | Human-readable duration strings ("42 s" / "26 min" / "9.9 h") for dashboard rows |
| `sensor.fridge_last_opening_duration_readable` | template display | Last duration, human-readable |
| `sensor.fridge_opening_duration_median_7d_readable` / `_max_7d_readable` | template display | 7-day median/max, human-readable |

## Events

All events fire on the Home Assistant event bus; consume them with
`trigger: event` / `event_type: <name>`.

| Event | Fires when | Payload |
|---|---|---|
| `fridge_door_opened` | A qualifying temperature rise starts | `t0`, `t_room`, `opened_at`, `source` |
| `fridge_door_closed` | Temperature falls again after an opening | `duration_s`, `class`, `dt_peak`, `t0`, `peak`, `t_room`, `wall_clock_s`, `source` |
| `fridge_door_ajar` | Door state on for `ajar_minutes` **and** interior at/above `ajar_warn_temp` | `opened_at`, `current_temp` |
| `fridge_temp_critical` | Interior above `critical_temp` for 30 min | `current_temp` |
| `fridge_aux_trigger` | Auxiliary sensor turns on | `entity_id`, `at` |
| `fridge_short_grab` | The optional humidity monitor books a sub-floor opening ([below](#humidity-grab-monitor)) | `entity_id`, `d_rh`, `window_s`, `rate_rh_s`, `humidity`, `source` |

## Event classes

Assigned when an event closes; stored in `helper_last_class` and the
`fridge_door_closed` payload.

| Class | Definition | Duration source |
|---|---|---|
| `quick_grab` | Estimated duration < 40 s | τ model |
| `normal_grab` | 40–90 s | τ model |
| `extended_open` | > 90 s | τ model |
| `sustained_warmup` | Wall-clock open ≥ `ajar_minutes` (default 15 min) or ΔT ≥ 2.5 °C — door ajar, warm food inserted, or rapid repeated access | Wall clock (the τ model does not apply to this regime) |
| `blip` | Total rise below `rise_amp_min` | Discarded; not counted or logged |
| `compressor_cycle` | A long "open" (≥ `ajar_minutes`) whose peak stayed below `ajar_warn_temp` — a passive compressor-off warming ramp misread as an opening, not a real door event | Discarded; logbook note, not counted |
| `stale_reset` | Close arrived more than `stale_hours` after the recorded opening (automation paused mid-event, sensor removed) | Discarded; state reset, logbook note, not counted |
| `short_grab` | Booked by the optional humidity monitor: a humidity-rate spike with the door state off that the temperature channel did not claim within the claim window — an opening below the temperature detection floor | None — the temperature never moved, so the τ inversion has nothing to invert; counted in its own counter. Note: the duration/opened-at helpers are NOT touched, so `sensor.fridge_door_state` still shows the LAST temperature-channel event's `last_duration_s`/`opened_at` beside `last_class: short_grab` |

## Detection state machine

The blueprint runs in `queued` mode so sensor reports are processed strictly in order.

1. **Open**: a report arrives while the door state is off, and the rise from the previous
   report is ≥ 0.15 °C at ≥ `rise_rate_min`. The previous report supplies T₀ and the opening
   timestamp; the room temperature is snapshotted.
2. **Peak tracking**: while the door state is on, every report above the stored peak updates
   `helper_peak`. This branch precedes the close branch, so a rising report can never be read
   as a close candidate.
3. **Close**: a report arrives while the door state is on, lies ≥ `fall_confirm` below the
   previous one **and** ≥ `fall_from_peak` below the tracked peak — confirmed cooling rather
   than a transient dip. Duration and class are computed from the tracked peak, counters and
   logbook are updated, `fridge_door_closed` fires. A total rise below `rise_amp_min` ends the
   open state silently (`blip`).
4. **Ajar**: the door state stays on for `ajar_minutes` **and** the interior has reached
   `ajar_warn_temp` → `fridge_door_ajar` + warn actions. If it never warmed that far, the
   warning is suppressed (a compressor-off drift, not an open door) and the episode is
   discarded on close as `compressor_cycle`.
5. **Critical backstop**: independent of door state, interior above `critical_temp` for
   30 minutes → `fridge_temp_critical` + critical actions. Restart-safe because the
   `numeric_state` condition re-arms after a restart while the temperature stays high.

All temperature branches guard both trigger states against `unknown` and `unavailable`, so
sensor dropouts and restarts do not produce false events.

## Sensor-silence watchdog

A separate companion blueprint, `blueprints/fridge_sensor_watchdog.yaml`, alerts when a
monitored sensor stops reporting — a fridge sensor whose battery dies in the cold otherwise
fails invisibly, since its last value lingers and the door detector simply sees no more
events. It checks `last_reported` (not `last_changed`), so a steady value never false-alarms.
It is self-contained: it needs none of the package helpers.

### Watchdog inputs

| Input | Required | Default | Purpose |
|---|---|---|---|
| `monitored_sensor` | yes | — | The entity to watch (any domain; typically the fridge sensor) |
| `silence_hours` | no | 3 | Alert after this many hours with no report |
| `alarm_actions` | no | none | Runs once when the sensor crosses the silence threshold |
| `recovery_actions` | no | none | Runs when the sensor reports again after a gap past the threshold |

### Watchdog events

| Event | Fires when | Payload |
|---|---|---|
| `fridge_sensor_silent` | No report for `silence_hours` | `entity_id`, `silent_hours`, `last_reported` |
| `fridge_sensor_recovered` | A report arrives after a gap past the threshold | `entity_id`, `gap_hours` |

Detection is on the alive→silent transition. A still-silent sensor re-alerts ~`silence_hours`
after each Home Assistant restart (every entity's `last_reported` resets at startup); the one
uncovered case — reloading the automation while the sensor is already past the threshold —
self-heals on the next restart.

## Humidity grab monitor

An optional companion blueprint, `blueprints/fridge_humidity_monitor.yaml`, books openings
BELOW the temperature detection floor ("short grabs") from a humidity sensor inside the
fridge. Room air carries far more absolute moisture than the dried fridge air, so even a
stopwatched 5 s grab that left zero trace on the temperature channel spiked relative humidity
by +12 %RH within a single report. The evaporator's own moisture cycle moves humidity almost
as far but far slower, so detection gates on rate plus single-report amplitude. If the door
state turns on during the claim window, the temperature channel owns the event and the
monitor stays silent — it counts only sub-floor grabs, without a duration estimate.

### Humidity monitor inputs

| Input | Required | Default | Purpose |
|---|---|---|---|
| `humidity_sensor` | yes | — | Humidity sensor inside the fridge |
| `helper_door_open` | no | `input_boolean.fridge_door_open` | Door state; read-only here (grab gate + claim detection) |
| `helper_last_class` | no | `input_text.fridge_last_event_class` | Receives `short_grab` on booking |
| `counter_short_grabs` | no | `counter.fridge_short_grabs_total` | Incremented per booked grab |
| `grab_rate_min` | no | 0.2 %RH/s | Minimum rise rate between two reports (reference: slowest stopwatched door event +0.29, evaporator cycle ≈ +0.05) |
| `grab_amp_min` | no | 4 %RH | Minimum single-step rise; smaller steps are noise/drift |
| `max_report_gap` | no | 180 s | Rises spread over longer report gaps have no meaningful rate and are skipped |
| `claim_wait_minutes` | no | 5 min | Wait for the temperature channel to claim before booking (reference claims arrived within 71 s) |

Behaviour notes: the blueprint runs `mode: single` with `max_exceeded: silent` on purpose —
follow-on reports of the same grab that clear the amplitude gate on their own arrive during
the claim window and must fold into that episode instead of booking again (the deliberate
cost: genuine repeat grabs within the window collapse into one booking). A second real
opening inside the claim window suppresses the pending grab (it books as a regular opening;
only the preceding grab goes uncounted), and a Home Assistant restart during the claim
window drops the pending grab. A restart guard additionally suppresses runs during the
first `max_report_gap` seconds after startup/reload — after a restart every entity's
`last_reported` resets, and the first report pair could otherwise fake a door-grade rate.
Validation on the reference kitchen (11 days of recorder history — a `last_changed`-based
approximation of the shipped rule, see the caveat below): 4.0 booked grabs/day on top of
3.3 temperature-detected openings/day, zero bookings between 01:00 and 05:00 — the
compressor's humidity cycle never triggered. Caveat: recorder history carries no
`last_reported`, so the backtest measured state-CHANGE gaps; the live rule's
`last_reported` gaps are ≤ those, making live sensitivity ≥ the backtest's — the daily
count is a lower bound, and the night-zero result was measured on the approximation, not
the shipped rule (`analysis/backtest_short_grab.py` reproduces it). Barometric pressure is not a confounder: room-barometer
changes showed zero correlation with in-fridge humidity rates (r ≈ −0.03 over the same
11 days); the in-fridge humidity–pressure co-movement that does exist is internal
vapor-pressure transience, a co-symptom of the same events.

## Access guarantee

The project is strictly read-only toward everything it does not own:

- **Reads (never writes):** the configured fridge, ambient, and auxiliary sensors.
- **Writes only its own entities:** the `fridge_*` helper set and the package's mirror,
  statistics, and utility-meter sensors. Logbook entries attach exclusively to the project's
  own door-state entity.
- **Events** are fired under the project's own `fridge_*` event types.
- The only actions that reach anything else are those the **user injects** through the
  `warn_actions` / `critical_actions` inputs — empty by default.
