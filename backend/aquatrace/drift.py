"""Lagrangian particle-advection drift model.

Each hotspot is released as an ensemble of particles. Every particle moves with

    velocity = ocean current + windage * 10 m wind      (RK4 time stepping)
             + current error (constant per particle, sd CURRENT_SIGMA)
             + random walk with eddy diffusivity K

and a per-particle windage drawn from WINDAGE_RANGE (unknown debris type). The spread of the
ensemble is the forecast uncertainty (the current error is tuned so the 90 % cone really
contains real buoys ~90 % of the time, see tune_drift.py); particles that hit the land polygon are "beached" and
tell us which coastline is at risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import shapely
from shapely.geometry import MultiPoint

from .config import (CURRENT_SIGMA, DIFFUSIVITY, DT_HOURS, FORECAST_HOURS, M_PER_DEG_LAT, PARTICLES_PER_HOTSPOT,
                     RANDOM_SEED, WINDAGE_RANGE)
from .forcing import VelocityField
from .sources.coast import haversine_km, on_land


@dataclass
class Seed:
    id: str
    lat: float
    lon: float
    radius_km: float = 2.0


def _to_deg(lat, dx_m, dy_m):
    return dy_m / M_PER_DEG_LAT, dx_m / (M_PER_DEG_LAT * np.cos(np.deg2rad(lat)))


def _hull(lat, lon, keep=0.9):
    """Polygon (list of [lat, lon]) enclosing the `keep` fraction of particles closest to the median."""
    if len(lat) < 4:
        return [[float(a), float(b)] for a, b in zip(lat, lon)]
    mlat, mlon = np.median(lat), np.median(lon)
    d = haversine_km(mlat, mlon, lat, lon)
    idx = np.argsort(d)[: max(4, int(len(d) * keep))]
    poly = MultiPoint(np.column_stack([lon[idx], lat[idx]])).convex_hull
    if poly.geom_type != "Polygon":
        poly = poly.buffer(0.01)
    return [[round(y, 4), round(x, 4)] for x, y in poly.exterior.coords]


def simulate(seeds: list[Seed], start: datetime, currents: VelocityField, wind: VelocityField,
             hours: int = FORECAST_HOURS, dt_h: float = DT_HOURS, n: int = PARTICLES_PER_HOTSPOT,
             windage=WINDAGE_RANGE, diffusivity: float = DIFFUSIVITY, rng_seed: int = RANDOM_SEED,
             frame_every: int = 3, keep_particles: int = 60, horizons=(24, 48),
             backward: bool = False, current_sigma: float = CURRENT_SIGMA) -> list[dict]:
    """Forward forecast, or with backward=True a back-track (time runs backwards) to find where the
    debris came from; back-tracked particles that reach land mark a likely coastal / river source."""
    rng = np.random.default_rng(rng_seed)
    S = len(seeds)
    if S == 0:
        return []
    owner = np.concatenate([np.repeat(np.arange(S), n), np.arange(S)])  # last S = central particles
    slat = np.array([s.lat for s in seeds]); slon = np.array([s.lon for s in seeds])
    srad = np.array([s.radius_km for s in seeds])
    lat = np.concatenate([np.repeat(slat, n) + rng.normal(0, 1, S * n) * np.repeat(srad, n) / 111.32, slat])
    lon = np.concatenate([np.repeat(slon, n) + rng.normal(0, 1, S * n) * np.repeat(srad, n)
                          / (111.32 * np.cos(np.deg2rad(np.repeat(slat, n)))), slon])
    alpha = np.concatenate([rng.uniform(*windage, S * n), np.full(S, np.mean(windage))])
    diffuse = np.concatenate([np.ones(S * n), np.zeros(S)])
    is_central = np.concatenate([np.zeros(S * n, bool), np.ones(S, bool)])
    # Forcing error: daily ~25 km current products miss tides, inertial motion and small eddies, so
    # each particle carries its own constant current error. Real forecast errors grow ~linearly in
    # time (a velocity error), which diffusion alone (~sqrt(t)) cannot reproduce.
    # Errors come in +/- (antithetic) pairs per hotspot, so they widen the cone without shifting its centre.
    err_u = np.zeros(lat.size); err_v = np.zeros(lat.size)
    if current_sigma > 0:
        for err in (err_u, err_v):
            z = rng.normal(0, current_sigma, (S, n // 2))
            err[: S * n] = np.concatenate([z, -z, np.zeros((S, n % 2))], axis=1).ravel()

    # Near-shore seeds can fall inside the (coarse) land polygon. Only a move from sea onto land
    # counts as beaching, so those particles are not "beached" at t = 0.
    was_land = on_land(lat, lon)
    beached = np.zeros(lat.size, bool)
    beach_hour = np.full(lat.size, np.nan)
    dt = dt_h * 3600.0
    ds = -dt if backward else dt  # signed time step in seconds
    t0 = np.datetime64(start, "s")

    def vel(t, la, lo, al):
        uc, vc = currents.at(t, la, lo)
        uw, vw = wind.at(t, la, lo)
        return uc + al * uw, vc + al * vw

    nsteps = int(round(hours / dt_h))
    central_track = [[[0.0, float(slat[k]), float(slon[k])]] for k in range(S)]
    frames = {k: [] for k in range(S)}
    snap = {}
    sample_idx = [np.flatnonzero((owner == k) & ~is_central)[:keep_particles] for k in range(S)]

    def record(h):
        if h % frame_every == 0:
            for k in range(S):
                ii = sample_idx[k]
                frames[k].append({"h": h, "p": [[round(float(a), 4), round(float(b), 4), int(c)]
                                                for a, b, c in zip(lat[ii], lon[ii], beached[ii])]})
        if h in horizons:
            snap[h] = (lat.copy(), lon.copy(), beached.copy())

    record(0)
    for step in range(nsteps):
        t = t0 + np.timedelta64(int(step * ds), "s")
        a = ~beached
        la, lo, al = lat[a], lon[a], alpha[a]
        half = np.timedelta64(int(ds / 2), "s")
        # RK4 on the deterministic part of the motion
        u1, v1 = vel(t, la, lo, al)
        d1 = _to_deg(la, u1 * ds / 2, v1 * ds / 2)
        u2, v2 = vel(t + half, la + d1[0], lo + d1[1], al)
        d2 = _to_deg(la, u2 * ds / 2, v2 * ds / 2)
        u3, v3 = vel(t + half, la + d2[0], lo + d2[1], al)
        d3 = _to_deg(la, u3 * ds, v3 * ds)
        u4, v4 = vel(t + np.timedelta64(int(ds), "s"), la + d3[0], lo + d3[1], al)
        u = (u1 + 2 * u2 + 2 * u3 + u4) / 6 + err_u[a]
        v = (v1 + 2 * v2 + 2 * v3 + v4) / 6 + err_v[a]
        # stochastic part: random walk with diffusivity K
        sig = np.sqrt(2 * diffusivity * dt)
        dx = u * ds + rng.normal(0, 1, la.size) * sig * diffuse[a]
        dy = v * ds + rng.normal(0, 1, la.size) * sig * diffuse[a]
        dlat, dlon = _to_deg(la, dx, dy)
        nla, nlo = la + dlat, lo + dlon
        land = on_land(nla, nlo)
        idx_a = np.flatnonzero(a)
        hit = land & ~was_land[idx_a]
        was_land[idx_a] = land
        lat[a], lon[a] = nla, nlo
        beached[idx_a[hit]] = True
        beach_hour[idx_a[hit]] = (step + 1) * dt_h
        h = int(round((step + 1) * dt_h))
        for k in range(S):
            c = S * n + k
            central_track[k].append([float(h), round(float(lat[c]), 4), round(float(lon[c]), 4)])
        record(h)

    results = []
    for k, s in enumerate(seeds):
        m = (owner == k) & ~is_central
        out = {"id": s.id, "start": str(t0), "seed": {"lat": s.lat, "lon": s.lon},
               "central_track": central_track[k], "frames": frames[k], "horizons": {}}
        for h, (hl, hn, hb) in snap.items():
            pl, pn, pb = hl[m], hn[m], hb[m]
            mlat, mlon = float(np.mean(pl)), float(np.mean(pn))
            spread = float(np.sqrt(np.mean(haversine_km(mlat, mlon, pl, pn) ** 2)))
            fl = ~pb
            out["horizons"][str(h)] = {
                "mean": [round(mlat, 4), round(mlon, 4)],
                "mean_floating": [round(float(np.mean(pl[fl])), 4), round(float(np.mean(pn[fl])), 4)] if fl.any() else None,
                "spread_km": round(spread, 2),
                # spread caused by this hotspot's own flow (shear, divergence, coast), i.e. without the
                # forcing-error and diffusion terms that are the same for every hotspot (RMS, km)
                "flow_spread_km": round(float(np.sqrt(max(spread ** 2 - 2 * (current_sigma * h * 3.6) ** 2
                                                          - 4 * diffusivity * h * 3600 / 1e6, 0.0))), 2),
                "displacement_km": round(float(haversine_km(s.lat, s.lon, mlat, mlon)), 2),
                "beached_fraction": round(float(pb.mean()), 3),
                "hull": _hull(pl, pn),
            }
        bh = beach_hour[m]
        bl, bn = lat[m][~np.isnan(bh)], lon[m][~np.isnan(bh)]
        out["beached_fraction"] = round(float(np.mean(~np.isnan(bh))), 3)
        out["first_beaching_h"] = None if np.all(np.isnan(bh)) else float(np.nanmin(bh))
        # hour by which half of the particles are ashore (None if fewer than half beach within the forecast)
        hb = np.sort(bh[~np.isnan(bh)])
        out["half_beached_h"] = float(hb[(bh.size - 1) // 2]) if hb.size * 2 >= bh.size else None
        out["beach_points"] = [[round(float(a), 4), round(float(b), 4)] for a, b in zip(bl[:80], bn[:80])]
        results.append(out)
    return results
