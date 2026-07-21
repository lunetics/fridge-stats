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
| `fall_confirm` | 0.05 °C | A report this far below the previous one closes the event |
| `ajar_minutes` | 15 min | Door-open time before the ajar warning fires |
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

File: `package/fridge_stats.yaml`. State helpers store the detector's working state; mirror
sensors expose it with `state_class` so the recorder keeps long-term statistics.

| Entity | Type | Role |
|---|---|---|
| `input_boolean.fridge_door_open` | helper | Inferred door state; carries the logbook history |
| `input_number.fridge_t0` | helper | Interior temperature before the current opening |
| `input_number.fridge_troom0` | helper | Room temperature at opening |
| `input_number.fridge_tau` | helper | Calibration constant τ in seconds |
| `input_datetime.fridge_opened_at` | helper | Opening timestamp (last pre-rise report) |
| `input_number.fridge_last_open_duration` | helper | Last estimated opening duration in seconds |
| `input_text.fridge_last_event_class` | helper | Last event class |
| `counter.fridge_openings_total` | helper | Openings since installation |
| `input_number.fridge_open_seconds_total` | helper | Accumulated open seconds |
| `sensor.kuhlschrank_tur_letzte_offnungsdauer` | template mirror | Last duration, `measurement` — event-gated: available only for ~1 h after an opening, so its long-term statistics contain event hours only |
| `sensor.kuhlschrank_tur_offnungen_gesamt` | template mirror | Opening count, `total_increasing` |
| `sensor.kuhlschrank_tur_offnungszeit_gesamt` | template mirror | Open seconds, `total_increasing` |
| `sensor.kuhlschrank_turstatus` | template | `offen`/`geschlossen` plus last class, duration, timestamp as attributes |
| `sensor.kuhlschrank_offnungsdauer_median_7d` | statistics | Median opening duration over 7 days |
| `sensor.kuhlschrank_offnungsdauer_max_7d` | statistics | Maximum opening duration over 7 days |
| `sensor.kuhlschrank_offnungen_heute` / `_woche` / `_monat` | utility_meter | Opening counts per day/week/month |
| `sensor.kuhlschrank_offnungszeit_heute` / `_monat` | utility_meter | Open time per day/month |
| `sensor.kuhlschrank_offnungszeit_heute_lesbar` / `_monat_lesbar` / `_gesamt_lesbar` | template display | Human-readable duration strings ("42 s" / "26 min" / "9,9 h") for dashboard rows |
| `sensor.kuhlschrank_letzte_offnungsdauer_lesbar` | template display | Last duration, human-readable |
| `sensor.kuhlschrank_offnungsdauer_median_7d_lesbar` / `_max_7d_lesbar` | template display | 7-day median/max, human-readable |

## Events

All events fire on the Home Assistant event bus; consume them with
`trigger: event` / `event_type: <name>`.

| Event | Fires when | Payload |
|---|---|---|
| `fridge_door_opened` | A qualifying temperature rise starts | `t0`, `t_room`, `opened_at`, `source` |
| `fridge_door_closed` | Temperature falls again after an opening | `duration_s`, `class`, `dt_peak`, `t0`, `peak`, `t_room`, `wall_clock_s`, `source` |
| `fridge_door_ajar` | Door state on for `ajar_minutes` | `opened_at`, `current_temp` |
| `fridge_temp_critical` | Interior above `critical_temp` for 30 min | `current_temp` |
| `fridge_aux_trigger` | Auxiliary sensor turns on | `entity_id`, `at` |

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
| `stale_reset` | Close arrived more than `stale_hours` after the recorded opening (automation paused mid-event, sensor removed) | Discarded; state reset, logbook note, not counted |

## Detection state machine

The blueprint runs in `queued` mode so sensor reports are processed strictly in order.

1. **Open**: a report arrives while the door state is off, and the rise from the previous
   report is ≥ 0.15 °C at ≥ `rise_rate_min`. The previous report supplies T₀ and the opening
   timestamp; the room temperature is snapshotted.
2. **Close**: a report arrives while the door state is on and lies ≥ `fall_confirm` below the
   previous one. The previous report is the peak. Duration and class are computed, counters
   and logbook are updated, `fridge_door_closed` fires. A total rise below `rise_amp_min`
   ends the open state silently (`blip`).
3. **Ajar**: the door state stays on for `ajar_minutes` → `fridge_door_ajar` + warn actions.
4. **Critical backstop**: independent of door state, interior above `critical_temp` for
   30 minutes → `fridge_temp_critical` + critical actions. Restart-safe because the
   `numeric_state` condition re-arms after a restart while the temperature stays high.

All temperature branches guard both trigger states against `unknown` and `unavailable`, so
sensor dropouts and restarts do not produce false events.

## Access guarantee

The project is strictly read-only toward everything it does not own:

- **Reads (never writes):** the configured fridge, ambient, and auxiliary sensors.
- **Writes only its own entities:** the `fridge_*` helper set and the package's mirror,
  statistics, and utility-meter sensors. Logbook entries attach exclusively to the project's
  own door-state entity.
- **Events** are fired under the project's own `fridge_*` event types.
- The only actions that reach anything else are those the **user injects** through the
  `warn_actions` / `critical_actions` inputs — empty by default.
