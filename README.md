# fridge-stats

Detect fridge door openings in Home Assistant from two temperature sensors — one inside the
fridge, one an ambient/room reference — with no door contact sensor. A door opening warms the
fridge interior toward room temperature far faster than the compressor cycle ever does; this
project turns that physics into door events, per-opening duration estimates, a logbook history,
usage statistics, and alarms for a door left ajar. (Detection itself uses only the in-fridge
sensor; the ambient sensor is required to turn each detected excursion into a season-independent
duration estimate.)

> [!NOTE]
> Duration estimates are physics-based approximations. Medians and comparisons hold under
> ±50 % threshold variation; absolute per-event seconds carry roughly a factor-2 uncertainty
> until calibrated against a timed opening. See [docs/physics.md](docs/physics.md).

**One-click blueprint import** (Home Assistant 2026.6+):

[![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.][import-badge]][import-link]

The badge imports the blueprint only. The helper entities come from the package, so
the full setup is still two files — see [Install](#install).

## Features

- **Door detection from rise rate**: on the reference fridge, door events warmed the sensor at
  ≥0.3 °C/min while the compressor cycle stayed ≤0.06 °C/min — a rate threshold (default
  0.10 °C/min) separates them with a 5–12× margin. Those rates are measured on one fridge, not
  universal; calibrate your own with `analysis/calibrate_tau.py --rate-check`. The temperature
  falling again closes the event.
- **Physical duration model**: `t_open = −τ · ln(1 − ΔT_peak / (T_room − T₀))` — the ambient
  sensor supplies the thermal driving force, so a summer opening and a winter opening of equal
  length score equally.
- **Five bus events** with data payloads: `fridge_door_opened`, `fridge_door_closed`,
  `fridge_door_ajar`, `fridge_temp_critical`, `fridge_aux_trigger`
  ([reference](docs/reference.md#events)).
- **Event classes**: `quick_grab` / `normal_grab` / `extended_open` / `sustained_warmup`
  (door ajar, warm food, or rapid repeated access) / `blip` (discarded).
- **Logbook history**: every opening, closing, and alarm writes a logbook entry on the
  door-state entity.
- **Statistics layer**: total and daily/weekly/monthly opening counts, accumulated open time,
  7-day median and maximum duration.
- **Two-tier alarms** with user-defined actions: door-ajar warning (default after 15 min) and
  a critical over-temperature backstop (default >10 °C (50 °F) sustained 30 min) that also
  catches appliance failure and survives restarts.
- **Sensor-silence watchdog** (companion blueprint `fridge_sensor_watchdog.yaml`): alerts when
  the fridge sensor stops reporting for a configurable time (default 3 h) — a battery dead in
  the cold or a dropped link otherwise fails invisibly. Uses `last_reported`, so a steady
  temperature never false-alarms; fires `fridge_sensor_silent` / `fridge_sensor_recovered`.
- **Fully configurable blueprint** (typed selectors): fridge sensor, ambient sensor, optional
  auxiliary door/motion/vibration sensor for future sensor fusion, all thresholds, alarm
  actions. Instantiate per appliance — a freezer needs only a second helper set.
- **Calibration and backfill toolkit**: τ self-calibration from recorder history and
  statistics backfill from the sensor's long-term statistics — Home Assistant onboard data
  only, no external database.
- **Read-only toward your system**: the configured sensors are only read; the project
  writes exclusively to its own entities ([access guarantee](docs/reference.md#access-guarantee)).

## Requirements

- Home Assistant ≥ 2026.6.
- A temperature sensor inside the fridge with event-driven reporting at roughly 1–10 minute
  intervals and ≤0.1 °C resolution (tested with an Aqara-class Zigbee multisensor).
- An ambient temperature sensor on the same floor as the fridge.
- YAML packages enabled (`homeassistant: packages: !include_dir_named packages`).
- **No HACS or custom components required** — blueprint, package, and the example
  dashboard views use core Home Assistant only.

## Install

1. Copy `package/fridge_stats.yaml` to `<config>/packages/`.
2. Import the blueprint — click the badge, which opens the import dialog in your instance:

   [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.][import-badge]][import-link]

   or copy `blueprints/fridge_door_monitor.yaml` to
   `<config>/blueprints/automation/fridge_stats/` manually.
3. Enable packages in `configuration.yaml` if not already enabled, run a configuration check,
   and restart Home Assistant.
4. Create an automation from the **Fridge Door Monitor** blueprint and select your fridge and
   ambient temperature sensors. The state-helper inputs default to the entities the package
   creates.
5. Seed the calibration constant: set `input_number.fridge_tau` to `1028` (or your own
   calibrated value — see [calibration](docs/installation.md#calibrate-τ)).

Step-by-step instructions, multi-appliance setup, and troubleshooting:
[docs/installation.md](docs/installation.md).

## Documentation

| Document | Type | Contents |
|---|---|---|
| [docs/reference.md](docs/reference.md) | Reference | Blueprint inputs, entities, events and payloads, classes, thresholds |
| [docs/installation.md](docs/installation.md) | How-to | Install, multi-appliance, τ calibration, troubleshooting |
| [docs/physics.md](docs/physics.md) | Explanation | Model derivation, detection design, calibration method, validation evidence, limitations |
| [docs/ideas.md](docs/ideas.md) | Roadmap | Research-backed feature backlog with sources |

## Limitations

- Openings shorter than ~15–30 s are discarded by the detector's own blip threshold (a
  cumulative rise below `rise_amp_min`, 0.30 °C, is treated as compressor noise) — a design
  choice, not a sensor-resolution limit (the sensor itself resolves 0.01 °C). This floor is a
  physics estimate, not measured (the shortest verified test was 30–60 s); detected counts are
  a lower bound on true openings, and no door-sensor ground truth exists to quantify the gap.
- Events fire 1–4 minutes after the physical action (sensor reporting cadence); the
  `opened_at` timestamp is the last pre-rise report.
- Closely spaced openings merge into episodes; `sustained_warmup` cannot distinguish a door
  left ajar from warm food being inserted or rapid repeated access. The auxiliary sensor
  input exists to resolve this in a future version.
- Moving the sensor to another shelf invalidates τ — recalibrate after any reposition.
- Battery percentage readings from sensors inside a fridge are unreliable; monitor sensor
  liveness (report silence) instead.

## Prior art and credits

No published Home Assistant blueprint or package with a model-based thermal door detector was
found; the closest community approach gates a threshold alert with a derivative-sensor
condition. Sources, comparisons, and community-reported pitfalls are collected in
[docs/ideas.md](docs/ideas.md#8-community-prior-art).

## License

[MIT](LICENSE)

[import-badge]: https://my.home-assistant.io/badges/blueprint_import.svg
[import-link]: https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Flunetics%2Ffridge-stats%2Fblob%2Fmain%2Fblueprints%2Ffridge_door_monitor.yaml
