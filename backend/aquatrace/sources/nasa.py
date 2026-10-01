"""NASA Earthdata sources named in the deck: PACE OCI SFREFL, OSCAR v2.0 and MERRA-2.

All three need a (free) Earthdata login stored in ~/.netrc. ``logged_in()`` is checked first
so the pipeline can fall back to open sources when no credentials are present.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import xarray as xr

from ..config import BBOX, RAW
from ..forcing import VelocityField

OSCAR_PRODUCTS = ["OSCAR_L4_OC_FINAL_V2.0", "OSCAR_L4_OC_INTERIM_V2.0", "OSCAR_L4_OC_NRT_V2.0"]
PACE_SFREFL = "PACE_OCI_L2_SFREFL"
# NASA cloud OPeNDAP (Hyrax); DAP4 constraint expressions return only the Bay of Bengal subset
MERRA2_OPENDAP = ("https://opendap.earthdata.nasa.gov/collections/C1276812863-GES_DISC/granules/"
                  "M2T1NXSLV.5.12.4%3AMERRA2_{stream}.tavg1_2d_slv_Nx.{date}.nc4")


@lru_cache(maxsize=1)
def logged_in() -> bool:
    netrc = Path.home() / ".netrc"
    if not netrc.exists() or "urs.earthdata.nasa.gov" not in netrc.read_text(errors="ignore"):
        return False
    try:
        import earthaccess
        auth = earthaccess.login(strategy="netrc")
        return bool(auth and auth.authenticated)
    except Exception:
        return False


def _bbox_tuple(pad: float = 0.0):
    return (BBOX["lon_min"] - pad, BBOX["lat_min"] - pad, BBOX["lon_max"] + pad, BBOX["lat_max"] + pad)


# --- OSCAR v2.0 surface currents -------------------------------------------------------------
def oscar(start: date, end: date) -> VelocityField:
    import earthaccess
    outdir = RAW / "oscar"
    outdir.mkdir(parents=True, exist_ok=True)
    temporal = (start.isoformat(), (end + timedelta(days=1)).isoformat())
    granules, product = [], None
    for sn in OSCAR_PRODUCTS:  # most accurate product that covers the dates wins
        granules = earthaccess.search_data(short_name=sn, temporal=temporal)
        if granules:
            product = sn
            break
    if not granules:
        raise RuntimeError(f"No OSCAR granules for {start}..{end}")
    files = earthaccess.download(granules, str(outdir))
    parts = []
    for f in sorted(files):  # one daily file each; subset before concatenating
        with xr.open_dataset(f) as one:
            # OSCAR v2 keeps lon/lat as plain coordinates on "longitude"/"latitude" dimensions
            if "longitude" in one.dims and "lon" in one.coords:
                one = one.swap_dims({"longitude": "lon", "latitude": "lat"})
            one = one.sortby(["lat", "lon"])
            parts.append(one[["u", "v"]].sel(lon=slice(BBOX["lon_min"] - 1, BBOX["lon_max"] + 1),
                                             lat=slice(BBOX["lat_min"] - 1, BBOX["lat_max"] + 1)).load())
    ds = xr.concat(parts, dim="time").sortby("time")
    lat_name, lon_name = "lat", "lon"
    u = ds["u"].transpose("time", lat_name, lon_name).values
    v = ds["v"].transpose("time", lat_name, lon_name).values
    tag = product.split("_")[3].lower()  # final / interim / nrt
    # OSCAR's daily mean is stamped 00:00; centre it at noon. Times may be cftime objects.
    times = np.array([np.datetime64(str(t)[:19]) for t in ds.time.values]) + np.timedelta64(12, "h")
    return VelocityField("currents", f"NASA OSCAR v2.0 ({tag}) surface currents, 0.25 deg daily",
                         times, ds[lat_name].values, ds[lon_name].values, u, v)


# --- MERRA-2 10 m wind (OPeNDAP subset so we only download the Bay of Bengal) -------------------
def _merra_stream(d: date) -> str:
    return "400" if d.year >= 2011 else "300" if d.year >= 2001 else "200" if d.year >= 1992 else "100"


def merra2_wind(start: date, end: date) -> VelocityField:
    import earthaccess
    session = earthaccess.get_requests_https_session()
    outdir = RAW / "merra2"
    outdir.mkdir(parents=True, exist_ok=True)
    # MERRA-2 grid: lat = -90 + 0.5 j, lon = -180 + 0.625 i
    j0 = int(np.floor((BBOX["lat_min"] - 1 + 90) / 0.5)); j1 = int(np.ceil((BBOX["lat_max"] + 1 + 90) / 0.5))
    i0 = int(np.floor((BBOX["lon_min"] - 1 + 180) / 0.625)); i1 = int(np.ceil((BBOX["lon_max"] + 1 + 180) / 0.625))
    sub = f"[0:1:23][{j0}:1:{j1}][{i0}:1:{i1}]"
    ce = f"/U10M{sub};/V10M{sub};/lat[{j0}:1:{j1}];/lon[{i0}:1:{i1}];/time[0:1:23]"
    parts = []
    d = start
    while d <= end:
        path = outdir / f"merra2_wind_{d:%Y%m%d}.nc"
        if not path.exists():
            r = None
            # MERRA-2 days are occasionally re-processed under stream 401
            for stream in (_merra_stream(d), "401"):
                r = session.get(MERRA2_OPENDAP.format(stream=stream, date=f"{d:%Y%m%d}") + ".dap.nc4",
                                params={"dap4.ce": ce}, timeout=300)
                if r.status_code == 200 and r.content[:4] == b"\x89HDF":
                    break
            if r.status_code != 200 or r.content[:4] != b"\x89HDF":
                raise RuntimeError(f"MERRA-2 OPeNDAP {r.status_code} for {d}: {r.text[:200]} "
                                   "(approve 'NASA GESDISC DATA ARCHIVE' in your Earthdata profile)")
            path.write_bytes(r.content)
        parts.append(xr.open_dataset(path).load())
        d += timedelta(days=1)
    ds = xr.concat(parts, dim="time")
    return VelocityField("wind", "NASA MERRA-2 (M2T1NXSLV) 10 m wind, 0.5 x 0.625 deg hourly",
                         ds.time.values, ds.lat.values, ds.lon.values, ds.U10M.values, ds.V10M.values)


# --- PACE OCI L2 surface reflectance --------------------------------------------------------
def _bay_coverage(g) -> float:
    """Fraction of the pilot region inside a granule's footprint."""
    from shapely.geometry import Polygon, box
    try:
        pts = g["umm"]["SpatialExtent"]["HorizontalSpatialDomain"]["Geometry"]["GPolygons"][0]["Boundary"]["Points"]
    except (KeyError, IndexError):
        return 0.0
    region = box(*_bbox_tuple())
    poly = Polygon([(p["Longitude"], p["Latitude"]) for p in pts]).buffer(0)
    return poly.intersection(region).area / region.area


def pace_search(day: date, max_cloud: float = 60.0):
    """PACE OCI SFREFL granules over the pilot region on one day, best first
    (region coverage x clear-sky fraction)."""
    import earthaccess
    results = earthaccess.search_data(
        short_name=PACE_SFREFL,
        temporal=(day.isoformat(), (day + timedelta(days=1)).isoformat()),
        bounding_box=_bbox_tuple(),
        cloud_cover=(0, max_cloud),
    )
    score = lambda g: _bay_coverage(g) * (1 - (g["umm"].get("CloudCover") or 100) / 100)
    return [g for g in sorted(results, key=score, reverse=True) if _bay_coverage(g) > 0.05]


def pace_search_recent(t0: datetime, t1: datetime, short_name: str = "PACE_OCI_L2_SFREFL_NRT",
                       min_coverage: float = 0.15):
    """Latest passes between t0 and t1 (near-real-time product: online ~3 h after the pass),
    best first by region coverage x clear-sky fraction."""
    import earthaccess
    results = earthaccess.search_data(short_name=short_name,
                                      temporal=(t0.strftime("%Y-%m-%dT%H:%M:%S"), t1.strftime("%Y-%m-%dT%H:%M:%S")),
                                      bounding_box=_bbox_tuple())
    score = lambda g: _bay_coverage(g) * (1 - (g["umm"].get("CloudCover") or 100) / 100)
    return [g for g in sorted(results, key=score, reverse=True) if _bay_coverage(g) >= min_coverage]


def pace_download(granules, limit: int = 2) -> list[Path]:
    import earthaccess
    outdir = RAW / "pace"
    outdir.mkdir(parents=True, exist_ok=True)
    paths, todo = [], []
    for g in granules[:limit]:
        p = outdir / g["umm"]["GranuleUR"]
        if p.exists() and p.stat().st_size > 1e6:
            paths.append(p)
        else:
            todo.append(g)
    if todo:
        paths += [Path(f) for f in earthaccess.download(todo, str(outdir))]
    return sorted(paths)


def granule_time(path: Path) -> datetime:
    # PACE_OCI.20260303T071404.L2.SFREFL.V3_1.nc
    return datetime.strptime(path.name.split(".")[1], "%Y%m%dT%H%M%S")
