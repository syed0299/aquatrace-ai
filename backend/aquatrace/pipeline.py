"""End-to-end run: OBSERVE -> DETECT -> FUSE -> FORECAST -> PRIORITIZE.

    python -m aquatrace.pipeline --date 2026-03-03            # auto: NASA data if logged in
    python -m aquatrace.pipeline --date 2026-03-03 --source s2 # force the Sentinel-2 fallback

Writes outputs/runs/<run_id>/run.json (+ map overlays) which the API and web app serve.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from .config import OUTPUTS, PROCESSED
from .drift import Seed, simulate
from .forcing import VelocityField
from .risk import persistence, score
from .source import attribute
from .sources import nasa, openmeteo

log = logging.getLogger("aquatrace")
RUNS = OUTPUTS / "runs"


# --- forcing ---------------------------------------------------------------------------------
def load_forcing(kind: str, start: date, end: date, prefer_nasa: bool = True) -> VelocityField:
    """Currents or wind for [start, end]; NASA product first, open fallback second. Cached."""
    nasa_path = PROCESSED / f"nasa_{kind}_{start:%Y%m%d}_{end:%Y%m%d}.nc"
    om_path = PROCESSED / f"om_{kind}_{start:%Y%m%d}_{end:%Y%m%d}.nc"
    if prefer_nasa and nasa_path.exists():
        return VelocityField.from_netcdf(nasa_path)
    if prefer_nasa and nasa.logged_in():
        try:
            f = nasa.oscar(start, end) if kind == "currents" else nasa.merra2_wind(start, end)
            f.to_netcdf(nasa_path)
            return f
        except Exception as e:  # keep going with the fallback, but say why
            log.warning("NASA %s unavailable (%s); using Open-Meteo fallback", kind, e)
    if om_path.exists():
        return VelocityField.from_netcdf(om_path)
    f = openmeteo.currents(start, end) if kind == "currents" else openmeteo.wind(start, end)
    f.to_netcdf(om_path)
    return f


# --- detection -------------------------------------------------------------------------------
def load_rf():
    try:
        from .marida import load_model
        return load_model()
    except Exception as e:
        log.warning("No MARIDA model (%s); detection uses spectral anomaly only", e)
        return None


def detect_pace(day: date, rf, outdir: Path, max_granules: int = 1, per_scene: int = 10):
    from .detect import find_hotspots, read_pace, render_overlays
    granules = nasa.pace_search(day)
    if not granules:
        raise RuntimeError(f"No PACE granules over the Bay of Bengal on {day}")
    files = nasa.pace_download(granules, limit=max_granules)
    hotspots, stats, overlays = [], [], []
    for i, f in enumerate(files):
        scene = read_pace(f)
        if scene is None:
            continue
        hs, st, extra = find_hotspots(scene, rf=rf, max_hotspots=per_scene)
        for h in hs:
            h["region"] = "Open Bay (PACE scan)"
        ov = render_overlays(scene, extra["z"], outdir / f"pace_{i}")
        ov = {k: (f"pace_{i}/{v}" if isinstance(v, str) else v) for k, v in ov.items()}
        overlays.append({"label": f"PACE OCI {scene.time}", **ov})
        hotspots += hs
        stats.append(st)
    return hotspots, stats, overlays


def detect_s2(day: date, rf, outdir: Path, per_target: int = 3):
    from .detect import find_hotspots, render_overlays
    from .sources import sentinel2
    hotspots, stats, overlays = [], [], []
    for i, t in enumerate(sentinel2.TARGETS):
        items = sentinel2.search(t["lat"], t["lon"], day)
        if not items:
            log.info("No clear Sentinel-2 pass for %s", t["name"])
            continue
        scene = sentinel2.read(items[0], t["lat"], t["lon"], name=t["name"])
        hs, st, extra = find_hotspots(scene, rf=rf, max_hotspots=per_target)
        ov = render_overlays(scene, extra["z"], outdir / f"s2_{i}")
        ov = {k: (f"s2_{i}/{v}" if isinstance(v, str) else v) for k, v in ov.items()}
        overlays.append({"label": f"Sentinel-2 {t['name']} {scene.time[:10]}", **ov})
        for h in hs:
            h["region"] = t["name"]
        hotspots += hs
        stats.append(st)
    return hotspots, stats, overlays


# --- run -------------------------------------------------------------------------------------
def previous_hotspots(exclude: str, before: date) -> list[list[dict]]:
    """Hotspots of saved runs from *earlier* dates only (a replay must not see later observations)."""
    out = []
    for p in sorted(RUNS.glob("*/run.json")):
        r = json.loads(p.read_text())
        if p.parent.name != exclude and r.get("date", "9999") < before.isoformat():
            out.append(r["hotspots"])
    return out


def run(day: date, source: str = "auto", max_hotspots: int = 25) -> Path:
    t_start = time.time()
    use_nasa = source in ("auto", "pace") and nasa.logged_in()
    sensor_tag = "pace" if use_nasa else "s2"
    run_id = f"{day:%Y%m%d}_{sensor_tag}"
    outdir = RUNS / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    rf = load_rf()

    hotspots, det_stats, overlays = [], [], []
    if use_nasa:  # regional scan of the open Bay with PACE (1.2 km)
        log.info("DETECT with PACE OCI")
        hotspots, det_stats, overlays = detect_pace(day, rf, outdir)
    if source in ("auto", "s2"):  # high-resolution coastal layer with Sentinel-2 (20 m)
        log.info("DETECT with Sentinel-2 (coastal)")
        h2, s2, o2 = detect_s2(day, rf, outdir)
        hotspots, det_stats, overlays = hotspots + h2, det_stats + s2, overlays + o2
    hotspots = sorted(hotspots, key=lambda h: -h["confidence"])[:max_hotspots]
    for i, h in enumerate(hotspots, 1):
        h["id"] = f"HS-{i:02d}"

    log.info("FUSE currents + wind")
    # NASA runs also load the 3 days *before* the pass for source back-tracking. Open-Meteo runs
    # reuse the forward window (persistence before it) to stay inside the free daily quota.
    f0 = day - timedelta(days=3) if use_nasa else day
    currents = load_forcing("currents", f0, day + timedelta(days=3), prefer_nasa=True)
    wind = load_forcing("wind", f0, day + timedelta(days=3), prefer_nasa=True)

    log.info("FORECAST %d hotspots", len(hotspots))
    obs = [datetime.fromisoformat(h["observed"]) for h in hotspots]
    forecasts = []
    for h, t0 in zip(hotspots, obs):
        forecasts += simulate([Seed(h["id"], h["lat"], h["lon"], max(0.5, h["radius_km"]))], t0, currents, wind)
        h["source"] = attribute(h, t0, currents, wind)

    log.info("PRIORITIZE")
    prev = previous_hotspots(run_id, day)
    for h, fc in zip(hotspots, forecasts):
        h["risk"] = score(h, fc, persistence(h, prev))
    order = sorted(range(len(hotspots)), key=lambda i: -hotspots[i]["risk"]["risk_score"])
    hotspots = [hotspots[i] for i in order]
    forecasts = [forecasts[i] for i in order]
    for rank, h in enumerate(hotspots, 1):
        h["rank"] = rank

    from .sources.coast import VULNERABLE_SITES
    t_mid = min(obs) if obs else datetime.combine(day, datetime.min.time())
    result = {
        "run_id": run_id, "date": day.isoformat(), "created": datetime.now().isoformat(timespec="seconds"),
        "region": "Bay of Bengal pilot",
        "sources": {
            "detection": " + ".join(dict.fromkeys(d["sensor"] for d in det_stats)) or None,
            "currents": currents.summary(), "wind": wind.summary(),
            "ml_model": "Two-expert classifier (Extra Trees + gradient boosting) trained on MARIDA (Sentinel-2), texture features v2" if rf is not None else None,
        },
        "detection": det_stats, "overlays": overlays,
        "hotspots": hotspots, "forecasts": forecasts,
        "fields": {"currents": currents.grid_sample(t_mid, step=2), "wind": wind.grid_sample(t_mid, step=2)},
        "sites": VULNERABLE_SITES,
        "runtime_s": round(time.time() - t_start, 1),
    }
    (outdir / "run.json").write_text(json.dumps(result, default=float))
    index = sorted({p.parent.name for p in RUNS.glob("*/run.json")}, reverse=True)
    (RUNS / "index.json").write_text(json.dumps(index))
    log.info("Done: %s (%d hotspots, %.0fs)", outdir, len(hotspots), result["runtime_s"])
    return outdir


# --- live (near-real-time) run ---------------------------------------------------------------
def nowcast(h: dict, now: datetime, currents: VelocityField, wind: VelocityField) -> dict:
    """Move a detection from its satellite time to `now` so the map shows where it most likely is."""
    obs = datetime.fromisoformat(h["observed"])
    age = int(round((now - obs).total_seconds() / 3600))
    h["detected"] = {"lat": h["lat"], "lon": h["lon"], "time": h["observed"]}
    if age < 1:
        h["nowcast"] = {"age_h": 0, "track": [], "spread_km": 0.0, "beached_fraction": 0.0}
        return h
    res = simulate([Seed(h["id"], h["lat"], h["lon"], max(0.5, h["radius_km"]))], obs, currents, wind,
                   hours=age, horizons=(age,), keep_particles=0, frame_every=10 ** 6)[0]
    hz = res["horizons"][str(age)]
    h["nowcast"] = {"age_h": age, "track": [[p[1], p[2]] for p in res["central_track"]],
                    "spread_km": hz["spread_km"], "beached_fraction": hz["beached_fraction"]}
    ashore = hz["beached_fraction"] >= 0.8 or hz["mean_floating"] is None
    h["lat"], h["lon"] = hz["mean"] if ashore else hz["mean_floating"]
    # spread is the RMS distance (2-D); Seed.radius_km is the per-axis standard deviation, hence / sqrt(2)
    h["radius_km"] = round(float(max(h["radius_km"], hz["spread_km"] / np.sqrt(2))), 2)
    h["ashore"] = bool(ashore)
    return h


def run_live(lookback_days: int = 3, max_granules: int = 3, max_hotspots: int = 25,
             issued: datetime | None = None) -> Path:
    """Latest satellite passes -> where the debris is likely *now* -> the next 48 h.
    `issued` re-issues a past live run (same passes and cached forcing), e.g. after retraining."""
    from .sources.coast import VULNERABLE_SITES, haversine_km
    t_start = time.time()
    now = (issued or datetime.utcnow()).replace(minute=0, second=0, microsecond=0)
    run_id = f"live_{now:%Y%m%d_%H}00"
    outdir = RUNS / run_id
    outdir.mkdir(parents=True, exist_ok=True)
    rf = load_rf()

    hotspots, det_stats, overlays = [], [], []
    if nasa.logged_in():
        from .detect import find_hotspots, read_pace, render_overlays
        granules = nasa.pace_search_recent(now - timedelta(days=lookback_days), now)
        log.info("DETECT: %d recent PACE NRT passes, using the best %d", len(granules), max_granules)
        for i, f in enumerate(nasa.pace_download(granules, limit=max_granules)):
            scene = read_pace(f)
            if scene is None:
                continue
            hs, st, extra = find_hotspots(scene, rf=rf, max_hotspots=10)
            for h in hs:
                h["region"] = "Open Bay (PACE NRT)"
            ov = render_overlays(scene, extra["z"], outdir / f"pace_{i}")
            overlays.append({"label": f"PACE OCI {scene.time}",
                             **{k: (f"pace_{i}/{v}" if isinstance(v, str) else v) for k, v in ov.items()}})
            hotspots += hs
            det_stats.append(st)
    log.info("DETECT: latest Sentinel-2 coastal passes")
    h2, s2, o2 = detect_s2(now.date(), rf, outdir)
    hotspots, det_stats, overlays = hotspots + h2, det_stats + s2, overlays + o2

    # Recurrence: the same place flagged on more than one pass is more trustworthy. Keep the newest.
    hotspots.sort(key=lambda h: h["observed"], reverse=True)
    passes = {h["observed"] for h in hotspots}
    kept = []
    for h in hotspots:
        same = [k for k in kept if haversine_km(h["lat"], h["lon"], k["detected_lat"], k["detected_lon"]) <= 15]
        if same:
            same[0]["seen_on"].add(h["observed"])
            continue
        h["detected_lat"], h["detected_lon"], h["seen_on"] = h["lat"], h["lon"], {h["observed"]}
        kept.append(h)
    for h in kept:
        h["recurrence"] = round((len(h.pop("seen_on")) - 1) / max(1, len(passes) - 1), 3)
        h.pop("detected_lat"); h.pop("detected_lon")
    hotspots = sorted(kept, key=lambda h: -h["confidence"])[:max_hotspots]
    for i, h in enumerate(hotspots, 1):
        h["id"] = f"HS-{i:02d}"

    log.info("FUSE: forecast currents + wind (Open-Meteo), from the oldest pass to +3 days")
    # from 3 days before the oldest pass (source back-tracking) to 3 days ahead (forecast)
    first = min((datetime.fromisoformat(h["observed"]) for h in hotspots), default=now).date() - timedelta(days=4)
    last = now.date() + timedelta(days=3)
    fpaths = {k: PROCESSED / f"live_{k}_{now:%Y%m%d%H}.nc" for k in ("currents", "wind")}
    if not fpaths["currents"].exists():
        openmeteo.currents(first, last).to_netcdf(fpaths["currents"])
    if not fpaths["wind"].exists():
        openmeteo.wind(first, last).to_netcdf(fpaths["wind"])
    currents, wind = (VelocityField.from_netcdf(fpaths[k]) for k in ("currents", "wind"))

    log.info("NOWCAST + FORECAST %d hotspots", len(hotspots))
    forecasts = []
    for h in hotspots:
        h["source"] = attribute(h, datetime.fromisoformat(h["observed"]), currents, wind)
        nowcast(h, now, currents, wind)
        forecasts += simulate([Seed(h["id"], h["lat"], h["lon"], max(0.5, h["radius_km"]))], now, currents, wind)

    for h, fc in zip(hotspots, forecasts):
        h["risk"] = score(h, fc, h["recurrence"])
    order = sorted(range(len(hotspots)), key=lambda i: -hotspots[i]["risk"]["risk_score"])
    hotspots, forecasts = [hotspots[i] for i in order], [forecasts[i] for i in order]
    for rank, h in enumerate(hotspots, 1):
        h["rank"] = rank

    latest = max((h["observed"] for h in hotspots), default=None)
    result = {
        "run_id": run_id, "live": True, "date": now.date().isoformat(),
        "issued": now.isoformat(), "latest_pass": latest,
        "created": datetime.now().isoformat(timespec="seconds"), "region": "Bay of Bengal pilot",
        "sources": {
            "detection": " + ".join(dict.fromkeys(d["sensor"] for d in det_stats)) or None,
            "currents": currents.summary(), "wind": wind.summary(),
            "ml_model": "Two-expert classifier (Extra Trees + gradient boosting) trained on MARIDA (Sentinel-2), texture features v2" if rf is not None else None,
        },
        "forcing_files": {k: str(p.relative_to(PROCESSED)) for k, p in fpaths.items()},
        "detection": det_stats, "overlays": overlays, "hotspots": hotspots, "forecasts": forecasts,
        "fields": {"currents": currents.grid_sample(np.datetime64(now), step=2),
                   "wind": wind.grid_sample(np.datetime64(now), step=2)},
        "sites": VULNERABLE_SITES, "runtime_s": round(time.time() - t_start, 1),
    }
    (outdir / "run.json").write_text(json.dumps(result, default=float))
    index = sorted({p.parent.name for p in RUNS.glob("*/run.json")}, reverse=True)
    (RUNS / "index.json").write_text(json.dumps(index))
    log.info("Done: %s (%d hotspots, %.0fs)", outdir, len(hotspots), result["runtime_s"])
    return outdir


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, help="hindcast date (omit with --live)")
    ap.add_argument("--live", action="store_true", help="near-real-time run: latest passes, forecast from now")
    ap.add_argument("--source", default="auto", choices=["auto", "pace", "s2"])
    ap.add_argument("--max-hotspots", type=int, default=25)
    ap.add_argument("--issued", type=datetime.fromisoformat, help="with --live: re-issue a past run, e.g. 2026-09-30T19:00")
    a = ap.parse_args()
    if a.live:
        run_live(max_hotspots=a.max_hotspots, issued=a.issued)
    elif a.date:
        run(a.date, a.source, a.max_hotspots)
    else:
        ap.error("give --date YYYY-MM-DD or --live")
