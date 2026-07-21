#!/usr/bin/env python3
"""Backfill fridge-stats long-term statistics from Home Assistant's own data.

No external database or export required. Two onboard sources are combined:

1. Recorder raw history (default retention ~10 days): full-resolution burst
   detection, same method as the live blueprint — precise events.
2. Long-term statistics of the fridge temperature sensor (hourly mean/min/max,
   never purged): coarse per-hour detection for everything older — an hour
   whose maximum clearly exceeds the rolling compressor ceiling is counted as
   one opening, its duration estimated with the tau model from the hourly
   amplitude.

The LTS branch is an honest LOWER BOUND: at most one opening per hour is
detectable, sub-ceiling openings are invisible, and hourly amplitudes carry
more uncertainty than raw data. Sustained warm-ups (door ajar, warm food) are
excluded in both branches, matching the live classifier.

Requires the `websockets` package (pip install websockets) for the statistics
API; everything else is stdlib.

Usage:
  export HASS_TOKEN=<long-lived access token>
  python3 backfill_statistics.py --url http://homeassistant.local:8123 \
      --fridge-entity sensor.fridge_temperature \
      --ambient-entity sensor.living_room_temperature \
      [--since 2026-01-01] [--tau 1028] [--replace] [--apply] [--seed]

Dry run by default: prints the reconstructed monthly table and exits.
--apply imports the statistics (--replace clears the target ids first);
--seed additionally sets the counter/total helpers and calibrates the
utility meters.
"""
import argparse
import asyncio
import bisect
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

SLOPE_MIN = 0.10
AMP_MIN = 0.30
CEIL_MARGIN = 0.35     # °C above rolling hourly-max ceiling (LTS branch)
WARMUP_DT = 2.5        # °C: bigger excursions are warm-ups, not openings
WARMUP_RATIO = 0.45
RATIO_MAX = 0.95


def rest(base, token, path, data=None):
    req = urllib.request.Request(
        base.rstrip('/') + path,
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        data=json.dumps(data).encode() if data is not None else None)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


class Ws:
    def __init__(self, base, token):
        self.base, self.token, self.mid = base, token, 0

    async def __aenter__(self):
        try:
            import websockets
        except ImportError:
            sys.exit('this script needs the websockets package: pip install websockets')
        url = self.base.rstrip('/').replace('http', 'ws', 1) + '/api/websocket'
        self.conn = await __import__('websockets').connect(url, max_size=32 * 2 ** 20)
        await self.conn.recv()
        await self.conn.send(json.dumps({'type': 'auth', 'access_token': self.token}))
        await self.conn.recv()
        return self

    async def __aexit__(self, *exc):
        await self.conn.close()

    async def cmd(self, payload):
        self.mid += 1
        payload['id'] = self.mid
        await self.conn.send(json.dumps(payload))
        while True:
            m = json.loads(await self.conn.recv())
            if m.get('id') == self.mid and m.get('type') == 'result':
                if not m.get('success'):
                    raise RuntimeError(f"{payload['type']}: {m.get('error')}")
                return m['result']


def recorder_events(base, token, fridge, ambient, start, end, tau):
    """Precise events from raw recorder history (same detection as the blueprint)."""
    def hist(entity):
        q = urllib.parse.urlencode({'filter_entity_id': entity,
                                    'end_time': end.isoformat(), 'no_attributes': '1'})
        out = []
        for chunk in rest(base, token,
                          f"/api/history/period/{urllib.parse.quote(start.isoformat())}?{q}"):
            for item in chunk:
                try:
                    v = float(item['state'])
                except (KeyError, TypeError, ValueError):
                    continue
                ts = item.get('last_changed') or item.get('last_updated')
                out.append((datetime.fromisoformat(ts.replace('Z', '+00:00')).timestamp(), v))
        return sorted(set(out))

    F, A = hist(fridge), hist(ambient)
    at = [p[0] for p in A]

    def room_at(t):
        i = bisect.bisect_left(at, t)
        lo = A[i - 1] if i > 0 else None
        hi = A[i] if i < len(A) else None
        if lo and hi and hi[0] > lo[0]:
            f = (t - lo[0]) / (hi[0] - lo[0])
            return lo[1] + f * (hi[1] - lo[1])
        pick = lo or hi
        return pick[1] if pick and abs(pick[0] - t) <= 21600 else None

    T = [p[0] for p in F]
    V = [p[1] for p in F]
    segs = [(i, (V[i + 1] - V[i]) / (T[i + 1] - T[i]) * 60.0, V[i + 1] - V[i], T[i + 1] - T[i])
            for i in range(len(F) - 1) if T[i + 1] > T[i]]
    events, j = [], 0
    while j < len(segs):
        i, sl, dv, dt = segs[j]
        if sl >= SLOPE_MIN and dv > 0:
            k = j
            while (k + 1 < len(segs) and segs[k + 1][0] == segs[k][0] + 1
                   and segs[k + 1][1] >= SLOPE_MIN and segs[k + 1][2] > 0):
                k += 1
            s_idx, e_idx = segs[j][0], segs[k][0] + 1
            t0v = V[s_idx]
            peak, peak_t = t0v, T[s_idx]
            for m in range(s_idx, len(F)):
                if T[m] - T[e_idx] > 10800 or (m > e_idx and V[m] <= t0v + 0.2):
                    break
                if V[m] > peak:
                    peak, peak_t = V[m], T[m]
            d_t = peak - t0v
            tr = room_at(T[s_idx])
            if d_t >= AMP_MIN and tr and tr - t0v > 2:
                ratio = d_t / (tr - t0v)
                if d_t >= WARMUP_DT or ratio >= WARMUP_RATIO:
                    # sustained warm-up (loading, searching, ajar): counted like the
                    # live blueprint — one opening with wall-clock duration
                    events.append((T[s_idx], max(peak_t - T[s_idx], 60.0)))
                elif 0 < ratio < RATIO_MAX:
                    events.append((T[s_idx], -tau * math.log(1 - ratio)))
            j = k + 1
        else:
            j += 1
    return events


async def lts_events(ws, fridge, ambient, start, end, tau, margin):
    """Coarse events from hourly long-term statistics (lower bound, <=1/hour)."""
    res = await ws.cmd({'type': 'recorder/statistics_during_period',
                        'start_time': start.isoformat(), 'end_time': end.isoformat(),
                        'statistic_ids': [fridge, ambient], 'period': 'hour',
                        'types': ['mean', 'min', 'max']})
    fr = res.get(fridge, [])
    amb = {r['start']: r.get('mean') for r in res.get(ambient, [])}
    rows = [(r['start'], r.get('min'), r.get('mean'), r.get('max')) for r in fr
            if r.get('min') is not None and r.get('max') is not None]
    if not rows:
        return []
    maxs = [r[3] for r in rows]
    amps = [r[3] - r[1] for r in rows]

    def rolling_median(vals, idx, half):
        lo, hi = max(0, idx - half), min(len(vals), idx + half + 1)
        w = sorted(vals[lo:hi])
        return w[len(w) // 2]

    flags = [False] * len(rows)
    work = maxs
    for _pass in range(2):  # two passes: detect, re-estimate ceiling without events
        for i, (ts, mn, me, mx) in enumerate(rows):
            flags[i] = mx > rolling_median(work, i, 36) + margin
        clean = sorted(m for m, f in zip(maxs, flags) if not f) or sorted(maxs)
        global_clean = clean[len(clean) // 2]
        work = [m if not f else global_clean for m, f in zip(maxs, flags)]
    band = sorted(a for a, f in zip(amps, flags) if not f)
    band_amp = band[len(band) // 2] if band else 1.3

    events = []
    episode = []
    def close_episode(ep):
        if not ep:
            return
        ts, mn, mx, tr = max(ep, key=lambda e: e[2])
        d_t = max(0.15, (mx - mn) - band_amp / 2)
        ratio = d_t / (tr - mn) if (tr is not None and tr - mn > 2) else None
        warm = (len(ep) >= 2 or d_t >= WARMUP_DT
                or (ratio is not None and ratio >= WARMUP_RATIO))
        if warm:
            # sustained warm-up: counted as one opening. Hourly data cannot
            # resolve the actual door-open span (elevated hours include the
            # recovery phase), so the duration is the capped tau estimate -
            # far closer to real accumulated open time than the episode span.
            r = min(ratio, 0.94) if ratio is not None else None
            dur = -tau * math.log(1 - r) if r and r > 0 else 600.0
            events.append((ep[0][0] / 1000, dur))
        elif ratio is not None and 0 < ratio < RATIO_MAX:
            events.append((ts / 1000, -tau * math.log(1 - ratio)))

    for i, (ts, mn, me, mx) in enumerate(rows):
        if flags[i]:
            episode.append((ts, mn, mx, amb.get(ts)))
        elif episode:
            close_episode(episode)
            episode = []
    close_episode(episode)
    return events


def build_rows(events, until):
    buck = defaultdict(list)
    for t, d in events:
        h = datetime.fromtimestamp(t, timezone.utc).replace(minute=0, second=0, microsecond=0)
        buck[h].append(d)
    cum_n, cum_s = 0, 0.0
    count_rows, secs_rows, dur_rows = [], [], []
    for h in sorted(buck):
        ds = buck[h]
        cum_n += len(ds)
        cum_s += sum(ds)
        count_rows.append({'start': h.isoformat(), 'state': cum_n, 'sum': cum_n})
        secs_rows.append({'start': h.isoformat(), 'state': round(cum_s), 'sum': round(cum_s)})
        dur_rows.append({'start': h.isoformat(), 'mean': round(sum(ds) / len(ds), 1),
                         'min': round(min(ds)), 'max': round(max(ds))})
    h = (max(buck) if buck else until) + timedelta(hours=1)
    last_full = until.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    while h <= last_full:
        count_rows.append({'start': h.isoformat(), 'state': cum_n, 'sum': cum_n})
        secs_rows.append({'start': h.isoformat(), 'state': round(cum_s), 'sum': round(cum_s)})
        h += timedelta(hours=1)
    return count_rows, secs_rows, dur_rows, cum_n, cum_s


async def amain():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--url', required=True)
    ap.add_argument('--token', default=os.environ.get('HASS_TOKEN'))
    ap.add_argument('--fridge-entity', required=True)
    ap.add_argument('--ambient-entity', required=True)
    ap.add_argument('--since', default=f'{datetime.now().year}-01-01')
    ap.add_argument('--tau', type=float, default=None,
                    help='time constant in s (default: read --tau-entity, fallback 1028)')
    ap.add_argument('--tau-entity', default='input_number.fridge_tau')
    ap.add_argument('--recorder-days', type=int, default=10)
    ap.add_argument('--ceiling-margin', type=float, default=CEIL_MARGIN)
    ap.add_argument('--openings-stat', default='sensor.kuhlschrank_tur_offnungen_gesamt')
    ap.add_argument('--seconds-stat', default='sensor.kuhlschrank_tur_offnungszeit_gesamt')
    ap.add_argument('--duration-stat', default='sensor.kuhlschrank_tur_letzte_offnungsdauer')
    ap.add_argument('--replace', action='store_true', help='clear target statistics first')
    ap.add_argument('--apply', action='store_true', help='import the statistics')
    ap.add_argument('--seed', action='store_true',
                    help='also set counter/total helpers and calibrate utility meters')
    args = ap.parse_args()
    if not args.token:
        sys.exit('no token: pass --token or set HASS_TOKEN')

    now = datetime.now(timezone.utc)
    since = datetime.fromisoformat(args.since).astimezone(timezone.utc)
    rec_start = now - timedelta(days=args.recorder_days)
    tau = args.tau
    if tau is None:
        try:
            tau = float(rest(args.url, args.token, f'/api/states/{args.tau_entity}')['state'])
        except Exception:
            tau = 1028.0
    print(f'tau = {tau:.0f} s | LTS window {since.date()} -> {rec_start.date()} | '
          f'recorder window {rec_start.date()} -> today')

    rec = recorder_events(args.url, args.token, args.fridge_entity, args.ambient_entity,
                          rec_start, now, tau)
    print(f'recorder branch: {len(rec)} precise events')

    async with Ws(args.url, args.token) as ws:
        lts = await lts_events(ws, args.fridge_entity, args.ambient_entity,
                               since, rec_start, tau, args.ceiling_margin)
        print(f'LTS branch: {len(lts)} coarse events (lower bound, <=1/hour)')
        events = sorted(lts + rec)
        count_rows, secs_rows, dur_rows, total_n, total_s = build_rows(events, now)

        monthly = defaultdict(lambda: [0, 0.0])
        for t, d in events:
            m = datetime.fromtimestamp(t, timezone.utc).astimezone().strftime('%Y-%m')
            monthly[m][0] += 1
            monthly[m][1] += d
        print('\nreconstructed monthly openings (from HA-native data only):')
        for m in sorted(monthly):
            print(f'  {m}: {monthly[m][0]:4d} openings, {monthly[m][1]:6.0f} s')
        print(f'  TOTAL: {total_n} openings, {total_s:.0f} s')

        if not args.apply:
            print('\ndry run — re-run with --apply (and optionally --replace/--seed) to import')
            return

        ids = [args.openings_stat, args.seconds_stat, args.duration_stat]
        if args.replace:
            await ws.cmd({'type': 'recorder/clear_statistics', 'statistic_ids': ids})
            print('cleared existing statistics')
        for sid, has_sum, unit, stats in [
                (args.openings_stat, True, None, count_rows),
                (args.seconds_stat, True, 's', secs_rows),
                (args.duration_stat, False, 's', dur_rows)]:
            await ws.cmd({'type': 'recorder/import_statistics',
                          'metadata': {'statistic_id': sid, 'source': 'recorder', 'name': None,
                                       'unit_of_measurement': unit,
                                       'has_mean': not has_sum, 'has_sum': has_sum},
                          'stats': stats})
            print(f'imported {len(stats)} rows -> {sid}')

        if args.seed:
            local_now = datetime.now().astimezone()
            def since_count(dt0):
                sel = [(t, d) for t, d in events
                       if datetime.fromtimestamp(t, timezone.utc).astimezone() >= dt0]
                return len(sel), round(sum(d for _, d in sel))
            today0 = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            week0 = today0 - timedelta(days=local_now.weekday())
            month0 = today0.replace(day=1)
            await ws.cmd({'type': 'call_service', 'domain': 'counter', 'service': 'set_value',
                          'service_data': {'entity_id': 'counter.fridge_openings_total',
                                           'value': total_n}})
            await ws.cmd({'type': 'call_service', 'domain': 'input_number', 'service': 'set_value',
                          'service_data': {'entity_id': 'input_number.fridge_open_seconds_total',
                                           'value': round(total_s)}})
            for ent, val in [('sensor.kuhlschrank_offnungen_heute', since_count(today0)[0]),
                             ('sensor.kuhlschrank_offnungen_woche', since_count(week0)[0]),
                             ('sensor.kuhlschrank_offnungen_monat', since_count(month0)[0]),
                             ('sensor.kuhlschrank_offnungszeit_heute', since_count(today0)[1]),
                             ('sensor.kuhlschrank_offnungszeit_monat', since_count(month0)[1])]:
                await ws.cmd({'type': 'call_service', 'domain': 'utility_meter',
                              'service': 'calibrate',
                              'service_data': {'entity_id': ent, 'value': str(val)}})
            if events:
                d_last = events[-1][1]
                # 900 s = the blueprint's default sustained_warmup wall-clock leg
                # (ajar_minutes = 15 min); keep in sync if that default changes.
                cls = ('sustained_warmup' if d_last >= 900 else
                       'quick_grab' if d_last < 40 else
                       'normal_grab' if d_last <= 90 else 'extended_open')
                await ws.cmd({'type': 'call_service', 'domain': 'input_number',
                              'service': 'set_value',
                              'service_data': {'entity_id': 'input_number.fridge_last_open_duration',
                                               'value': round(d_last)}})
                await ws.cmd({'type': 'call_service', 'domain': 'input_text',
                              'service': 'set_value',
                              'service_data': {'entity_id': 'input_text.fridge_last_event_class',
                                               'value': cls}})
            print(f'seeded helpers (total {total_n} / {total_s:.0f} s), calibrated meters, '
                  'set last-event class/duration')


if __name__ == '__main__':
    asyncio.run(amain())
