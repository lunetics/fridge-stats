#!/usr/bin/env python3
"""Calibrate the fridge-stats tau constant from Home Assistant recorder history.

Works against any Home Assistant instance via the REST API — no InfluxDB required.
The default recorder retention (~10 days) provides enough door-opening events for a
stable estimate in a normally used household fridge.

Method: door-opening rise bursts are detected by rise rate; every short rise segment
inside a burst yields an estimator tau_hat = (T_room - T_mid) / slope. Closed-door
contamination can only bias tau_hat upward, so the 10th percentile of per-event
minima approaches the true constant from above. See docs/physics.md.

Usage:
  export HASS_TOKEN=<long-lived access token>
  python3 calibrate_tau.py --url http://homeassistant.local:8123 \
      --fridge-entity sensor.fridge_temperature \
      --ambient-entity sensor.living_room_temperature \
      [--days 10] [--apply] [--tau-entity input_number.fridge_tau]

Read-only by default; --apply writes the recommendation to the tau helper.
"""
import argparse
import bisect
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

SLOPE_MIN = 0.10       # °C/min: minimum rise rate of a door event segment
AMP_MIN = 0.30         # °C: minimum cumulative rise of a burst
SEG_MAX_DT = 180       # s: calibration segments must be short (least contamination)
SEG_MIN_DV = 0.15      # °C: minimum rise of a calibration segment
MIN_EVENTS = 5         # below this the estimate is unreliable


def api(base, token, path, data=None):
    req = urllib.request.Request(
        base.rstrip('/') + path,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def fetch_history(base, token, entity, start, end):
    """Return sorted [(epoch_seconds, value)] for one entity from the recorder."""
    q = urllib.parse.urlencode({'filter_entity_id': entity,
                                'end_time': end.isoformat(),
                                'no_attributes': '1'})
    path = f"/api/history/period/{urllib.parse.quote(start.isoformat())}?{q}"
    series = []
    for chunk in api(base, token, path):
        for item in chunk:
            try:
                v = float(item['state'])
            except (KeyError, TypeError, ValueError):
                continue
            ts = item.get('last_changed') or item.get('last_updated')
            t = datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp()
            series.append((t, v))
    return sorted(set(series))


def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--url', required=True, help='Home Assistant base URL')
    ap.add_argument('--token', default=os.environ.get('HASS_TOKEN'),
                    help='long-lived access token (default: HASS_TOKEN env var)')
    ap.add_argument('--fridge-entity', required=True)
    ap.add_argument('--ambient-entity', required=True)
    ap.add_argument('--days', type=int, default=10,
                    help='history window (default 10 = default recorder retention)')
    ap.add_argument('--apply', action='store_true',
                    help='write the recommended tau to the tau helper')
    ap.add_argument('--tau-entity', default='input_number.fridge_tau')
    args = ap.parse_args()
    if not args.token:
        sys.exit('no token: pass --token or set HASS_TOKEN')

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    fridge = fetch_history(args.url, args.token, args.fridge_entity, start, end)
    ambient = fetch_history(args.url, args.token, args.ambient_entity, start, end)
    print(f'history: {len(fridge)} fridge samples, {len(ambient)} ambient samples '
          f'({args.days} days)')
    if len(fridge) < 100:
        sys.exit('too few fridge samples — sensor must report every 1-10 minutes '
                 '(see docs/installation.md prerequisites)')

    at = [p[0] for p in ambient]

    def room_at(t):
        i = bisect.bisect_left(at, t)
        lo = ambient[i - 1] if i > 0 else None
        hi = ambient[i] if i < len(ambient) else None
        if lo and hi and hi[0] > lo[0]:
            f = (t - lo[0]) / (hi[0] - lo[0])
            return lo[1] + f * (hi[1] - lo[1])
        pick = lo or hi
        return pick[1] if pick and abs(pick[0] - t) <= 21600 else None

    T = [p[0] for p in fridge]
    V = [p[1] for p in fridge]
    segs = []
    for i in range(len(fridge) - 1):
        dt = T[i + 1] - T[i]
        if dt > 0:
            segs.append((i, (V[i + 1] - V[i]) / dt * 60.0, V[i + 1] - V[i], dt))

    # rise bursts: runs of fast-rising segments with sufficient cumulative rise
    per_event_min = []
    j = 0
    while j < len(segs):
        i, sl, dv, dt = segs[j]
        if sl >= SLOPE_MIN and dv > 0:
            k = j
            while (k + 1 < len(segs) and segs[k + 1][0] == segs[k][0] + 1
                   and segs[k + 1][1] >= SLOPE_MIN and segs[k + 1][2] > 0):
                k += 1
            s_idx, e_idx = segs[j][0], segs[k][0] + 1
            if V[e_idx] - V[s_idx] >= AMP_MIN:
                best = None
                for ii, ssl, sdv, sdt in segs[j:k + 1]:
                    if sdt <= SEG_MAX_DT and sdv >= SEG_MIN_DV:
                        tr = room_at(T[ii])
                        if tr is None:
                            continue
                        drive = tr - (V[ii] + V[ii + 1]) / 2
                        if drive <= 2:
                            continue
                        tau_hat = drive / (sdv / sdt)
                        if 60 < tau_hat < 36000 and (best is None or tau_hat < best):
                            best = tau_hat
                if best:
                    per_event_min.append(best)
            j = k + 1
        else:
            j += 1

    per_event_min.sort()
    n = len(per_event_min)
    print(f'door-opening events with a usable calibration segment: {n}')
    if n < MIN_EVENTS:
        sys.exit(f'fewer than {MIN_EVENTS} usable events — extend --days, or use the '
                 'stopwatch method (docs/installation.md#calibrate-τ)')
    tau = pct(per_event_min, 10)
    print(f'tau estimators: p10={tau:.0f}s  p25={pct(per_event_min, 25):.0f}s  '
          f'median={pct(per_event_min, 50):.0f}s')
    print(f'\nrecommended tau: {tau:.0f} s  (10th percentile — see docs/physics.md '
          'for the bias argument)')

    if args.apply:
        api(args.url, args.token, '/api/services/input_number/set_value',
            data={'entity_id': args.tau_entity, 'value': round(tau)})
        print(f'applied to {args.tau_entity}')
    else:
        print(f'dry run — re-run with --apply to write {args.tau_entity}')


if __name__ == '__main__':
    main()
