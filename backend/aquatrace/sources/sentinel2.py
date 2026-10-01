"""Sentinel-2 L2A (10-20 m) from the open Earth Search STAC catalogue (no login).

Used (a) as the detection fallback when PACE cannot be downloaded and (b) as a
high-resolution confirmation layer: the MARIDA Random Forest was trained on Sentinel-2 pixels,
so it applies here without any band conversion.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import rasterio
from pyproj import Transformer
from pystac_client import Client
from rasterio.windows import from_bounds

from ..config import PROCESSED
from ..detect import S2_BANDS, Scene

STAC = "https://earth-search.aws.element84.com/v1"
ASSET = {"B1": "coastal", "B2": "blue", "B3": "green", "B4": "red", "B5": "rededge1", "B6": "rededge2",
         "B7": "rededge3", "B8": "nir", "B8A": "nir08", "B11": "swir16", "B12": "swir22"}

# Coastal targets where river-borne debris enters the Bay of Bengal
TARGETS = [
    {"name": "Chennai coast", "lat": 13.10, "lon": 80.35},
    {"name": "Hooghly estuary / Sagar Island", "lat": 21.55, "lon": 88.15},
    {"name": "Visakhapatnam coast", "lat": 17.65, "lon": 83.35},
    {"name": "Cox's Bazar coast", "lat": 21.35, "lon": 91.90},
    {"name": "Port Blair (Andaman)", "lat": 11.65, "lon": 92.78},
]


def search(lat: float, lon: float, day: date, days: int = 6, max_cloud: float = 20.0):
    c = Client.open(STAC)
    s = c.search(collections=["sentinel-2-l2a"],
                 intersects={"type": "Point", "coordinates": [lon, lat]},
                 datetime=f"{(day - timedelta(days=days)).isoformat()}/{(day + timedelta(days=days)).isoformat()}",
                 query={"eo:cloud_cover": {"lt": max_cloud}}, max_items=20)
    items = list(s.items())
    # prefer the pass closest in time, then least cloudy
    return sorted(items, key=lambda it: (abs((it.datetime.date() - day).days), it.properties.get("eo:cloud_cover", 100)))


def read(item, lat: float, lon: float, half_km: float = 15.0, res_m: float = 20.0, name: str = "") -> Scene:
    """Read a window around (lat, lon); cached as .npz so pipeline re-runs are fast."""
    cache = PROCESSED / "s2" / f"{item.id}_{lat:.2f}_{lon:.2f}_{int(half_km)}km_{int(res_m)}m.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=False)
        return Scene("ESA Sentinel-2 L2A (MSI)", str(z["time"]), z["lat"], z["lon"],
                     {k: z[k] for k in S2_BANDS}, z["valid"], res_m / 1000.0,
                     {"item": item.id, "target": name, "cloud_cover": item.properties.get("eo:cloud_cover")})
    sc = _read_remote(item, lat, lon, half_km, res_m, name)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache, time=sc.time, lat=sc.lat, lon=sc.lon, valid=sc.valid, **sc.bands)
    return sc


def _read_remote(item, lat, lon, half_km, res_m, name) -> Scene:
    epsg =item.properties.get("proj:epsg") or int(str(item.properties.get("proj:code", "EPSG:0")).split(":")[1])
    to_utm = Transformer.from_crs(4326, epsg, always_xy=True)
    x, y = to_utm.transform(lon, lat)
    b = (x - half_km * 1000, y - half_km * 1000, x + half_km * 1000, y + half_km * 1000)
    n = int(2 * half_km * 1000 / res_m)
    bands = {}
    transform = None
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES"):
        for bname, key in ASSET.items():
            a = item.assets[key]
            rb = (a.extra_fields.get("raster:bands") or [{}])[0]
            with rasterio.open(a.href) as src:
                w = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
                arr = src.read(1, window=w, out_shape=(n, n), boundless=True, fill_value=0,
                               resampling=rasterio.enums.Resampling.average).astype("float32")
                if transform is None:
                    transform = rasterio.windows.transform(w, src.transform) * rasterio.Affine.scale(
                        w.width / n, w.height / n)
            nodata = arr == 0
            # Earth Search has already applied the processing-baseline 04.00 BOA offset when
            # "earthsearch:boa_offset_applied" is true; adding it again gives negative reflectance.
            offset = 0.0 if item.properties.get("earthsearch:boa_offset_applied") else rb.get("offset", 0.0)
            arr = arr * rb.get("scale", 1e-4) + offset
            arr[nodata] = np.nan
            bands[bname] = arr
        with rasterio.open(item.assets["scl"].href) as src:
            w = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            scl = src.read(1, window=w, out_shape=(n, n), boundless=True, fill_value=0,
                           resampling=rasterio.enums.Resampling.nearest)
    cols, rows = np.meshgrid(np.arange(n) + 0.5, np.arange(n) + 0.5)
    xs, ys = transform * (cols, rows)
    lon2, lat2 = Transformer.from_crs(epsg, 4326, always_xy=True).transform(xs, ys)
    finite = np.all([np.isfinite(bands[k]) for k in S2_BANDS], axis=0)
    # SCL: 6 = water. 3 shadow, 8/9 cloud, 10 cirrus are masked (and buffered)
    from scipy import ndimage
    cloud = ndimage.binary_dilation(np.isin(scl, [3, 8, 9, 10]), iterations=5)
    valid = finite & (scl == 6) & ~cloud
    return Scene("ESA Sentinel-2 L2A (MSI)", item.datetime.strftime("%Y-%m-%dT%H:%M:%S"),
                 lat2.astype("float32"), lon2.astype("float32"), bands, valid, res_m / 1000.0,
                 {"item": item.id, "target": name, "cloud_cover": item.properties.get("eo:cloud_cover")})
