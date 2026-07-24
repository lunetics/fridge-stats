#!/usr/bin/env python3
"""Generate a synthetic fridge temperature series for the documentation figures.

Deterministic (fixed seed), carries NO real household data or wall-clock timing —
it starts at an arbitrary fixed epoch. Reproduces every phenomenon the detector
has to handle:

  * a normal compressor sawtooth (slow warm ramp, fast cool drop) that must NOT
    trigger,
  * short "grab" openings (fast rise, quick recovery) -> counted,
  * one long door-open that reaches ~14 °C -> counted, ajar warning,
  * two compressor-off-drift phantoms (a steeper off-ramp that trips the rate
    but stays in the sawtooth band) -> discarded as compressor_cycle,
  * a quantization blip -> discarded.

Writes ts,fridge,ambient CSV. Feed it to plot_diagnostics.py --from-csv to build
the shipped demo figures without exposing any real installation.
"""
import argparse
import csv
import numpy as np

DT = 30                      # sample spacing (s)
DAYS = 3
EPOCH = 1_750_000_000        # arbitrary fixed start; NOT a real date
FLOOR, CEIL = 5.0, 7.3       # normal compressor band (°C)
WARM = (CEIL - FLOOR) / (27 * 60)   # slow warm ramp (°C/s)  ~0.085 °C/min
COOL = (CEIL - FLOOR) / (8 * 60)    # fast cool drop (°C/s)


def build():
    rng = np.random.default_rng(42)
    n = DAYS * 86400 // DT
    ep = EPOCH + np.arange(n) * DT
    fv = np.empty(n)

    # baseline compressor sawtooth
    t, warming = FLOOR + 1.0, True
    for i in range(n):
        fv[i] = t
        if warming:
            t += WARM * DT + rng.normal(0, 0.003)
            if t >= CEIL + rng.normal(0, 0.05):
                warming = False
        else:
            t -= COOL * DT
            if t <= FLOOR + rng.normal(0, 0.05):
                warming = True

    idx = lambda hours: int(hours * 3600 / DT)

    def relax_open(start_h, dur_min, target, tau_min=17):
        """Overwrite a window with a door-open excursion: relax toward `target`,
        then recover back to the sawtooth afterwards."""
        s = idx(start_h)
        d = int(dur_min * 60 / DT)
        base = fv[s]
        tau = tau_min * 60
        for k in range(d):
            fv[s + k] = base + (target - base) * (1 - np.exp(-(k * DT) / tau))
        # recovery: ease back to the ongoing sawtooth over ~15 min
        rec = idx(0) + int(15 * 60 / DT)
        peak = fv[s + d - 1]
        for k in range(min(rec, n - (s + d))):
            w = np.exp(-(k * DT) / (10 * 60))
            fv[s + d + k] = fv[s + d + k] * (1 - w) + (peak - (peak - fv[s + d + k]) ) * 0  # keep sawtooth
            fv[s + d + k] = fv[s + d + k] + (peak - fv[s + d + k]) * w * 0.6

    def phantom(start_h, dur_min):
        """A compressor-off drift that self-triggers: a small step, then a slow
        rise that stays within the band (peak < ajar_warn_temp)."""
        s = idx(start_h)
        d = int(dur_min * 60 / DT)
        fv[s] = fv[s - 1] + 0.22               # the single step that trips the rate
        top = min(CEIL + 0.6, 7.9)
        for k in range(1, d):
            fv[s + k] = fv[s] + (top - fv[s]) * (1 - np.exp(-(k * DT) / (25 * 60)))
        fv[s + d] = fv[s + d - 1] - 0.4        # compressor kicks in -> close

    def grab(start_h, rise, dur_min):
        s = idx(start_h)
        d = int(dur_min * 60 / DT)
        base = fv[s - 1]
        for k in range(d):
            frac = min(1.0, k / 3.0)           # ~90 s rise
            decay = np.exp(-(k * DT) / (4 * 60))
            fv[s + k] = base + rise * frac * decay + WARM * DT * k * 0.3

    def blip(start_h):
        s = idx(start_h)
        fv[s] = fv[s - 1] + 0.22               # one-sample quantization spike

    # scripted events across the 3 days
    grab(6.2, 1.2, 4)          # morning grab
    grab(12.6, 1.6, 5)         # lunch grab
    phantom(15.3, 30)          # afternoon compressor phantom
    blip(17.8)                 # quantization blip
    relax_open(20.9, 42, 14.5) # evening: long real opening -> ajar
    grab(31.0, 1.0, 3)
    phantom(37.2, 33)          # next-day compressor phantom
    grab(42.5, 1.4, 4)
    relax_open(45.0, 8, 9.5)   # short-ish real open, moderate warmth
    blip(52.1)

    # quantize to 0.01 °C (Aqara-class) + faint noise
    fv = np.round(fv + rng.normal(0, 0.01, n), 2)
    amb = np.round(22.0 + 1.5 * np.sin(np.arange(n) / n * 2 * np.pi * DAYS) + rng.normal(0, 0.05, n), 2)
    return ep, fv, amb


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="demo_fridge.csv")
    args = ap.parse_args()
    ep, fv, amb = build()
    with open(args.out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ts", "fridge", "ambient"])
        for a, b, c in zip(ep, fv, amb):
            w.writerow([int(a), b, c])
    print(f"wrote {args.out}  ({len(fv)} rows, {DAYS} days @ {DT}s, synthetic)")


if __name__ == "__main__":
    main()
