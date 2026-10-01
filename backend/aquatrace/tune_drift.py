"""Drift-forecast tuning with a held-out month.

Settings are chosen on buoys released in January 2025 and scored once on February 2025 buoys,
so the reported February numbers are not tuned on the data they are measured on.

Two things are tuned:
  1. position accuracy - windage (wind drag) and a current scale factor, by median error;
  2. cone reliability  - per-particle current error, eddy diffusivity K and windage spread, so that the 90 % cone
     drawn on the map really contains the buoy ~90 % of the time (it is too narrow otherwise).

    python -m aquatrace.tune_drift          # writes outputs/drift_tuning.json
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta

import numpy as np
from shapely.geometry import Point, Polygon

from .config import OUTPUTS
from .drift import Seed, simulate
from .forcing import VelocityField
from .pipeline import load_forcing
from .sources.coast import haversine_km
from .validate import cases, load_drifters

log = logging.getLogger("aquatrace")
START, SPLIT, END = date(2025, 1, 1), date(2025, 2, 1), date(2025, 2, 24)


def scaled(f: VelocityField, s: float) -> VelocityField:
    return f if s == 1.0 else VelocityField(f.name, f.source, f.time, f.lat, f.lon, f.u * s, f.v * s)


def _area_km2(hull):
    lat = np.array([p[0] for p in hull]); lon = np.array([p[1] for p in hull])
    x = lon * 111.32 * np.cos(np.deg2rad(lat.mean())); y = lat * 111.32
    return float(abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))) / 2)


def score(groups, currents, wind, windage, K, cscale=1.0, sigma=0.0, n=100):
    """Errors of the ensemble mean, and whether the truth fell inside the 90 % cone, per case."""
    cur = scaled(currents, cscale)
    rows = []
    for t0, group in groups:
        seeds = [Seed(c[1], c[2], c[3], 0.5) for c in group]
        fc = simulate(seeds, t0, cur, wind, n=n, windage=windage, diffusivity=K, current_sigma=sigma,
                      keep_particles=0, frame_every=1000)
        for c, f in zip(group, fc):
            r = {}
            for h, (tl, tn) in ((24, (c[4], c[5])), (48, (c[6], c[7]))):
                hz = f["horizons"][str(h)]
                r[f"err{h}"] = haversine_km(hz["mean"][0], hz["mean"][1], tl, tn)
                poly = Polygon([(p[1], p[0]) for p in hz["hull"]])
                r[f"in{h}"] = bool(poly.buffer(0).contains(Point(tn, tl)))
                r[f"area{h}"] = _area_km2(hz["hull"])
            rows.append(r)
    return summarize(rows)


def summarize(rows):
    out = {"n": len(rows)}
    for h in (24, 48):
        e = np.array([r[f"err{h}"] for r in rows])
        out[str(h)] = {"median_km": round(float(np.median(e)), 2), "p90_km": round(float(np.percentile(e, 90)), 1),
                       "cone90_coverage": round(float(np.mean([r[f"in{h}"] for r in rows])), 3),
                       "cone_area_km2": round(float(np.median([r[f"area{h}"] for r in rows])), 0)}
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    df = load_drifters()
    cs = cases(df, START, END)
    by_t0 = {}
    for c in cs:
        by_t0.setdefault(c[0], []).append(c)
    cal = [(t, g) for t, g in sorted(by_t0.items()) if t.date() < SPLIT]
    hold = [(t, g) for t, g in sorted(by_t0.items()) if t.date() >= SPLIT]
    log.info("calibration %d cases, held-out %d cases", sum(map(len, (g for _, g in cal))), sum(map(len, (g for _, g in hold))))
    currents = load_forcing("currents", START, END + timedelta(days=1))
    wind = load_forcing("wind", START, END + timedelta(days=1))
    res = {"calibration_window": [START.isoformat(), (SPLIT - timedelta(days=1)).isoformat()],
           "holdout_window": [SPLIT.isoformat(), END.isoformat()],
           "forcing": {"currents": currents.source, "wind": wind.source}, "stage1": [], "stage2": []}

    def run(stage, groups, **kw):
        t = time.time()
        s = score(groups, currents, wind, **kw)
        row = {**{k: v for k, v in kw.items() if k != "n"}, **s}
        row["windage"] = list(row["windage"])
        res[stage].append(row)
        log.info("%s %s K=%s sd=%s  24h %.1f km cov %.2f | 48h %.1f km cov %.2f area %d  (%.0fs)", stage, kw.get("windage"), kw.get("K"), kw.get("sigma"), s["24"]["median_km"],
                 s["24"]["cone90_coverage"], s["48"]["median_km"], s["48"]["cone90_coverage"], s["48"]["cone_area_km2"], time.time() - t)
        return row

    # baseline = current production settings, on both months
    base = dict(windage=(0.01, 0.03), K=20.0, cscale=1.0, sigma=0.0)
    res["baseline_calibration"] = run("stage1", cal, **base, n=100)
    res["baseline_holdout"] = score(hold, currents, wind, **base)

    # stage 1: position accuracy (mean track) - windage centre x current scale, small fixed spread
    for cs_ in (0.8, 1.0, 1.2, 1.4):
        for a in (0.01, 0.015, 0.02, 0.025, 0.03):
            run("stage1", cal, windage=(a, a), K=20.0, cscale=cs_, n=24)
    best1 = min(res["stage1"][1:], key=lambda r: r["48"]["median_km"] + r["24"]["median_km"])
    a0, cs0 = best1["windage"][0], best1["cscale"]
    log.info("stage 1 best: windage %.3f, current scale %.1f", a0, cs0)

    # stage 2: cone reliability around the chosen centre. Diffusion alone (sigma = 0) spreads ~sqrt(t)
    # and cannot fit 24 h and 48 h at once; a constant per-particle current error spreads ~t.
    wnd = (round(a0 - 0.005, 4), round(a0 + 0.005, 4))
    for K in (1000.0, 2000.0):
        run("stage2", cal, windage=wnd, K=K, cscale=cs0, sigma=0.0, n=150)
    for sigma in (0.06, 0.08, 0.10, 0.12, 0.14, 0.16):
        for K in (20.0, 200.0):
            run("stage2", cal, windage=wnd, K=K, cscale=cs0, sigma=sigma, n=150)
    # closest to 90 % coverage at both horizons (a cone that is too wide is penalised as much as too narrow)
    best2 = min(res["stage2"], key=lambda r: abs(r["24"]["cone90_coverage"] - 0.9) + abs(r["48"]["cone90_coverage"] - 0.9))
    chosen = dict(windage=tuple(best2["windage"]), K=best2["K"], cscale=best2["cscale"], sigma=best2["sigma"])
    log.info("chosen %s", chosen)

    # score the chosen settings once on the held-out month
    res["chosen"] = {**chosen, "windage": list(chosen["windage"])}
    res["chosen_calibration"] = {k: best2[k] for k in ("n", "24", "48")}
    res["chosen_holdout"] = score(hold, currents, wind, **chosen, n=150)
    res["created"] = datetime.now().isoformat(timespec="seconds")
    (OUTPUTS / "drift_tuning.json").write_text(json.dumps(res, indent=2))
    print(json.dumps({k: res[k] for k in ("chosen", "baseline_holdout", "chosen_holdout")}, indent=2))


if __name__ == "__main__":
    main()
