"""Cleanup risk score (0-100) and priority tier, as defined on the deck:

    hotspot confidence + predicted location (proximity to vulnerable coast / sites)
    + persistence / recurrence + beaching likelihood + forecast certainty
"""
from __future__ import annotations

import numpy as np

from .sources.coast import coast_distance_km, haversine_km, nearest_site

WEIGHTS = {"confidence": 0.35, "proximity": 0.25, "beaching": 0.15, "persistence": 0.15, "certainty": 0.10}


def persistence(h: dict, previous: list[list[dict]], radius_km: float = 15.0) -> float:
    """Fraction of earlier runs that also had a hotspot within `radius_km`."""
    if not previous:
        return 0.0
    hits = 0
    for run in previous:
        if any(haversine_km(h["lat"], h["lon"], p["lat"], p["lon"]) <= radius_km for p in run):
            hits += 1
    return hits / len(previous)


def score(h: dict, fc: dict, persist: float = 0.0) -> dict:
    track = np.array(fc["central_track"])            # [hour, lat, lon]
    lats = np.append(track[:, 1], fc["horizons"]["48"]["mean"][0])
    lons = np.append(track[:, 2], fc["horizons"]["48"]["mean"][1])
    best = (None, 1e9, 0.0)
    for la, lo in zip(lats[::3], lons[::3]):
        site, d = nearest_site(la, lo)
        s = site["weight"] * np.exp(-d / 60.0)
        if s > best[2]:
            best = (site, d, s)
    d_coast = float(np.min(coast_distance_km(lats, lons)))
    # Sensitive sites dominate; being near any coast adds a little (every coastal scene is near a coast)
    proximity = float(0.75 * best[2] + 0.25 * np.exp(-d_coast / 20.0))
    hz = fc["horizons"]["48"]
    spread = hz.get("flow_spread_km", hz["spread_km"])  # hotspot-specific part of the uncertainty
    certainty = float(1 - np.clip(spread / 25.0, 0, 1))
    comp = {
        "confidence": float(h["confidence"]),
        "proximity": proximity,
        "beaching": float(fc["beached_fraction"]),
        "persistence": float(persist),
        "certainty": certainty,
    }
    risk = 100 * sum(WEIGHTS[k] * v for k, v in comp.items())
    tier = "High" if risk >= 60 else "Medium" if risk >= 40 else "Low"
    site = best[0] or nearest_site(h["lat"], h["lon"])[0]
    p24 = fc["horizons"]["24"]["mean"]
    h50 = fc.get("half_beached_h")
    if h.get("ashore"):
        age = h.get("nowcast", {}).get("age_h", 0)
        action = (f"Seen {age} h ago; the drift model says it has most likely already washed ashore near "
                  f"{h['lat']:.2f}N {h['lon']:.2f}E: send a beach cleanup / survey team.")
    elif tier != "Low" and h50 is not None and h50 <= 24 and fc["beach_points"]:
        bl = np.mean(np.array(fc["beach_points"]), axis=0)
        action = (f"Likely to wash ashore near {bl[0]:.2f}N {bl[1]:.2f}E: half of the forecast particles are ashore by "
                  f"+{h50:.0f} h ({fc['beached_fraction'] * 100:.0f}% by +48 h). Send a shoreline cleanup team "
                  f"and alert {site['name']}.")
    elif tier == "High":
        action = (f"Deploy a cleanup vessel within 24 h; intercept near {p24[0]:.2f}N {p24[1]:.2f}E "
                  f"before it reaches {site['name']}.")
    elif tier == "Medium":
        action = f"Schedule a patrol and re-check the next satellite pass; watch the approach to {site['name']}."
    else:
        action = "Monitor: low confidence or far from sensitive coast."
    return {
        "risk_score": round(float(risk), 1), "tier": tier,
        "components": {k: round(v, 3) for k, v in comp.items()},
        "nearest_site": site["name"], "nearest_site_type": site["type"],
        "min_distance_to_site_km": round(float(best[1]), 1) if best[0] else None,
        "min_distance_to_coast_km": round(d_coast, 1),
        "first_beaching_h": fc.get("first_beaching_h"), "half_beached_h": h50,
        "intercept_24h": p24, "action": action,
    }
