"""Drift-forecast validation against real floating buoys (NOAA Global Drifter Program).

For every drifter and every day at 00 UTC we release a particle ensemble at the buoy's true
position, forecast 24 h and 48 h ahead, and measure the distance (km) to where the buoy really
went, and whether the buoy fell inside the 90 % cone drawn on the map. Two references are reported:
  * persistence baseline - "the debris stays where it was seen" (what a snapshot implies)
  * currents-only model  - same model without the wind term

    python -m aquatrace.validate --holdout     # Feb 2025 buoys; drift settings were tuned on January
    python -m aquatrace.validate --start 2025-02-15 --end 2025-03-01
"""
from __future__ import annotations

import argparse
import io
import json
import logging
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from shapely.geometry import Point, Polygon

from .config import CURRENT_SIGMA, DIFFUSIVITY, OUTPUTS, RAW, WINDAGE_RANGE
from .drift import Seed, simulate
from .pipeline import load_forcing
from .sources.coast import haversine_km

log = logging.getLogger("aquatrace")
DRIFTERS = RAW / "drifters" / "gdp_6h_bob_2025H1.csv"
TUNING_WINDOW = (date(2025, 1, 1), date(2025, 1, 31))     # tune_drift.py calibration month
HOLDOUT_WINDOW = (date(2025, 2, 1), date(2025, 2, 24))    # scored once with the chosen settings
FORCING_WINDOW = (date(2025, 1, 1), date(2025, 2, 25))    # cached NASA forcing covering both


def load_drifters(path=DRIFTERS) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(path.read_text()), skiprows=[1])
    df["time"] = pd.to_datetime(df["time"]).dt.tz_localize(None)
    df["drogue_lost_date"] = pd.to_datetime(df["drogue_lost_date"], errors="coerce").dt.tz_localize(None)
    return df.dropna(subset=["latitude", "longitude"]).sort_values(["ID", "time"])


def cases(df: pd.DataFrame, start: date, end: date):
    """(t0, id, lat0, lon0, lat24, lon24, lat48, lon48, drogued) for each buoy-day with a full 48 h track."""
    out = []
    for bid, g in df.groupby("ID"):
        s = g.set_index("time")
        for t0 in pd.date_range(start, end - timedelta(days=2), freq="24h"):
            t24, t48 = t0 + pd.Timedelta(hours=24), t0 + pd.Timedelta(hours=48)
            if t0 in s.index and t24 in s.index and t48 in s.index:
                dl = s["drogue_lost_date"].iloc[0]
                out.append((t0.to_pydatetime(), str(bid), s.at[t0, "latitude"], s.at[t0, "longitude"],
                            s.at[t24, "latitude"], s.at[t24, "longitude"], s.at[t48, "latitude"], s.at[t48, "longitude"],
                            bool(pd.isna(dl) or dl > t48)))
    return out


def _stats(err):
    err = np.asarray(err, float)
    return {"median_km": round(float(np.median(err)), 1), "mean_km": round(float(np.mean(err)), 1),
            "p90_km": round(float(np.percentile(err, 90)), 1), "n": int(err.size)}


def _inside(hull, lat, lon) -> bool:
    return bool(Polygon([(p[1], p[0]) for p in hull]).buffer(0).contains(Point(lon, lat)))


def run(start: date, end: date, forcing: tuple[date, date] | None = None) -> dict:
    df = load_drifters()
    cs = cases(df, start, end)
    if not cs:
        raise RuntimeError("No drifter cases in the window")
    log.info("%d buoy-day cases from %d drifters", len(cs), len({c[1] for c in cs}))
    fs, fe = forcing or (start, end + timedelta(days=1))
    currents = load_forcing("currents", fs, fe)
    wind = load_forcing("wind", fs, fe)
    inside = {24: [], 48: []}

    err = {"model": {24: [], 48: []}, "currents_only": {24: [], 48: []}, "persistence": {24: [], 48: []}}
    drog = []
    examples = []
    by_t0 = {}
    for c in cs:
        by_t0.setdefault(c[0], []).append(c)
    for t0, group in sorted(by_t0.items()):
        seeds = [Seed(f"{c[1]}", c[2], c[3], 0.5) for c in group]
        full = simulate(seeds, t0, currents, wind, n=100, keep_particles=0, frame_every=1000)
        cur = simulate(seeds, t0, currents, wind, n=100, windage=(0.0, 0.0), keep_particles=0, frame_every=1000)
        for c, f, g in zip(group, full, cur):
            for h, (tl, tn) in ((24, (c[4], c[5])), (48, (c[6], c[7]))):
                m = f["horizons"][str(h)]["mean"]; mc = g["horizons"][str(h)]["mean"]
                err["model"][h].append(haversine_km(m[0], m[1], tl, tn))
                err["currents_only"][h].append(haversine_km(mc[0], mc[1], tl, tn))
                err["persistence"][h].append(haversine_km(c[2], c[3], tl, tn))
                inside[h].append(_inside(f["horizons"][str(h)]["hull"], tl, tn))
            drog.append(c[8])
            if len(examples) < 12:
                examples.append({"id": c[1], "t0": t0.isoformat(), "truth": [[c[2], c[3]], [c[4], c[5]], [c[6], c[7]]],
                                 "forecast": [r[1:] for r in f["central_track"]]})
    drog = np.array(drog)
    summary = {str(h): {**_stats(err["model"][h]), "cone90_coverage": round(float(np.mean(inside[h])), 3)}
               for h in (24, 48)}
    result = {
        "window": [start.isoformat(), end.isoformat()],
        "settings": {"windage": list(WINDAGE_RANGE), "diffusivity_m2s": DIFFUSIVITY, "current_sigma_ms": CURRENT_SIGMA},
        "tuned_on": [d.isoformat() for d in TUNING_WINDOW],
        "held_out": start > TUNING_WINDOW[1],
        "drifters": len({c[1] for c in cs}), "cases": len(cs),
        "forcing": {"currents": currents.source, "wind": wind.source},
        "summary": summary,
        "currents_only": {str(h): _stats(err["currents_only"][h]) for h in (24, 48)},
        "persistence": {str(h): _stats(err["persistence"][h]) for h in (24, 48)},
        "skill_vs_persistence": {str(h): round(1 - np.median(err["model"][h]) / np.median(err["persistence"][h]), 3)
                                 for h in (24, 48)},
        "by_drogue": {k: {str(h): _stats(np.asarray(err["model"][h])[mask]) for h in (24, 48)}
                      for k, mask in (("drogued", drog), ("undrogued", ~drog)) if mask.any()},
        "examples": examples,
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    (OUTPUTS / "drift_validation.json").write_text(json.dumps(result, indent=2, default=float))
    return result


def calibrate_windage(start: date, end: date, values=(0.0, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04)) -> dict:
    """Pick the wind-drag factor that best explains real buoy tracks (undrogued buoys float at the
    surface like debris, so they are the closest available proxy)."""
    df = load_drifters()
    cs = cases(df, start, end)
    currents = load_forcing("currents", start, end + timedelta(days=1))
    wind = load_forcing("wind", start, end + timedelta(days=1))
    by_t0 = {}
    for c in cs:
        by_t0.setdefault(c[0], []).append(c)
    rows = []
    for a in values:
        e24, e48 = [], []
        for t0, group in sorted(by_t0.items()):
            seeds = [Seed(c[1], c[2], c[3], 0.5) for c in group]
            fc = simulate(seeds, t0, currents, wind, n=60, windage=(a, a), keep_particles=0, frame_every=1000)
            for c, f in zip(group, fc):
                m24, m48 = f["horizons"]["24"]["mean"], f["horizons"]["48"]["mean"]
                e24.append(haversine_km(m24[0], m24[1], c[4], c[5]))
                e48.append(haversine_km(m48[0], m48[1], c[6], c[7]))
        rows.append({"windage": a, "median_24_km": round(float(np.median(e24)), 2),
                     "median_48_km": round(float(np.median(e48)), 2)})
        log.info("windage %.3f -> 24 h %.1f km, 48 h %.1f km", a, rows[-1]["median_24_km"], rows[-1]["median_48_km"])
    best = min(rows, key=lambda r: r["median_48_km"])
    out = {"window": [start.isoformat(), end.isoformat()], "cases": len(cs),
           "forcing": {"currents": currents.source, "wind": wind.source},
           "results": rows, "best_windage": best["windage"],
           "created": datetime.now().isoformat(timespec="seconds")}
    (OUTPUTS / "windage_calibration.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=date.fromisoformat, default=date(2025, 2, 15))
    ap.add_argument("--end", type=date.fromisoformat, default=date(2025, 3, 1))
    ap.add_argument("--calibrate-windage", action="store_true")
    ap.add_argument("--holdout", action="store_true", help="score the held-out month (Feb 2025)")
    a = ap.parse_args()
    if a.holdout:
        r = run(*HOLDOUT_WINDOW, forcing=FORCING_WINDOW)
        print(json.dumps({k: r[k] for k in ("drifters", "cases", "summary", "persistence", "skill_vs_persistence")}, indent=2))
        raise SystemExit
    if a.calibrate_windage:
        print(json.dumps(calibrate_windage(a.start, a.end), indent=2))
        raise SystemExit
    r = run(a.start, a.end)
    print(json.dumps({k: r[k] for k in ("drifters", "cases", "forcing", "summary", "persistence", "skill_vs_persistence", "currents_only")}, indent=2))
