#!/usr/bin/env python3
"""Backtest the humidity short-grab rule against recorder history.

LIMITATION — read this before trusting any number: recorder history exposes
``last_changed`` only, while the shipped blueprint computes its rate over
``last_reported`` gaps. For any report pair, the ``last_reported`` gap is <=
the state-change gap this script measures, so the live rule computes rates
>= the backtested ones and admits pairs this script rejects at the gap gate.
Results are therefore LOWER BOUNDS on live booking volume, and a night-quiet
result here is evidence about the approximation, not a guarantee for the
shipped rule. (The v0.4.0 release numbers came from this logic; see
docs/reference.md "Humidity grab monitor".)

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
    ap.add_argument("--url", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--humidity", required=True, help="in-fridge humidity sensor entity")
    ap.add_argument("--door", required=True, help="door-state input_boolean written by the door monitor")
    ap.add_argument("--days", type=float, default=11)
    ap.add_argument("--rate-min", type=float, default=0.2, help="%%RH/s (blueprint grab_rate_min)")
    ap.add_argument("--amp-min", type=float, default=4.0, help="%%RH (blueprint grab_amp_min)")
    ap.add_argument("--max-gap", type=float, default=180.0, help="s (blueprint max_report_gap)")
    ap.add_argument("--claim-minutes", type=float, default=5.0, help="blueprint claim_wait_minutes")
    ap.add_argument("--tz", default="Europe/Berlin", help="timezone for the hour histogram")
    args = ap.parse_args()

    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(days=args.days)

    hum_rows = [(parse_ts(p["last_changed"]), float(p["state"]))
                for p in fetch_history(args.url, args.token, args.humidity, start, end)
                if p["state"] not in ("unknown", "unavailable", "")]
    door_rows = [(parse_ts(p["last_changed"]), p["state"])
                 for p in fetch_history(args.url, args.token, args.door, start, end)]
    if len(hum_rows) < 2:
        sys.exit("not enough humidity history")
    hum_rows.sort()
    door_rows.sort()
    door_times = [t for t, _ in door_rows]

    def door_state_at(t):
        i = bisect.bisect_right(door_times, t) - 1
        return door_rows[i][1] if i >= 0 else "off"

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
    booked, suppressed, rejected_open, folded = [], [], [], []
    for t, dv in candidates:
        if busy_until is not None and t < busy_until:
            folded.append(t)
            continue
        if door_state_at(t) == "on":
            rejected_open.append(t)
            continue
        on = next_door_on(t)
        if on is not None and on - t <= claim:
            suppressed.append((t, (on - t).total_seconds()))
            busy_until = on
        else:
            booked.append((t, dv))
            busy_until = t + claim

    days = (hum_rows[-1][0] - hum_rows[0][0]).total_seconds() / 86400
    tz = ZoneInfo(args.tz) if ZoneInfo else datetime.timezone.utc
    hours = Counter(t.astimezone(tz).hour for t, _ in booked)
    night = sum(hours[h] for h in (1, 2, 3, 4))

    print(f"window: {days:.1f} days, {len(hum_rows)} humidity state changes")
    print(f"candidates passing amp/rate/gap gates: {len(candidates)}")
    print(f"BOOKED short grabs: {len(booked)} ({len(booked) / days:.1f}/day)")
    print(f"suppressed by temperature-channel claim: {len(suppressed)}"
          + (f" (delays s: min={min(d for _, d in suppressed):.0f}"
             f" max={max(d for _, d in suppressed):.0f})" if suppressed else ""))
    print(f"rejected (door already open): {len(rejected_open)}; folded into episodes: {len(folded)}")
    print(f"bookings 01:00-05:00 {args.tz}: {night}")
    print("bookings per hour:", dict(sorted(hours.items())))
    print("\nREMINDER: last_changed approximation — live rule admits MORE pairs "
          "(see module docstring).")


if __name__ == "__main__":
    main()
