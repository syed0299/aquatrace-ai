"""Fallback forcing from Open-Meteo (no login needed).

* Currents: Open-Meteo Marine API (Mercator/Meteo-France SMOC ocean model), history + forecast.
* Wind: ERA5 reanalysis (archive API) for past dates, GFS/ECMWF blend (forecast API) for recent
  and future dates, so the same pipeline can also run a genuine live forecast.
"""
from __future__ import annotations

import time
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

from ..config import BBOX
from ..forcing import VelocityField

MARINE = "https://marine-api.open-meteo.com/v1/marine"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
BATCH = 100


def _grid(step: float, bbox=BBOX):
    lats = np.round(np.arange(bbox["lat_min"], bbox["lat_max"] + 1e-9, step), 4)
    lons = np.round(np.arange(bbox["lon_min"], bbox["lon_max"] + 1e-9, step), 4)
    return lats, lons


def _fetch(url: str, lats, lons, params: dict) -> list[dict]:
    """Query many points in batches; returns one response dict per point."""
    pts = [(la, lo) for la in lats for lo in lons]
    out: list[dict] = []
    s = requests.Session()
    for i in range(0, len(pts), BATCH):
        chunk = pts[i:i + BATCH]
        p = dict(params)
        p["latitude"] = ",".join(f"{la:.3f}" for la, _ in chunk)
        p["longitude"] = ",".join(f"{lo:.3f}" for _, lo in chunk)
        for attempt in range(5):
            r = s.get(url, params=p, timeout=120)
            if r.status_code == 200:
                j = r.json()
                out.extend(j if isinstance(j, list) else [j])
                break
            if r.status_code == 429:  # rate limited: back off
                time.sleep(20 * (attempt + 1))
                continue
            raise RuntimeError(f"Open-Meteo {r.status_code}: {r.text[:300]}")
        else:
            raise RuntimeError("Open-Meteo rate limit: retries exhausted")
        time.sleep(1.0)
    return out


def _to_field(name, source, rows, lats, lons, speed_key, dir_key, speed_scale, direction_is_from):
    times = pd.to_datetime(rows[0]["hourly"]["time"]).values.astype("datetime64[s]")
    nt, ny, nx = len(times), len(lats), len(lons)
    u = np.full((nt, ny, nx), np.nan, dtype="float32")
    v = np.full((nt, ny, nx), np.nan, dtype="float32")
    for k, row in enumerate(rows):
        i, j = divmod(k, nx)
        spd = np.array(row["hourly"][speed_key], dtype="float64") * speed_scale
        ang = np.deg2rad(np.array(row["hourly"][dir_key], dtype="float64"))
        sign = -1.0 if direction_is_from else 1.0  # meteorological "from" vs oceanographic "towards"
        u[:, i, j] = sign * spd * np.sin(ang)
        v[:, i, j] = sign * spd * np.cos(ang)
    return VelocityField(name, source, times, np.asarray(lats), np.asarray(lons), u, v)


def currents(start: date, end: date, step: float = 0.5) -> VelocityField:
    lats, lons = _grid(step)
    rows = _fetch(MARINE, lats, lons, {
        "hourly": "ocean_current_velocity,ocean_current_direction",
        "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "GMT",
    })
    # ocean_current_velocity is km/h; direction is where the current flows *towards*
    return _to_field("currents", "Open-Meteo Marine (SMOC ocean model) [fallback for NASA OSCAR]",
                     rows, lats, lons, "ocean_current_velocity", "ocean_current_direction", 1 / 3.6, False)


def wind(start: date, end: date, step: float = 0.5) -> VelocityField:
    lats, lons = _grid(step)
    recent = end >= date.today() - timedelta(days=6)
    url = FORECAST if recent else ARCHIVE
    label = "Open-Meteo forecast (GFS/ECMWF)" if recent else "Open-Meteo ERA5 reanalysis"
    rows = _fetch(url, lats, lons, {
        "hourly": "wind_speed_10m,wind_direction_10m", "wind_speed_unit": "ms",
        "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "GMT",
    })
    return _to_field("wind", f"{label} 10 m wind [fallback for NASA MERRA-2]",
                     rows, lats, lons, "wind_speed_10m", "wind_direction_10m", 1.0, True)
