#!/usr/bin/env python3
"""Diagnostic plots for a fridge-stats installation.

Renders the figures that explain the detector on YOUR data:

  overview   raw interior temp + ambient + rolling compressor ceiling, with the
             reconstructed open episodes shaded by class (real / compressor-cycle
             phantom / blip)
  zoom       a close-up of the worst compressor-cycle phantom (if any): the
             interior stays in the sawtooth band while a long "open" was booked
  equalized  the sawtooth "equalized away" — interior minus the rolling ceiling,
             so real openings stand out over a flat line
  adaptive   the adaptive rolling-ceiling detector (causal): "open" when the
             interior rises MARGIN above its self-estimated normal ceiling

The detector is re-simulated from the temperature series using the same rules as
the blueprint (rate open, fall_confirm close, rise_amp_min blip, ajar_warn_temp
warmth gate + compressor_cycle discard), so the plots are self-contained and do
not need the live helpers.

Data source — either:
  REST : --url http://homeassistant:8123 --token <long-lived> \
         --fridge sensor.fridge_temperature --ambient sensor.room_temperature
         (or env HA_URL / HA_TOKEN); read-only /api/history/period, --days back.
  CSV  : --from-csv data.csv  with columns  ts,fridge[,ambient]
         (ts = unix seconds or ISO8601). Used for the shipped demo figures.

Read-only. Never writes to Home Assistant. Requires matplotlib + numpy (+ requests
for the REST path).
"""
import argparse
import csv
import math
import os
import sys
import urllib.parse
from datetime import datetime, timezone, timedelta

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# --------------------------------------------------------------------------- #
# data loading
# --------------------------------------------------------------------------- #
def _parse_ts(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def load_csv(path):
    ep, fr, am = [], [], []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            ep.append(_parse_ts(row["ts"]))
            fr.append(float(row["fridge"]))
            am.append(float(row["ambient"]) if row.get("ambient") not in (None, "") else np.nan)
    order = np.argsort(ep)
    ep, fr, am = np.array(ep)[order], np.array(fr)[order], np.array(am)[order]
    return ep, fr, am


def load_rest(url, token, fridge, ambient, days):
    import requests
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    ents = fridge + ("," + ambient if ambient else "")
    q = {"filter_entity_id": ents, "end_time": end.isoformat(), "minimal_response": "true"}
    u = f"{url.rstrip('/')}/api/history/period/{start.isoformat()}?{urllib.parse.urlencode(q)}"
    r = requests.get(u, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    by = {}
    for arr in r.json():
        if arr:
            by[arr[0]["entity_id"]] = arr

    def series(rows):
        ep, va = [], []
        for it in rows or []:
            st = it.get("state")
            if st in (None, "", "unknown", "unavailable"):
                continue
            try:
                v = float(st)
            except ValueError:
                continue
            ep.append(_parse_ts(it.get("last_changed") or it["last_updated"]))
            va.append(v)
        return np.array(ep), np.array(va)

    fe, fv = series(by.get(fridge))
    ae, av = series(by.get(ambient)) if ambient else (np.array([]), np.array([]))
    am = np.interp(fe, ae, av) if len(ae) else np.full_like(fe, np.nan)
    return fe, fv, am


# --------------------------------------------------------------------------- #
# detector re-simulation (mirrors the blueprint state machine)
# --------------------------------------------------------------------------- #
class P:  # detection parameters (blueprint defaults)
    rise_rate_min = 0.13
    dv_floor = 0.15
    rise_amp_min = 0.30
    fall_confirm = 0.05
    ajar_minutes = 15
    ajar_warn_temp = 8.0
    tau = 1028.0


def simulate(ep, fv, am, p):
    """Return a list of episode dicts with class + geometry, mirroring the
    blueprint's open/close/blip/compressor_cycle/ajar logic."""
    eps = []
    door = False
    t0 = opened_ts = troom0 = None
    for i in range(1, len(fv)):
        dv = fv[i] - fv[i - 1]
        dt = max(ep[i] - ep[i - 1], 1.0)
        rate = dv / dt * 60.0
        if not door:
            if dv >= p.dv_floor and rate >= p.rise_rate_min:
                door, t0, opened_ts = True, fv[i - 1], ep[i - 1]
                troom0 = am[i] if not math.isnan(am[i]) else 21.0
        else:
            if fv[i] < fv[i - 1] - p.fall_confirm:
                peak = fv[i - 1]
                d_t = peak - t0
                wall_s = ep[i] - opened_ts
                # ajar fired? interior >= warm gate at the ajar mark, if reached
                ajar = False
                if wall_s >= p.ajar_minutes * 60:
                    j = np.searchsorted(ep, opened_ts + p.ajar_minutes * 60)
                    j = min(max(j, 0), len(fv) - 1)
                    ajar = fv[j] >= p.ajar_warn_temp
                if d_t < p.rise_amp_min:
                    cls = "blip"
                elif wall_s >= p.ajar_minutes * 60 and peak < p.ajar_warn_temp:
                    cls = "compressor_cycle"
                else:
                    drive = troom0 - t0
                    ratio = d_t / drive if drive > 2 else 0
                    sustained = wall_s >= p.ajar_minutes * 60 or d_t >= 2.5
                    if sustained:
                        dur = wall_s
                    elif 0 < ratio < 0.95:
                        dur = -p.tau * math.log(1 - ratio)
                    else:
                        dur = 0
                    cls = ("sustained_warmup" if sustained else
                           "quick_grab" if dur < 40 else
                           "normal_grab" if dur <= 90 else "extended_open")
                eps.append(dict(start=opened_ts, end=ep[i], t0=t0, peak=peak,
                                d_t=d_t, wall_s=wall_s, cls=cls, ajar=ajar))
                door = False
    return eps


CLASS_GROUP = {  # -> (colour, label, is-counted)
    "blip": ("#9467bd", "blip", False),
    "compressor_cycle": ("#d62728", "compressor cycle (phantom)", False),
}
REAL_CLASSES = {"quick_grab", "normal_grab", "extended_open", "sustained_warmup"}


def trailing_q(ep, val, win_s, q):
    """causal trailing-window percentile (past-only), for the adaptive ceiling."""
    out = np.empty_like(val)
    lo = np.searchsorted(ep, ep - win_s, side="left")
    for i in range(len(val)):
        seg = val[lo[i]:i + 1]
        out[i] = np.percentile(seg, q) if len(seg) else val[i]
    return out


def ewma_time(ep, val, tau_s):
    out = np.empty_like(val)
    out[0] = val[0]
    for k in range(1, len(val)):
        a = 1.0 - math.exp(-(ep[k] - ep[k - 1]) / tau_s)
        out[k] = out[k - 1] + a * (val[k] - out[k - 1])
    return out


# --------------------------------------------------------------------------- #
# plotting helpers
# --------------------------------------------------------------------------- #
def _axis(ax, ep, t0, span_h, step_h=6):
    ax.set_xlim(0, span_h)
    tk = np.arange(0, span_h + 0.1, step_h)
    ax.set_xticks(tk)
    ax.set_xticklabels(
        [datetime.fromtimestamp(t0 + t * 3600).strftime("%d.%m\n%H:%M") for t in tk],
        fontsize=8)


def _shade(ax, eps, t0, H):
    seen = set()
    for e in eps:
        col, lab, _ = CLASS_GROUP.get(
            e["cls"], ("#2ca02c", "real opening", True))
        ax.axvspan(H(e["start"]), H(e["end"]), color=col, alpha=.16,
                   label=lab if lab not in seen else None)
        seen.add(lab)


def make_figures(ep, fv, am, p, out, prefix="fridge"):
    eps = simulate(ep, fv, am, p)
    ceil = trailing_q(ep, fv, 3 * 3600, 85)
    base = trailing_q(ep, fv, 40 * 60, 50)
    fv_s = ewma_time(ep, fv, 90.0)
    excess = fv - ceil

    t0 = eps[0]["start"] - 3600 if eps else ep[0]
    t1 = ep[-1]
    m = (ep >= t0) & (ep <= t1)
    H = lambda x: (np.asarray(x) - t0) / 3600.0
    span = (t1 - t0) / 3600.0
    written = []

    def save(fig, name):
        path = os.path.join(out, f"{prefix}_{name}.png")
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        written.append(path)

    # ---- overview ----
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(15, 9), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1.3]})
    a1.plot(H(ep[m]), fv[m], color="#1f77b4", lw=1.0, label="interior temp")
    a1.plot(H(ep[m]), fv_s[m], color="#ff7f0e", lw=1.4, alpha=.8, label="EWMA smoothed")
    if not np.isnan(am[m]).all():
        a1.plot(H(ep[m]), am[m], color="#7f7f7f", lw=1.0, ls="--", alpha=.6, label="ambient")
    _shade(a1, eps, t0, H)
    a1.set_ylabel("°C")
    a1.set_title("fridge-stats — detected openings over the interior temperature")
    a1.legend(loc="upper left", ncol=2, fontsize=8)
    a1.grid(alpha=.25)
    dvv = np.diff(fv) / np.maximum(np.diff(ep), 1) * 60
    rmid = (ep[:-1] + ep[1:]) / 2
    mr = (rmid >= t0) & (rmid <= t1)
    a2.axhline(p.rise_rate_min, color="#d62728", lw=1.3,
               label=f"rise_rate_min = {p.rise_rate_min} °C/min")
    a2.axhline(0, color="k", lw=.5, alpha=.4)
    a2.plot(H(rmid[mr]), dvv[mr], color="#1f77b4", lw=.7, alpha=.6, label="rate dv/dt")
    a2.set_ylabel("°C/min")
    a2.set_ylim(-1.2, min(3.0, float(dvv.max()) * 1.05) if len(dvv) else 3.0)
    a2.legend(loc="upper left", fontsize=8)
    a2.grid(alpha=.25)
    _axis(a2, ep, t0, span)
    save(fig, "overview")

    # ---- equalized ----
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(15, 8), sharex=True,
                                 gridspec_kw={"height_ratios": [1.5, 1.5]})
    a1.plot(H(ep[m]), fv[m], color="#1f77b4", lw=1.0, label="interior temp")
    a1.plot(H(ep[m]), ceil[m], color="#ff7f0e", lw=1.6, label="rolling compressor ceiling (p85, 3 h)")
    _shade(a1, eps, t0, H)
    a1.set_ylabel("°C")
    a1.set_title("Equalizing the compressor sawtooth: the rolling ceiling that is subtracted")
    a1.legend(loc="upper left", ncol=2, fontsize=8)
    a1.grid(alpha=.25)
    a2.axhline(0, color="#d62728", lw=1.2, label="ceiling = 0")
    a2.fill_between(H(ep[m]), 0, np.clip(excess[m], 0, None), color="#2ca02c", alpha=.5,
                    label="excess over ceiling = real opening")
    a2.plot(H(ep[m]), excess[m], color="#1f77b4", lw=1.0)
    _shade(a2, eps, t0, H)
    a2.set_ylabel("T − ceiling (°C)")
    a2.set_title("Equalized: sawtooth flat ≤ 0 — only real openings rise; phantoms stay in the band")
    a2.legend(loc="upper left", ncol=3, fontsize=8)
    a2.grid(alpha=.25)
    _axis(a2, ep, t0, span)
    save(fig, "equalized")

    # ---- adaptive detector ----
    margin = 0.6
    detect = ceil + margin
    fires = fv > detect
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(15, 8), sharex=True,
                                 gridspec_kw={"height_ratios": [2, 1.3]})
    a1.plot(H(ep[m]), fv[m], color="#1f77b4", lw=1.0, label="interior temp")
    a1.plot(H(ep[m]), ceil[m], color="#ff7f0e", lw=1.6, label="adaptive ceiling (trailing p85, 3 h)")
    a1.plot(H(ep[m]), detect[m], color="#d62728", lw=1.1, ls="--", label=f"trigger = ceiling + {margin} °C")
    mm = m & fires
    a1.scatter(H(ep[mm]), fv[mm], s=14, color="#d62728", zorder=5, label="detector fires")
    _shade(a1, eps, t0, H)
    a1.set_ylabel("°C")
    a1.set_title("Adaptive rolling-ceiling detector (causal): open = interior above its self-estimated ceiling")
    a1.legend(loc="upper left", ncol=2, fontsize=8)
    a1.grid(alpha=.25)
    a2.axhline(0, color="k", lw=.5, alpha=.4)
    a2.axhline(margin, color="#d62728", lw=1.2, ls="--", label=f"trigger +{margin} °C")
    a2.plot(H(ep[m]), excess[m], color="#1f77b4", lw=1.0)
    _shade(a2, eps, t0, H)
    a2.set_ylabel("T − ceiling (°C)")
    a2.set_title("Distance to the adaptive ceiling: phantoms stay under the margin, real openings break through")
    a2.legend(loc="upper left", ncol=2, fontsize=8)
    a2.grid(alpha=.25)
    _axis(a2, ep, t0, span)
    save(fig, "adaptive_ceiling")

    # ---- zoom on worst compressor-cycle phantom (if any) ----
    phantoms = [e for e in eps if e["cls"] == "compressor_cycle"]
    if phantoms:
        e = max(phantoms, key=lambda x: x["wall_s"])
        a, b = e["start"], e["end"]
        pad = 900
        z = (ep >= a - pad) & (ep <= b + pad)
        Z = lambda x: (np.asarray(x) - (a - pad)) / 60.0
        fig, ax = plt.subplots(figsize=(13, 5.5))
        ax.plot(Z(ep[z]), fv[z], color="#1f77b4", lw=1.3, marker=".", ms=4, label="interior (reports)")
        ax.plot(Z(ep[z]), ceil[z], color="#ff7f0e", lw=1.6, label="rolling ceiling")
        ax.axhline(p.ajar_warn_temp, color="#d62728", lw=1.1, ls="--", label=f"ajar_warn_temp = {p.ajar_warn_temp} °C")
        ax.axvspan(Z(a), Z(b), color="#d62728", alpha=.15, label="booked 'open' (discarded as compressor_cycle)")
        ax.set_xlabel("minutes")
        ax.set_ylabel("°C")
        ax.set_title(f"Compressor-cycle phantom: {e['wall_s']/60:.0f} min 'open', peak {e['peak']:.1f} °C — never real")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=.25)
        save(fig, "zoom_phantom")

    # summary
    counts = {}
    for e in eps:
        g = "real" if e["cls"] in REAL_CLASSES else e["cls"]
        counts[g] = counts.get(g, 0) + 1
    ajar_real = sum(1 for e in eps if e["ajar"])
    print(f"episodes: {counts}  |  ajar warnings that would fire: {ajar_real}")
    return written


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-csv", help="read ts,fridge[,ambient] from CSV instead of REST")
    ap.add_argument("--url", default=os.environ.get("HA_URL"))
    ap.add_argument("--token", default=os.environ.get("HA_TOKEN"))
    ap.add_argument("--fridge", help="fridge interior temperature entity_id")
    ap.add_argument("--ambient", default="", help="ambient temperature entity_id (optional)")
    ap.add_argument("--days", type=float, default=10)
    ap.add_argument("--out", default=".", help="output directory for PNGs")
    ap.add_argument("--prefix", default="fridge")
    ap.add_argument("--rise-rate-min", type=float, default=P.rise_rate_min)
    ap.add_argument("--ajar-warn-temp", type=float, default=P.ajar_warn_temp)
    ap.add_argument("--tau", type=float, default=P.tau)
    args = ap.parse_args()

    if args.from_csv:
        ep, fv, am = load_csv(args.from_csv)
    else:
        if not (args.url and args.token and args.fridge):
            ap.error("REST mode needs --url, --token and --fridge (or --from-csv)")
        ep, fv, am = load_rest(args.url, args.token, args.fridge, args.ambient, args.days)
    if len(fv) < 10:
        sys.exit("not enough data points")

    p = P()
    p.rise_rate_min, p.ajar_warn_temp, p.tau = args.rise_rate_min, args.ajar_warn_temp, args.tau
    os.makedirs(args.out, exist_ok=True)
    for path in make_figures(ep, fv, am, p, args.out, args.prefix):
        print("wrote", path)


if __name__ == "__main__":
    main()
