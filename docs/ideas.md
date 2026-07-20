# Ideas: what else the fridge data can do

> [!NOTE]
> Internal roadmap and research notes, not release documentation. On publication these
> items migrate to the issue tracker.

Status 2026-07-20 v2: merged from (a) the 7-month session analysis/physics and
(b) the fridge-analytics research report (sources = actually-fetched URLs; scout
inferences are flagged as such), plus (c) the community prior-art report in
[§8](#8-community-prior-art).

## 1. Appliance health (predictive maintenance) — Tier 1

- **Compressor duty-cycle & cycle-period trend** (no power sensor needed): detect
  sawtooth minima/maxima → per-cycle period (~45 min today) + amplitude (~1.3 K) →
  weekly duty-cycle %. Rising duty at constant ambient = seal/condenser/refrigerant
  degradation, weeks before any temperature alarm — temperature alone is a *lagging*
  indicator ([Lab Design News](https://www.labdesignnews.com/content/predictive-maintenance-listening-to-freezer-motors),
  [iFactory cold-storage checklist](https://ifactoryapp.com/industries/food-manufacturing/cold-storage-refrigeration-analytics-checklist-food-manufacturing)).
  Real HA case study: fridge diagnosed via "compressor never cycled off" on the
  power graph, ~2,500 kWh/yr vs ~2,000 expected, root cause failed insulation —
  [HA Community case study](https://community.home-assistant.io/t/case-study-the-value-of-monitoring-a-fridge-with-home-assistant/592200).
- **Door-seal degradation**: trend post-close *recovery time* (we timestamp both
  ends of every event) and the *inter-cycle minimum temp* — both drift upward with
  a leaking gasket; classic signature is short-cycling + baseline several degrees
  high ([CyCookery seal-testing guide](https://cycookery.com/article/how-do-you-test-seals-on-refrigerator)).
- **Baseline drift alert**: EWMA of daily compressor-band median; ≥0.5 K sustained
  drift → check appliance. 2026 baseline is stable ~5 °C = clean reference
  *(session-derived)*.
- **Defrost detection** (also protects the door-detector from misclassification):
  defrost pulses are periodic (~24 h in the case study above), uncorrelated with
  door events, slower-sloped (phase-change plateau). None observed in our fridge in
  2026 — a NEW periodic excursion appearing is itself an anomaly worth alerting
  *(mechanism descriptions are WebSearch-synthesized from patent snippets, not
  opened PDFs — treat as directionally right)*.
- **Refrigerant-leak detection**: the good indicator (discharge-line temp) needs a
  sensor we don't have; folds into the duty-cycle trend as a slow multi-month read
  ([Compressors Unlimited](https://www.compressorsunlimited.com/signs-of-a-leaky-refrigeration-compressor-service-valve/)).

## 2. Food safety (HACCP-style, implementable today) — Tier 1

Threshold stack (sources per line):
- Target: **≤4.4 °C** (40 °F) consistently — [FDA](https://www.fda.gov/food/buy-store-serve-safe-food/refrigerator-thermometers-cold-facts-about-food-safety).
- Danger zone: **>4 °C**, bacteria can double in 20 min — [USDA FSIS](https://www.fsis.usda.gov/food-safety/safe-food-handling-and-preparation/food-safety-basics/danger-zone-40f-140f).
- Corrective window: **>41 °F for 4 h = unsafe** (commercial "4-hour rule"; strict
  operators trigger at 2 h) — [Refrigeration Technologies](https://refrigerationtechnologiesllc.com/commercial-refrigeration-4-hour-rule/).
- EU/UK frame: legal max **8 °C**, working target **5 °C** — [Chilled Food Association](https://www.chilledfood.org/temperature/)
  *(secondary-sourced, not primary EUR-Lex text)*. Context: EU home fridges average
  6.4 °C — [ANSES](https://www.anses.fr/en/content/domestic-fridge-temperatures-studied-europe-better-protect-consumers).

Concrete build: integrate minutes-above-4 °C (or 8 °C strict-EU variant) per
rolling 24 h; warn at 2 h, "check/discard contents" advisory at 4 h. Our existing
`fridge_temp_critical` (>11 °C/10 min) stays as the acute tier; a long
`sustained_warmup`/ajar event auto-escalates to the contents advisory (the 05-11
incident: hours at 15–21 °C).

## 3. Energy — Tier 2

- **Per-opening cost**: measured studies beat our first physics guess (which used
  the *ajar crack* conductance — wrong regime for full-open exchange + ignores the
  latent load of humid air): a 12-s opening measured **9–12.4 Wh**
  ([AgentCalc, citing a measured study](https://agentcalc.com/refrigerator-door-open-energy-loss-calculator));
  an LBNL-cited figure says 10 min/day open ≈ **50 kWh/yr**
  ([HouseFixMaster](https://housefixmaster.com/how-much-energy-is-wasted-leaving-refrigerator-door-open/)).
  ⚠️ The two sources disagree ~4× per open-minute — present as a band, not a number.
  Dashboard formula (derived, flag as approximation):
  `Wh ≈ duration_s/12 × 10.5` (upper band).
- **Warm-food-insertion vs door-air cost**: no source separates them; separable in
  OUR data via event class + post-event recovery slope (loading class → thermal
  mass signature) *(engineering inference)*.
- **Ambient correlation**: compressor duty vs room temp → what a hot kitchen costs.

## 4. Usage analytics & fun — Tier 2

- **Day×hour opening heatmap**: [ha-heatmap-card](https://github.com/kandsten/ha-heatmap-card)
  (auto-scales), or the HACS plotly-graph card. Prior art logs door events to jsonl for this:
  [FridgeMate](https://github.com/M-Uzaif/FridgeMate-Smart-Refrigerator-Automation-Monitoring).
- **Midnight-snack detector**: quick_grab events 23:00–04:00, weekly trend —
  a heatmap slice, not a separate build.
- **Vacation/away detection**: multi-day zero-event stretch + loading/searching
  classes silent *(engineering inference, no external source)*.
- **Grocery-day detection**: `loading`-class episodes timestamp shopping days.
- **Monthly fridge report card**: openings, median/longest duration, total open
  time, energy band, duty-cycle trend, safety-minutes — composed from the utility
  meters + statistics sensors; HA Energy dashboard's monthly-ranking pattern as the
  template ([dashboard tour](https://medium.com/@rorygallagher2010/home-assistant-smart-home-dashboard-tour-2025-2aecfb0bc6ee)).
- Gamification (badges/family challenges): UX polish on top of the report card
  ([Zigpoll design piece](https://www.zigpoll.com/content/how-can-we-design-an-interactive-userfriendly-dashboard-that-visually-tracks-realtime-energy-consumption-of-smart-home-appliances-while-incorporating-playful-animations-that-reflect-our-brands-gaming-heritage)).

## 5. Anomaly detection (lightweight, no ML stack) — Tier 1

- **CUSUM+EWMA combined** on cycle period & baseline temp — each alone
  false-positives on complex anomalies; the combination is the published fix
  ([Ulster University](https://pure.ulster.ac.uk/en/publications/a-combination-of-cusum-ewma-for-anomaly-detection-in-time-series--3)).
- **Rolling Z-score (3σ)** Grafana/InfluxDB pattern: `avg_over_time` +
  `stddev_over_time` over ~1 day, alert at Z>3
  ([Vassallo](https://blog.davidvassallo.me/2021/10/01/grafana-prometheus-detecting-anomalies-in-time-series/));
  seasonal variant: average same-hour across past 4 weeks.
- InfluxDB gotcha for our sparse/event-driven series: means jump on missing
  datapoints — use point-count-based moving averages
  ([HA Community thread](https://community.home-assistant.io/t/getting-a-moving-average-from-influxdb/344116)).

## 6. Monitoring & data quality

- **Sensor watchdog** (high value — the sensor was silently dead 06-27→07-11!):
  alert on >3 h without any report *(session-derived)*.
- **Nightly offline recompute** of exact stats + τ via `analysis/` script (cron).

## 7. Sensor fusion (the blueprint's aux input)

- **Vibration/contact sensor on the door** → precise open/close timestamps →
  continuous τ recalibration per event + resolves the sustained_warmup ambiguity
  (ajar vs warm food vs rapid cooking access) *(session-derived; the aux input
  already exists in the blueprint)*.
- **Humidity-based freshness inference**: open research gap, no source found —
  parked *(scout-flagged)*.

## 8. Community prior-art

**Novelty check:** no published HA blueprint/package does model-based door
detection from temperature. Closest match: a hand-rolled `derivative`-sensor
*condition* gating a threshold alert (rising = real problem, falling = recovering
door event) — [#904146](https://community.home-assistant.io/t/freezer-temp-alert-not-falling-as-a-condition/904146).
Community extrapolation is naive-linear ([#423855](https://community.home-assistant.io/t/trigger-if-temp-will-exceed-threshold-in-th-future/423855));
our τ·ln() mixing model is a strict improvement → **publishing the blueprint back
to the community is a genuine contribution** (needs a public repo + `source_url`).

**Steal-worthy patterns:**
- **`alert:` integration for the ajar alarm** (v2 candidate): repeat-until-
  acknowledged + automatic `done_message` + `skip_first`, driven by
  `input_boolean.fridge_door_open` — better UX than a one-shot push. Caveat:
  `alert:` needs a full restart to reload — [#742274](https://community.home-assistant.io/t/refrigerator-freezer-alerting/742274).
- **Derivative-as-condition** (falling temp cancels an over-threshold alert) —
  could refine our `fridge_temp_critical` tier ([#904146](https://community.home-assistant.io/t/freezer-temp-alert-not-falling-as-a-condition/904146)).
- **history_stats** as an alternative counter/total-time backend (on→off flip
  count, time-in-state per period); reported midnight-reset quirk
  ([#763022](https://community.home-assistant.io/t/history-stats-do-not-reset-at-midnight-but-require-an-additional-event-to-reset/763022), unverified).
- **EMA smoothing upstream of rate calculation** if noise-triggered false door
  events ever appear ([pdx.su DIY monitor](https://pdx.su/blog/2025-05-10-diy-overengineered-fridge/freezer-monitor/)).
- Temperature-based > power-based detection, with sourced counter-evidence: a
  failed compressor still draws power while cooling nothing; a user missed a real
  food-loss event on power-only monitoring —
  [#916870](https://community.home-assistant.io/t/alert-when-freezer-consumes-to-much-energy-probably-not-closed/916870).

**Pitfalls (checked against our deployed blueprint where applicable):**
- Bare `from:` triggers also fire on `unknown`/`unavailable` transitions (restart
  false positives) — [#792419](https://community.home-assistant.io/t/need-help-with-lg-fridge-door-open-notifications/792419).
  ✅ Our blueprint guards both `from_state`/`to_state` against
  unknown/unavailable in every temp branch.
- Derivative **UI helper** refuses temperature sources (open bug
  [core#135490](https://github.com/home-assistant/core/issues/135490)) — YAML
  `platform: derivative` works. N/A for us (no derivative helper used), relevant
  if we adopt the derivative-as-condition refinement.
- **Sensor placement change silently invalidates τ** — our 1028 s is calibrated
  for the current shelf position; moving the sensor ⇒ recalibrate
  ([placement thread #729529](https://community.home-assistant.io/t/sensors-for-refrigerator-freezer/729529)).
- Battery-in-cold: sensors report "dead" for months while still working; remedy
  disputed (lithium vs NiMH-LSD) — treat battery % as unreliable in the fridge,
  rely on the >3h-silence watchdog instead
  ([#592200](https://community.home-assistant.io/t/case-study-the-value-of-monitoring-a-fridge-with-home-assistant/592200),
  [battery thread](https://community.home-assistant.io/t/best-type-of-battery-to-withstand-cold-winters/767379)).
- Metal walls attenuate Zigbee — place near door seal, repeater if needed; some
  users bag the sensor against condensation (both [#729529](https://community.home-assistant.io/t/sensors-for-refrigerator-freezer/729529)).
- Single-probe air-current fluctuations → food-simulant buffer probe is the
  hardware fix ([#904146](https://community.home-assistant.io/t/freezer-temp-alert-not-falling-as-a-condition/904146), [pdx.su](https://pdx.su/blog/2025-05-10-diy-overengineered-fridge/freezer-monitor/)).

*Scout coverage notes: 12 Discourse-API queries, 12 sources fully fetched; ESPHome
multi-page threads and a 403-walled 433 MHz blog post skipped (flagged, low value);
no GitHub code-search pass — WebSearch found no published blueprint equivalent.*

## Research-coverage notes (from the analytics scout, preserved honestly)

Reddit unreachable via its search tier (zero hits, browser/credit tiers
deliberately not spent) — HA Community forum substituted and is the dominant venue
for this use case; EU 5/8 °C figures secondary-sourced; defrost/patent mechanisms
tool-synthesized, not opened PDFs; #vacation-detection and warm-food-cost-split are
engineering inferences, not sourced claims.
