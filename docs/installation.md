# Installation

## Prerequisites

Check [README → Requirements](../README.md#requirements) first. The critical property is the
in-fridge sensor's reporting behavior: the detector works from consecutive report pairs, so a
sensor that reports only on large changes or at fixed hourly intervals cannot resolve door
events. Aqara-class Zigbee multisensors (0.01 °C resolution, event-driven reports every 1–10
minutes) work.

## Sensor placement

- **Middle shelf, front, facing the door.** Incoming warm air reaches the sensor first
  (fastest detection) and the Zigbee signal crosses the least metal. Avoid the back wall
  (evaporator airflow distorts readings, worst reception) and do not bury the sensor behind
  food — it measures air.
- Optional condensation protection: a small zip-lock bag (community practice). It slightly
  slows the response — recalibrate τ afterwards.
- Check `linkquality` after installation; metal housings attenuate Zigbee. Add a repeater
  near the kitchen if reception is poor.
- Battery percentages read low in the cold and are unreliable — sensors report "empty" for
  months while working. Detect failure by report silence (>3 h), not by battery level.
- **Pause the automation before handling the sensor** (the automation entity is the master
  switch): removing the sensor looks exactly like an open door to the detector. Raw
  temperature recording continues while paused; missed events can be reconstructed with the
  backfill script. A pause mid-event self-heals via the `stale_hours` guard.
- **Placement defines τ.** Recalibrate after any reposition.

## Where sensors are configured

Three places take sensor entities — only the first one affects detection:

| Place | Role |
|---|---|
| **Blueprint automation inputs** | The actual wiring: detection, duration math, alarms |
| Script arguments (`--fridge-entity` / `--ambient-entity`) | Calibration and backfill runs |
| Dashboard cards | Display only — changing entities here changes nothing else |

## Steps

1. Copy the package:

   ```
   package/fridge_stats.yaml  →  <config>/packages/fridge_stats.yaml
   ```

2. Copy the blueprint:

   ```
   blueprints/fridge_door_monitor.yaml  →  <config>/blueprints/automation/fridge_stats/fridge_door_monitor.yaml
   ```

3. Enable packages in `configuration.yaml` if not already present:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

4. Run a configuration check, then restart Home Assistant.

5. Create the automation: Settings → Automations & Scenes → Create Automation →
   **Fridge Door Monitor (temperature-physics based)**. Select your fridge and ambient
   temperature sensors. Leave the state-helper inputs at their defaults (they point at the
   package's entities). Configure `warn_actions` and `critical_actions` with your
   notification services.

6. Seed τ: set `input_number.fridge_tau` to `1028` as a starting value, then calibrate
   (below).

7. Acceptance test: open the fridge door for 30–60 seconds. Within a few minutes the logbook
   of `input_boolean.fridge_door_open` shows an opening and a closing entry with an estimated
   duration.

## Calibrate τ

τ is the effective time constant of your fridge–sensor combination (air exchange, sensor lag,
placement). Calibration does not run automatically — pick one of these methods:

- **History self-calibration (recommended)**: `analysis/calibrate_tau.py` works against any
  Home Assistant instance's recorder history via the REST API — no InfluxDB, no extra
  dependencies. The default ~10-day retention yields enough events in a normally used fridge:

  ```bash
  export HASS_TOKEN=<long-lived access token>
  python3 analysis/calibrate_tau.py --url http://homeassistant.local:8123 \
      --fridge-entity sensor.your_fridge_temperature \
      --ambient-entity sensor.your_living_room_temperature
  # dry run prints the recommendation; add --apply to write input_number.fridge_tau
  ```

  Cross-check on the reference installation: 10 days of recorder history (25 events)
  recommend 1051 s vs. 1028 s from seven months of full-resolution data — within 2 %.
- **Timed opening**: open the door for a stopwatch-measured 60 s, wait for the
  `fridge_door_closed` event, and scale: `τ_new = τ_old × 60 / duration_s`. One timed opening
  pins the absolute scale to roughly ±20 %.
Re-run the history calibration after moving the sensor or changing the fridge's contents
layout substantially. Continuous automatic recalibration is planned together with the
auxiliary door sensor (per-event wall-clock ground truth).

## Calibrate detection thresholds

The rate/amplitude thresholds (`rise_rate_min`, `rise_amp_min`, `fall_confirm`) were **measured
on the reference fridge**, not derived from first principles. A fridge with a faster compressor
edge, a different air volume, or a slower-reporting sensor separates door events from the
compressor cycle at a different rate — the shipped `rise_rate_min` of 0.10 °C/min is a starting
point, not a physical constant.

`analysis/calibrate_tau.py --rate-check` reads the same recorder history as the τ calibration
and reports, for your fridge:

- the **compressor ceiling** — a high percentile of your passive (compressor-cycle) rise rates;
- the **door-event rate** — the rise rates of the detected opening bursts;
- a **recommended `rise_rate_min`** sitting between the two with margin.

```bash
export HASS_TOKEN=<long-lived access token>
python3 analysis/calibrate_tau.py --rate-check --url http://homeassistant.local:8123 \
    --fridge-entity sensor.your_fridge_temperature
```

It is read-only: the blueprint's threshold inputs are not script-writable, so paste the
recommended value into the blueprint automation yourself. If the two populations overlap (the
door rate is not clearly above the compressor ceiling), your compressor is unusually fast or
the sensor reports too slowly to separate them by rate alone — fall back to a timed opening and,
if needed, the auxiliary door sensor.

## Backfill historical statistics

Run this AFTER calibrating τ — the script reads the tau helper for its duration estimates.
`analysis/backfill_statistics.py` reconstructs door-opening statistics for the time BEFORE
the blueprint was installed — from Home Assistant's own data only (no external database):
full-resolution recorder history for the last ~10 days, and the fridge sensor's hourly
long-term statistics (never purged) for everything older. It imports the result into the
package sensors' long-term statistics and can seed the counters and utility meters.

```bash
export HASS_TOKEN=<long-lived access token>
pip install websockets   # only dependency, for the statistics API
python3 analysis/backfill_statistics.py --url http://homeassistant.local:8123 \
    --fridge-entity sensor.your_fridge_temperature \
    --ambient-entity sensor.your_living_room_temperature \
    --since 2026-01-01           # dry run: prints the reconstructed monthly table
# add:  --apply            import the statistics
#       --replace          clear the target statistics first
#       --seed             set counter/total helpers + calibrate utility meters
```

> [!NOTE]
> The long-term-statistics branch is a documented lower bound: at most one opening per
> hour is detectable, openings that stay below the compressor ceiling are invisible, and
> multi-opening evening clusters collapse into one event. Sustained warm-ups (door ajar,
> warm food, loading sessions) are counted as one opening each — matching the live
> classifier — with a capped τ-model duration: hourly data cannot separate the door-open
> span from the recovery phase, and the raw episode span would overstate open time by
> orders of magnitude. Expect reconstructed months to undercount versus live detection.

> [!IMPORTANT]
> Moving the sensor to a different shelf changes τ. Recalibrate after any reposition.

## Monitor a second appliance (freezer)

The blueprint is per-appliance; the package's helpers are one appliance's state.

1. Duplicate the helper/mirror/statistics blocks in the package with a distinct prefix
   (`freezer_` instead of `fridge_`), adjust names, restart.
2. Create a second automation from the same blueprint, select the freezer's sensors, and
   point every state-helper input at the new helper set.
3. Freezer notes: the driving force `T_room − T₀` is roughly twice a fridge's, so excursions
   are larger; calibrate a separate τ (different air volume and sensor placement).

## Troubleshooting

| Symptom | Check |
|---|---|
| No events at all | Does the sensor report often enough? Compare its history cadence against the 1–10 min requirement. Verify the automation is enabled and its trace shows runs on temperature reports. |
| Openings detected but durations look wrong by a constant factor | τ is miscalibrated — run a timed opening. |
| Short openings never appear | Expected: openings below ~15–30 s fall under the `rise_amp_min` blip threshold and are discarded ([limitations](../README.md#limitations)). |
| Alarm fires during normal cooking sessions | Raise `ajar_minutes`, or raise `critical_temp` if your fridge runs warm. |
| False door events from the compressor cycle | Your compressor edge is faster than the default 0.10 °C/min — run `calibrate_tau.py --rate-check` and raise `rise_rate_min` (see [Calibrate detection thresholds](#calibrate-detection-thresholds)). |
| Everything classified `sustained_warmup` | The ambient sensor input probably points at a wrong (e.g. outdoor) sensor, making the drive term implausible — verify both sensor inputs. |
| False openings right after a Home Assistant restart | Not expected — the blueprint guards `unknown`/`unavailable` transitions. If observed, check whether another integration replays stale states for the sensor, and open an issue with the automation trace. |
