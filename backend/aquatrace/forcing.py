"""A gridded velocity field (ocean current or 10 m wind) with fast interpolation.

Every data source (OSCAR, MERRA-2, Open-Meteo) is converted into a ``VelocityField`` so the
drift model does not care where the numbers came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from scipy import ndimage
from scipy.interpolate import RegularGridInterpolator


def _fill_nan_nearest(a: np.ndarray) -> np.ndarray:
    """Fill NaNs (land / gaps) in each time slice with the nearest valid value.

    The land polygon decides where particles beach, so the field only needs to be
    finite everywhere for interpolation near the coast.
    """
    out = a.copy()
    for k in range(out.shape[0]):
        sl = out[k]
        mask = ~np.isfinite(sl)
        if mask.all():
            out[k] = 0.0
            continue
        if mask.any():
            idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
            out[k] = sl[tuple(idx)]
    return out


@dataclass
class VelocityField:
    name: str          # "currents" or "wind"
    source: str        # e.g. "NASA OSCAR v2.0 (interim)"
    time: np.ndarray   # datetime64[s], ascending
    lat: np.ndarray    # ascending
    lon: np.ndarray    # ascending
    u: np.ndarray      # (time, lat, lon) eastward m/s, NaN on land
    v: np.ndarray      # (time, lat, lon) northward m/s
    _interp: tuple = field(default=None, repr=False)

    def __post_init__(self):
        order_lat = np.argsort(self.lat)
        order_lon = np.argsort(self.lon)
        self.lat = self.lat[order_lat]
        self.lon = self.lon[order_lon]
        self.u = self.u[:, order_lat][:, :, order_lon].astype("float32")
        self.v = self.v[:, order_lat][:, :, order_lon].astype("float32")
        self.time = np.asarray(self.time).astype("datetime64[s]")

    # --- interpolation -------------------------------------------------------------
    def _build(self):
        t = (self.time - self.time[0]).astype("float64")  # seconds
        u = _fill_nan_nearest(self.u)
        v = _fill_nan_nearest(self.v)
        if len(t) == 1:  # a single snapshot: duplicate so the interpolator has a time axis
            t = np.array([0.0, 1.0])
            u = np.concatenate([u, u])
            v = np.concatenate([v, v])
        grid = (t, self.lat.astype("float64"), self.lon.astype("float64"))
        kw = dict(method="linear", bounds_error=False, fill_value=None)
        self._interp = (RegularGridInterpolator(grid, u, **kw), RegularGridInterpolator(grid, v, **kw), t)

    def at(self, when: np.datetime64, lat: np.ndarray, lon: np.ndarray):
        """Velocity (u, v) in m/s at one time for many points. Outside the time range the
        nearest available time is used (persistence)."""
        if self._interp is None:
            self._build()
        iu, iv, t = self._interp
        ts = float((np.datetime64(when, "s") - self.time[0]).astype("float64"))
        ts = min(max(ts, t[0]), t[-1])
        lat = np.clip(lat, self.lat[0], self.lat[-1])
        lon = np.clip(lon, self.lon[0], self.lon[-1])
        pts = np.column_stack([np.full(lat.shape, ts), lat, lon])
        return iu(pts), iv(pts)

    # --- persistence -----------------------------------------------------------------
    def to_netcdf(self, path: Path):
        ds = xr.Dataset(
            {"u": (("time", "lat", "lon"), self.u), "v": (("time", "lat", "lon"), self.v)},
            coords={"time": self.time.astype("datetime64[ns]"), "lat": self.lat, "lon": self.lon},
            attrs={"name": self.name, "source": self.source},
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        ds.to_netcdf(path)

    @classmethod
    def from_netcdf(cls, path: Path) -> "VelocityField":
        with xr.open_dataset(path) as ds:
            ds = ds.load()
        return cls(ds.attrs["name"], ds.attrs["source"], ds.time.values, ds.lat.values,
                   ds.lon.values, ds.u.values, ds.v.values)

    def summary(self) -> dict:
        speed = np.hypot(self.u, self.v)
        return {
            "name": self.name,
            "source": self.source,
            "start": str(pd.Timestamp(self.time[0])),
            "end": str(pd.Timestamp(self.time[-1])),
            "steps": int(len(self.time)),
            "grid": f"{len(self.lat)} x {len(self.lon)}",
            "resolution_deg": round(float(np.median(np.diff(self.lat))), 3) if len(self.lat) > 1 else None,
            "mean_speed_ms": round(float(np.nanmean(speed)), 3),
        }

    def grid_sample(self, when: np.datetime64, step: int = 2) -> list[dict]:
        """Coarse arrows for the map (lat, lon, u, v)."""
        k = int(np.argmin(np.abs(self.time - np.datetime64(when, "s"))))
        out = []
        for i in range(0, len(self.lat), step):
            for j in range(0, len(self.lon), step):
                u, v = float(self.u[k, i, j]), float(self.v[k, i, j])
                if np.isfinite(u) and np.isfinite(v):
                    out.append({"lat": round(float(self.lat[i]), 3), "lon": round(float(self.lon[j]), 3),
                                "u": round(u, 3), "v": round(v, 3)})
        return out
