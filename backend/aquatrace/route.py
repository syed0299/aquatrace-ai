"""Cleanup vessel route planner with moving-target interception.

Debris keeps drifting while the boat travels, so each stop is aimed at the hotspot's *forecast*
position at the boat's arrival time (fixed-point iteration on the forecast track), not where the
satellite saw it. Stops are chosen greedily by travel time weighted by risk.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from .sources.coast import haversine_km, on_land

# Offshore approach / anchorage points (so routes start at sea, not on the harbour quay)
PORTS = [
    {"name": "Chennai", "lat": 13.09, "lon": 80.37},
    {"name": "Ennore (Kamarajar)", "lat": 13.26, "lon": 80.38},
    {"name": "Kakinada", "lat": 16.98, "lon": 82.40},
    {"name": "Visakhapatnam", "lat": 17.65, "lon": 83.36},
    {"name": "Paradip", "lat": 20.25, "lon": 86.74},
    {"name": "Haldia (Sagar Roads)", "lat": 21.45, "lon": 88.00},
    {"name": "Chittagong", "lat": 22.12, "lon": 91.70},
    {"name": "Port Blair", "lat": 11.66, "lon": 92.80},
]


def _position(track: np.ndarray, hour: float):
    """Interpolated forecast position at `hour` (clamped to the forecast window)."""
    h = np.clip(hour, track[0, 0], track[-1, 0])
    return float(np.interp(h, track[:, 0], track[:, 1])), float(np.interp(h, track[:, 0], track[:, 2]))


def _crosses_land(a, b, skip_km: float = 6.0) -> bool:
    """True if the straight leg a -> b passes over land (ignoring the first/last few km at the coast)."""
    d = haversine_km(*a, *b)
    if d < 2 * skip_km:
        return False
    f = np.linspace(skip_km / d, 1 - skip_km / d, 25)
    return bool(on_land(a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])).any())


def _sea_path(a, b):
    """Straight leg if it stays at sea, else the shortest detour via one offshore waypoint.
    Returns (distance_km, [waypoints]) or None if no simple sea path is found."""
    if not _crosses_land(a, b):
        return haversine_km(*a, *b), []
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    dy, dx = b[0] - a[0], (b[1] - a[1]) * np.cos(np.deg2rad(mid[0]))
    norm = np.hypot(dx, dy) or 1.0
    best = None
    for frac in (0.25, 0.5, 0.75):
        base = (a[0] + frac * (b[0] - a[0]), a[1] + frac * (b[1] - a[1]))
        for off_km in (10, 20, 40, 70, 110):
            for side in (1, -1):
                # perpendicular offset (north/east components in km -> degrees)
                wlat = base[0] + side * (dx / norm) * off_km / 111.32
                wlon = base[1] - side * (dy / norm) * off_km / (111.32 * np.cos(np.deg2rad(base[0])))
                w = (float(wlat), float(wlon))
                if on_land(np.array([w[0]]), np.array([w[1]]))[0] or _crosses_land(a, w) or _crosses_land(w, b):
                    continue
                d = haversine_km(*a, *w) + haversine_km(*w, *b)
                if best is None or d < best[0]:
                    best = (d, [w])
    return best


def plan(run: dict, port_name: str, speed_kn: float = 10.0, max_stops: int = 5, service_h: float = 2.0,
         max_range_km: float = 450.0, include_low: bool = False) -> dict:
    port = next((p for p in PORTS if p["name"] == port_name), None)
    if port is None:
        raise ValueError(f"unknown port {port_name}")
    speed = speed_kn * 1.852  # km/h
    fcs = {f["id"]: f for f in run["forecasts"]}
    starts = {f["id"]: datetime.fromisoformat(f["start"]) for f in run["forecasts"]}
    depart = datetime.fromisoformat(run["issued"]) if run.get("live") else max(starts.values())
    cands = [h for h in run["hotspots"]
             if not h.get("ashore") and (include_low or h["risk"]["tier"] != "Low")
             and haversine_km(port["lat"], port["lon"], h["lat"], h["lon"]) <= max_range_km]

    pos, t, stops, total = (port["lat"], port["lon"]), 0.0, [], 0.0
    remaining = {h["id"]: h for h in cands}
    while remaining and len(stops) < max_stops:
        best = None
        for hid, h in remaining.items():
            track = np.array(fcs[hid]["central_track"])
            offset = (depart - starts[hid]).total_seconds() / 3600  # forecast hour at departure
            T = haversine_km(*pos, *_position(track, offset + t)) / speed
            for _ in range(6):  # fixed point: arrive where it will be when we get there
                T = haversine_km(*pos, *_position(track, offset + t + T)) / speed
            tgt = _position(track, offset + t + T)
            if t + T > track[-1, 0] - offset or on_land(np.array([tgt[0]]), np.array([tgt[1]]))[0]:
                continue  # beyond the 48 h forecast, or already washed ashore (shoreline team's job)
            path = _sea_path(pos, tgt)
            if path is None:
                continue
            T = path[0] / speed  # detours take longer
            cost = T * (1.6 - h["risk"]["risk_score"] / 100)  # prefer near *and* high-risk
            if best is None or cost < best[0]:
                best = (cost, hid, T, tgt, path)
        if best is None:
            break
        _, hid, T, tgt, path = best
        leg = path[0]
        total += leg
        t += T
        h = remaining.pop(hid)
        stops.append({"id": hid, "rank": h["rank"], "tier": h["risk"]["tier"], "risk": h["risk"]["risk_score"],
                      "arrive_h": round(float(t), 1), "lat": round(tgt[0], 4), "lon": round(tgt[1], 4),
                      "leg_km": round(float(leg), 1), "via": [[round(a, 4), round(b, 4)] for a, b in path[1]],
                      "seen_at": [h["lat"], h["lon"]],
                      "drift_since_seen_km": round(float(haversine_km(h["lat"], h["lon"], *tgt)), 1)})
        t += service_h
        pos = tgt
    back_path = _sea_path(pos, (port["lat"], port["lon"])) if stops else (0.0, [])
    back_path = back_path or (haversine_km(*pos, port["lat"], port["lon"]), [])
    back = back_path[0]
    total += back
    return {"port": port, "speed_kn": speed_kn, "depart": depart.isoformat(), "stops": stops,
            "return_km": round(float(back), 1), "return_via": [[round(a, 4), round(b, 4)] for a, b in back_path[1]], "total_km": round(float(total), 1),
            "total_h": round(float(t + back / speed), 1), "candidates": len(cands),
            "note": "Legs detour via an offshore waypoint when a straight line would cross land; stops beyond the "
                    "48 h forecast or already ashore are skipped."}
