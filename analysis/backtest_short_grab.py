#!/usr/bin/env python3
"""Backtest the humidity short-grab rule against recorder history.

LIMITATIONS — read this before trusting any number:

1. Recorder history exposes ``last_changed`` only, while the shipped blueprint
   computes its rate over ``last_reported`` gaps. For any report pair, the
   ``last_reported`` gap is <= the state-change gap this script measures, so
   the live rule computes rates >= the backtested ones and admits pairs this
   script rejects at the gap gate. That inequality holds at the CANDIDATE-GATE
   level: booked counts here approximate live volume from below in steady
   state, but are not an unconditional guarantee.
2. The replay does not model the blueprint's restart/reload guard (live runs
   are suppressed for ``max_report_gap`` after automation startup/reload), so
   around restarts the live system can book FEWER events than this replay.
3. ``mode: single`` episode folding depends on which candidates exist: live-only
   candidates can open claim windows that fold candidates this replay books.
4. A night-quiet result is evidence about the approximation over the sampled
   window, not proof that a specific physical source (e.g. the compressor
   cycle) can never book.

(The v0.4.0 release numbers came from this logic; see docs/reference.md
"Humidity grab monitor".)

Replays the full rule otherwise: amplitude + rate + report-gap gates, the
door-state exclusion, the temperature-channel claim window, and the
``mode: single`` episode folding.

Usage:
  python3 backtest_short_grab.py --url http://ha:8123 --token $TOKEN \
      --humidity sensor.fridge_humidity --door input_boolean.fridge_door_open \
      --days 11 [--rate-min 0.2] [--amp-min 4] [--max-gap 180] \
      [--claim-minutes 5] [--tz Europe/Berlin]
"""
import argparse
import bisect
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None


def fetch_history(url, token, entity_id, start, end):
    query = urllib.parse.urlencode({
        "filter_entity_id": entity_id,
        "end_time": end.isoformat(),
        "significant_changes_only": "false",
        "no_attributes": "true",
    })
    req = urllib.request.Request(
        f"{url}/api/history/period/{urllib.parse.quote(start.isoformat())}?{query}",
        headers={"Authorization": f"Bearer {token}"})
    data = json.load(urllib.request.urlopen(req, timeout=120))
    return data[0] if data else []


def parse_ts(value):
    return datetime.datetime.fromisoformat(value)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("HA_URL"),
                    help="HA base URL (or env HA_URL)")
    ap.add_argument("--token", default=os.environ.get("HA_TOKEN"),
                    help="long-lived token (or env HA_TOKEN — keeps it out of argv)")
    ap.add_argument("--humidity", required=True, help="in-fridge humidity sensor entity")
    ap.add_argument("--door", required=True, help="door-state input_boolean written by the door monitor")
    ap.add_argument("--days", type=float, default=11)
    ap.add_argument("--rate-min", type=float, default=0.2, help="%%RH/s (blueprint grab_rate_min)")
    ap.add_argument("--amp-min", type=float, default=4.0, help="%%RH (blueprint grab_amp_min)")
    ap.add_argument("--max-gap", type=float, default=180.0, help="s (blueprint max_report_gap)")
    ap.add_argument("--claim-minutes", type=float, default=5.0, help="blueprint claim_wait_minutes")
    ap.add_argument("--tz", default="Europe/Berlin", help="timezone for the hour histogram")
    args = ap.parse_args()
    if not (args.url and args.token):
        ap.error("need --url and --token (or env HA_URL / HA_TOKEN)")
    url = args.url.rstrip("/")
    if ZoneInfo is None and args.tz.upper() != "UTC":
        sys.exit(f"zoneinfo unavailable (Python < 3.9) — cannot honor --tz {args.tz}; "
                 f"pass --tz UTC explicitly or run on Python >= 3.9")

    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=args.days)

    hum_rows = [(parse_ts(p["last_changed"]), float(p["state"]))
                for p in fetch_history(url, args.token, args.humidity, start, end)
                if p["state"] not in ("unknown", "unavailable", "")]
    # door: keep every row — non-on/off states (unavailable/unknown) must act as
    # "not off" in door_state_at(), exactly like the blueprint's state condition,
    # not silently inherit the previous real state
    door_rows = [(parse_ts(p["last_changed"]), p["state"])
                 for p in fetch_history(url, args.token, args.door, start, end)]
    if len(hum_rows) < 2:
        sys.exit("not enough humidity history")
    hum_rows.sort()
    door_rows.sort()
    door_times = [t for t, _ in door_rows]

    def door_state_at(t):
        # no prior sample -> "unknown": the blueprint proceeds only on an
        # explicit "off", so an unknown door state must reject, not book
        i = bisect.bisect_right(door_times, t) - 1
        return door_rows[i][1] if i >= 0 else "unknown"

    def next_door_on(t):
        i = bisect.bisect_right(door_times, t)
        while i < len(door_rows):
            if door_rows[i][1] == "on":
                return door_rows[i][0]
            i += 1
        return None

    # Candidate gates on consecutive state changes (last_changed basis — see header).
    candidates = []
    for (t0, v0), (t1, v1) in zip(hum_rows, hum_rows[1:]):
        gap = (t1 - t0).total_seconds()
        dv = v1 - v0
        if dv >= args.amp_min and 0 < gap <= args.max_gap and dv / gap >= args.rate_min:
            candidates.append((t1, dv))

    claim = datetime.timedelta(minutes=args.claim_minutes)
    busy_until = None
    booked, suppressed, rejected_not_off, folded, censored = [], [], [], [], []
    for t, dv in candidates:
        if busy_until is not None and t < busy_until:
            folded.append(t)
            continue
        if door_state_at(t) != "off":
            rejected_not_off.append(t)
            continue
        if t > end - claim:
            # right-censored: the claim window extends past the queried data —
            # the door might have claimed it after `end`; excluding keeps the
            # replay honest instead of inflating the tail of the histogram
            censored.append(t)
            continue
        on = next_door_on(t)
        if on is not None and on - t <= claim:
            suppressed.append((t, (on - t).total_seconds()))
            busy_until = on
        else:
            booked.append((t, dv))
            busy_until = t + claim

    observed_days = (hum_rows[-1][0] - hum_rows[0][0]).total_seconds() / 86400
    if observed_days <= 0:
        sys.exit("humidity data spans zero time — nothing to rate")
    tz = ZoneInfo(args.tz) if ZoneInfo else datetime.timezone.utc
    hours = Counter(t.astimezone(tz).hour for t, _ in booked)
    night = sum(hours[h] for h in (1, 2, 3, 4))

    print(f"window: requested {args.days:.1f} d, observed data span {observed_days:.1f} d, "
          f"{len(hum_rows)} humidity state changes")
    if door_rows and door_rows[0][0] > hum_rows[0][0]:
        print(f"NOTE: door history only starts {door_rows[0][0].isoformat()} — every "
              f"candidate before that rejects as door-state unknown (the helper did not "
              f"exist yet); shrink --days to the overlap for a meaningful rate")
    print(f"candidates passing amp/rate/gap gates: {len(candidates)}")
    print(f"BOOKED short grabs: {len(booked)} ({len(booked) / observed_days:.1f}/observed day)")
    print(f"suppressed by temperature-channel claim: {len(suppressed)}"
          + (f" (delays s: min={min(d for _, d in suppressed):.0f}"
             f" max={max(d for _, d in suppressed):.0f})" if suppressed else ""))
    print(f"rejected (door state not 'off'): {len(rejected_not_off)}; "
          f"folded into episodes: {len(folded)}; right-censored at window end: {len(censored)}")
    print(f"bookings 01:00-05:00 {args.tz}: {night}")
    print("bookings per hour:", dict(sorted(hours.items())))
    print("\nREMINDER: last_changed approximation with unmodeled restart-guard and "
          "folding effects — see LIMITATIONS in the module docstring.")


if __name__ == "__main__":
    main()
