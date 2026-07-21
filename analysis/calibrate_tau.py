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

  # or, to calibrate the detection rate threshold instead of tau (fridge sensor only):
  python3 calibrate_tau.py --rate-check --url http://homeassistant.local:8123 \
      --fridge-entity sensor.fridge_temperature

Read-only by default; --apply writes the tau recommendation to the tau helper.
--rate-check is always read-only (blueprint threshold inputs are not script-writable).
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


def _segments(fridge):
    """[(index, slope_°C_per_min, dv_°C, dt_s)] for every dt>0 report pair, plus V."""
    T = [p[0] for p in fridge]
    V = [p[1] for p in fridge]
    segs = [(i, (V[i + 1] - V[i]) / (T[i + 1] - T[i]) * 60.0, V[i + 1] - V[i], T[i + 1] - T[i])
            for i in range(len(fridge) - 1) if T[i + 1] > T[i]]
    return segs, V


def _burst_seg_ids(segs, V):
    """Indices into `segs` inside a qualifying door-opening burst (fast run >= AMP_MIN)."""
    in_burst = set()
    j = 0
    while j < len(segs):
        _, sl, dv, _ = segs[j]
        if sl >= SLOPE_MIN and dv > 0:
            k = j
            while (k + 1 < len(segs) and segs[k + 1][0] == segs[k][0] + 1
                   and segs[k + 1][1] >= SLOPE_MIN and segs[k + 1][2] > 0):
                k += 1
            if V[segs[k][0] + 1] - V[segs[j][0]] >= AMP_MIN:
                in_burst.update(range(j, k + 1))
            j = k + 1
        else:
            j += 1
    return in_burst


def rate_check(fridge):
    """Report compressor vs door-event rise rates and recommend rise_rate_min.

    Fridge sensor only. The blueprint tests a door open per SINGLE report pair whose
    rise clears SEG_MIN_DV (0.15 °C) — so this uses exactly that unit: per-segment
    rise rates of dv>=0.15 segments (short quantization steps are excluded exactly as
    the blueprint excludes them), split into door (inside a qualifying burst) vs
    passive (compressor) edges. Recommendation = geometric midpoint of the two.
    """
    segs, V = _segments(fridge)
    in_burst = _burst_seg_ids(segs, V)
    door = sorted(segs[k][1] for k in in_burst if segs[k][2] >= SEG_MIN_DV)
    passive = sorted(s[1] for k, s in enumerate(segs)
                     if k not in in_burst and s[2] >= SEG_MIN_DV)
    print(f'qualifying segments (single-step rise >= {SEG_MIN_DV} °C): '
          f'{len(passive)} passive (compressor), {len(door)} door')
    if len(passive) < 20:
        sys.exit('too few qualifying passive segments to characterise the compressor — '
                 'extend --days')

    ceil = pct(passive, 95)
    print('\ncompressor (passive) per-segment rise-rate percentiles [°C/min]:')
    print(f'  p50={pct(passive, 50):.3f}  p90={pct(passive, 90):.3f}  '
          f'p95={ceil:.3f}  max={passive[-1]:.3f}')

    if len(door) < MIN_EVENTS:
        print(f'\nonly {len(door)} door segments detected — too few to characterise door events.')
        print('Use a timed opening (docs/installation.md#calibrate-τ) or extend --days.')
        print(f'\ncompressor ceiling (p95) = {ceil:.2f} °C/min — set rise_rate_min above it.')
        return

    dfloor, dmid = pct(door, 10), pct(door, 50)
    print('\ndoor-event per-segment rise-rate percentiles [°C/min]:')
    print(f'  p10={dfloor:.3f}  median={dmid:.3f}  max={door[-1]:.3f}')
    if dfloor <= ceil:
        rec = math.sqrt(ceil * dmid)
        print(f'\n⚠ overlap: the door-event floor (p10 {dfloor:.2f}) is at or below the '
              f'compressor ceiling (p95 {ceil:.2f}) — rate alone separates them only loosely.')
        print(f'  Tentative rise_rate_min ≈ {rec:.2f} °C/min (compressor p95 × door median); '
              'confirm with a timed opening, and consider the auxiliary door sensor.')
        return

    rec = math.sqrt(ceil * dfloor)
    print(f'\nrecommended rise_rate_min: {rec:.2f} °C/min  '
          f'(between compressor {ceil:.2f} and door {dfloor:.2f}; shipped default 0.10)')
    print("Paste it into the blueprint automation's rise_rate_min input "
          '(blueprint inputs are not script-writable).')


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--url', required=True, help='Home Assistant base URL')
    ap.add_argument('--token', default=os.environ.get('HASS_TOKEN'),
                    help='long-lived access token (default: HASS_TOKEN env var)')
    ap.add_argument('--fridge-entity', required=True)
    ap.add_argument('--ambient-entity',
                    help='required for tau calibration; omit with --rate-check')
    ap.add_argument('--days', type=int, default=10,
                    help='history window (default 10 = default recorder retention)')
    ap.add_argument('--rate-check', action='store_true',
                    help='report compressor vs door-event rise rates and recommend '
                         'rise_rate_min (fridge sensor only); always read-only')
    ap.add_argument('--apply', action='store_true',
                    help='write the recommended tau to the tau helper')
    ap.add_argument('--tau-entity', default='input_number.fridge_tau')
    args = ap.parse_args()
    if not args.token:
        sys.exit('no token: pass --token or set HASS_TOKEN')

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    fridge = fetch_history(args.url, args.token, args.fridge_entity, start, end)
    if len(fridge) < 100:
        sys.exit('too few fridge samples — sensor must report every 1-10 minutes '
                 '(see docs/installation.md prerequisites)')

    if args.rate_check:
        print(f'history: {len(fridge)} fridge samples ({args.days} days)')
        rate_check(fridge)
        return

    if not args.ambient_entity:
        sys.exit('--ambient-entity is required for tau calibration (omit only with --rate-check)')
    ambient = fetch_history(args.url, args.token, args.ambient_entity, start, end)
    print(f'history: {len(fridge)} fridge samples, {len(ambient)} ambient samples '
          f'({args.days} days)')

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
