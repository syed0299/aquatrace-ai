"""Source tracking: run the drift model backwards to estimate where a hotspot came from.

Back-tracked particles that reach land within the window point to a land-based source; we
name the nearest major river mouth, because rivers carry most land-based plastic to the sea.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from .drift import Seed, simulate
from .forcing import VelocityField
from .sources.coast import haversine_km

# Approximate river mouths draining into the Bay of Bengal / Andaman Sea
RIVER_MOUTHS = [
    {"name": "Hooghly (Ganga) mouth", "lat": 21.62, "lon": 88.10},
    {"name": "Subarnarekha mouth", "lat": 21.58, "lon": 87.45},
    {"name": "Brahmani-Baitarani mouth", "lat": 20.72, "lon": 87.02},
    {"name": "Mahanadi mouth", "lat": 20.30, "lon": 86.72},
    {"name": "Godavari mouth", "lat": 16.62, "lon": 82.30},
    {"name": "Krishna mouth", "lat": 15.75, "lon": 80.95},
    {"name": "Penner mouth", "lat": 14.60, "lon": 80.18},
    {"name": "Chennai rivers (Adyar/Cooum)", "lat": 13.05, "lon": 80.28},
    {"name": "Cauvery mouth", "lat": 11.35, "lon": 79.85},
    {"name": "Meghna (Ganges-Brahmaputra) estuary", "lat": 22.40, "lon": 90.80},
    {"name": "Karnaphuli mouth (Chittagong)", "lat": 22.22, "lon": 91.80},
    {"name": "Irrawaddy delta", "lat": 15.85, "lon": 95.10},
]
COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


def _bearing(lat1, lon1, lat2, lon2) -> str:
    dy = lat2 - lat1
    dx = (lon2 - lon1) * np.cos(np.deg2rad((lat1 + lat2) / 2))
    ang = (np.degrees(np.arctan2(dx, dy)) + 360) % 360
    return COMPASS[int((ang + 22.5) // 45) % 8]


def attribute(h: dict, start: datetime, currents: VelocityField, wind: VelocityField,
              hours: int = 72, near_km: float = 60.0) -> dict:
    res = simulate([Seed(h["id"], h["lat"], h["lon"], max(0.5, h.get("radius_km", 1.0)))], start, currents, wind,
                   hours=hours, horizons=(hours,), keep_particles=0, frame_every=10 ** 6, backward=True)[0]
    hz = res["horizons"][str(hours)]
    coastal = float(res["beached_fraction"])
    shares = {}
    for la, lo in res["beach_points"]:
        d = [haversine_km(la, lo, r["lat"], r["lon"]) for r in RIVER_MOUTHS]
        k = int(np.argmin(d))
        name = RIVER_MOUTHS[k]["name"] if d[k] <= near_km else "other coastline"
        shares[name] = shares.get(name, 0) + 1
    n = max(1, len(res["beach_points"]))
    sources = sorted(({"name": k, "share": round(coastal * v / n, 3)} for k, v in shares.items()),
                     key=lambda s: -s["share"])
    track = [[p[1], p[2]] for p in res["central_track"]]
    origin = hz["mean_floating"] or hz["mean"]
    if coastal >= 0.3 and sources and sources[0]["name"] != "other coastline":
        s = sources[0]
        summary = (f"{coastal * 100:.0f}% of back-tracked particles reach the coast within {hours} h, mostly near the "
                   f"{s['name']}: likely a river-borne, land-based source.")
    elif coastal >= 0.3:
        summary = (f"{coastal * 100:.0f}% of back-tracked particles reach the nearby coastline within {hours} h: "
                   "likely a local coastal source.")
    else:
        d = haversine_km(h["lat"], h["lon"], origin[0], origin[1])
        summary = (f"Stayed at sea for the last {hours} h: about {d:.0f} km {_bearing(h['lat'], h['lon'], *origin)} "
                   f"of here {hours // 24} days ago. Source further upstream than {hours} h.")
    return {"hours": hours, "coastal_fraction": round(coastal, 3), "sources": sources[:3],
            "origin": origin, "track": track, "summary": summary}
