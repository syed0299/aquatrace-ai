"""Land mask, coastline distance and ecologically / economically sensitive coastal sites."""
from __future__ import annotations

import io
import zipfile
from functools import lru_cache

import geopandas as gpd
import numpy as np
import requests
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import box

from ..config import BBOX, RAW

NE_LAND = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip"
NE_COAST = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_coastline.zip"

# Approximate locations of sensitive sites around the Bay of Bengal used for the
# "proximity to vulnerable areas" term of the cleanup risk score.
VULNERABLE_SITES = [
    {"name": "Sundarbans mangroves", "type": "Mangrove / UNESCO site", "lat": 21.75, "lon": 89.20, "weight": 1.0},
    {"name": "Bhitarkanika & Gahirmatha", "type": "Mangrove / turtle nesting", "lat": 20.70, "lon": 87.00, "weight": 1.0},
    {"name": "Rushikulya rookery", "type": "Olive ridley nesting", "lat": 19.37, "lon": 85.07, "weight": 0.9},
    {"name": "Chilika Lake mouth", "type": "Ramsar lagoon", "lat": 19.70, "lon": 85.45, "weight": 0.9},
    {"name": "Coringa mangroves (Godavari)", "type": "Mangrove sanctuary", "lat": 16.75, "lon": 82.30, "weight": 0.9},
    {"name": "Krishna mangroves", "type": "Mangrove sanctuary", "lat": 15.80, "lon": 81.00, "weight": 0.8},
    {"name": "Pulicat Lake", "type": "Ramsar lagoon", "lat": 13.55, "lon": 80.30, "weight": 0.8},
    {"name": "Pichavaram mangroves", "type": "Mangrove", "lat": 11.43, "lon": 79.80, "weight": 0.8},
    {"name": "Point Calimere", "type": "Ramsar wetland", "lat": 10.30, "lon": 79.85, "weight": 0.8},
    {"name": "Mahatma Gandhi Marine NP (Andaman)", "type": "Coral reef park", "lat": 11.55, "lon": 92.60, "weight": 1.0},
    {"name": "Ritchie's Archipelago (Andaman)", "type": "Coral reef", "lat": 12.10, "lon": 93.05, "weight": 0.9},
    {"name": "St. Martin's Island", "type": "Coral island", "lat": 20.62, "lon": 92.32, "weight": 1.0},
    {"name": "Cox's Bazar coast", "type": "Beach / fisheries", "lat": 21.43, "lon": 91.97, "weight": 0.7},
    {"name": "Trincomalee coast", "type": "Coral reef / fisheries", "lat": 8.58, "lon": 81.23, "weight": 0.8},
    {"name": "Kolkata-Haldia port", "type": "Major port", "lat": 22.02, "lon": 88.08, "weight": 0.6},
    {"name": "Paradip port", "type": "Major port", "lat": 20.26, "lon": 86.68, "weight": 0.6},
    {"name": "Visakhapatnam port", "type": "Major port", "lat": 17.69, "lon": 83.29, "weight": 0.6},
    {"name": "Chennai port & Marina", "type": "Major port / beach", "lat": 13.08, "lon": 80.30, "weight": 0.7},
    {"name": "Chittagong port", "type": "Major port", "lat": 22.27, "lon": 91.80, "weight": 0.6},
]


def _download(url: str, name: str) -> gpd.GeoDataFrame:
    path = RAW / "naturalearth" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        r = requests.get(url, timeout=120, headers={"User-Agent": "aquatrace/0.1"})
        r.raise_for_status()
        path.write_bytes(r.content)
    region = box(BBOX["lon_min"] - 3, BBOX["lat_min"] - 3, BBOX["lon_max"] + 3, BBOX["lat_max"] + 3)
    gdf = gpd.read_file(f"zip://{path}")
    return gdf[gdf.intersects(region)].clip(region)


@lru_cache(maxsize=1)
def land_geometry():
    geom = shapely.union_all(_download(NE_LAND, "ne_10m_land.zip").geometry.values)
    shapely.prepare(geom)
    return geom


def on_land(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    return shapely.contains_xy(land_geometry(), lon, lat)


def _unit(lat, lon):
    la, lo = np.deg2rad(lat), np.deg2rad(lon)
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])


@lru_cache(maxsize=1)
def _coast_tree():
    coast = _download(NE_COAST, "ne_10m_coastline.zip")
    pts = []
    for g in coast.geometry.values:
        for line in getattr(g, "geoms", [g]):
            seg = shapely.segmentize(line, 0.01)  # ~1 km spacing
            pts.append(np.asarray(seg.coords))
    xy = np.vstack(pts)
    return cKDTree(_unit(xy[:, 1], xy[:, 0]))


def coast_distance_km(lat, lon) -> np.ndarray:
    d, _ = _coast_tree().query(_unit(np.atleast_1d(lat), np.atleast_1d(lon)))
    return 2 * np.arcsin(np.clip(d / 2, 0, 1)) * 6371.0


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.deg2rad, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def nearest_site(lat, lon):
    """Nearest vulnerable site to a point: (site dict, distance km)."""
    lats = np.array([s["lat"] for s in VULNERABLE_SITES])
    lons = np.array([s["lon"] for s in VULNERABLE_SITES])
    d = haversine_km(lat, lon, lats, lons)
    k = int(np.argmin(d))
    return VULNERABLE_SITES[k], float(d[k])
