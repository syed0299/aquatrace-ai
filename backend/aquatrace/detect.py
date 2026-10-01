"""Potential floating-debris hotspot detection.

Pipeline for any sensor (PACE OCI or Sentinel-2):
  1. Read surface reflectance and resample it to Sentinel-2-equivalent bands
     (PACE is hyperspectral, so each S2 band is an average over its wavelength range).
  2. Mask land, cloud (+ a buffer around clouds), sun glint and bad retrievals.
  3. Spectral indices: FDI (Floating Debris Index, Biermann et al. 2020), FAI, NDVI.
  4. Anomaly score: how far each pixel's FDI sits above its local ocean background (robust z).
  5. Optional ML: Random Forest trained on MARIDA labelled Sentinel-2 pixels gives
     P(floating material).
  6. Group anomalous pixels into hotspots with a confidence score.

Output hotspots are *potential* floating-material hotspots. PACE pixels are ~1 km, so
debris is sub-pixel; the detector flags candidates for follow-up, not confirmed litter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage

from .config import BBOX

S2_BANDS = ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
# Sentinel-2 band wavelength ranges (nm) used to resample PACE hyperspectral reflectance
S2_RANGES = {"B1": (433, 453), "B2": (458, 523), "B3": (543, 578), "B4": (650, 680), "B5": (698, 713),
             "B6": (733, 748), "B7": (773, 793), "B8": (785, 899), "B8A": (855, 875),
             "B11": (1565, 1660), "B12": (2100, 2280)}
WL = {"B4": 664.8, "B6": 740.5, "B8": 832.8, "B11": 1612.0}


@dataclass
class Scene:
    sensor: str
    time: str
    lat: np.ndarray                  # 2-D
    lon: np.ndarray                  # 2-D
    bands: dict                      # S2-equivalent reflectance, 2-D each
    valid: np.ndarray                # 2-D bool: usable open-water pixel
    pixel_km: float
    meta: dict = field(default_factory=dict)


# --- indices ------------------------------------------------------------------------------
def indices(b: dict) -> dict:
    eps = 1e-6
    ndvi = (b["B8"] - b["B4"]) / (b["B8"] + b["B4"] + eps)
    # Floating Debris Index (Biermann et al., 2020)
    fdi = b["B8"] - (b["B6"] + (b["B11"] - b["B6"]) * ((WL["B8"] - WL["B4"]) / (WL["B11"] - WL["B4"])) * 10)
    # Floating Algae Index style baseline (Hu, 2009), adapted to S2 band centres
    fai = b["B8"] - (b["B4"] + (b["B11"] - b["B4"]) * (WL["B8"] - WL["B4"]) / (WL["B11"] - WL["B4"]))
    ndwi = (b["B3"] - b["B8"]) / (b["B3"] + b["B8"] + eps)
    return {"NDVI": ndvi, "FDI": fdi, "FAI": fai, "NDWI": ndwi}


FEATURES = [f"d{k}" for k in S2_BANDS] + ["dFDI", "dFAI", "dNDVI", "dNDWI"]


def feature_stack(b: dict, bg: dict) -> np.ndarray:
    """(n_pixels, 15) background-relative features used by the Random Forest.

    Each band is taken relative to the surrounding open-water background. This removes most of
    the additive difference between processing levels (MARIDA patches vs Sentinel-2 L2A vs PACE
    surface reflectance) and describes what floating material adds on top of the water.
    """
    d = {k: np.asarray(b[k], dtype="float32").ravel() - np.asarray(bg[k], dtype="float32").ravel() for k in S2_BANDS}
    k = (WL["B8"] - WL["B4"]) / (WL["B11"] - WL["B4"])
    fdi = d["B8"] - (d["B6"] + (d["B11"] - d["B6"]) * k * 10)
    fai = d["B8"] - (d["B4"] + (d["B11"] - d["B4"]) * k)
    ndvi = (d["B8"] - d["B4"]) / (np.abs(d["B8"]) + np.abs(d["B4"]) + 1e-3)
    ndwi = (d["B3"] - d["B8"]) / (np.abs(d["B3"]) + np.abs(d["B8"]) + 1e-3)
    cols = [d[b_] for b_ in S2_BANDS] + [fdi, fai, ndvi, ndwi]
    return np.stack(cols, axis=1).astype("float32")


TEXTURE_OF = ["dFDI", "dNDVI", "dB8", "dB2"]


def spatial_features(F2: dict) -> dict:
    """Neighbourhood context: mean / std at 3x3 and 7x7 plus local contrast for key layers.
    Debris lines, ships, waves and foam differ more in shape and texture than in colour."""
    out = {}
    for name in TEXTURE_OF:
        x = np.nan_to_num(F2[name])
        for w in (3, 7):
            m = ndimage.uniform_filter(x, w)
            out[f"{name}_m{w}"] = m
            out[f"{name}_s{w}"] = np.sqrt(np.clip(ndimage.uniform_filter(x * x, w) - m * m, 0, None))
        out[f"{name}_c7"] = x - out[f"{name}_m7"]
    return out


def extra_spatial_features(F2: dict) -> dict:
    """Feature set v2: wider context (15x15) and edge strength (Sobel gradient) - debris often forms
    thin lines (windrows) whose edges are sharper than the surrounding water."""
    out = {}
    for name in ("dFDI", "dNDVI"):
        x = np.nan_to_num(F2[name])
        m = ndimage.uniform_filter(x, 15)
        out[f"{name}_m15"] = m
        out[f"{name}_s15"] = np.sqrt(np.clip(ndimage.uniform_filter(x * x, 15) - m * m, 0, None))
    for name in ("dFDI", "dB8", "dB2"):
        x = np.nan_to_num(F2[name])
        out[f"{name}_grad"] = np.hypot(ndimage.sobel(x, 0), ndimage.sobel(x, 1))
    for name in ("dB4", "dB11"):
        x = np.nan_to_num(F2[name])
        m = ndimage.uniform_filter(x, 7)
        out[f"{name}_s7"] = np.sqrt(np.clip(ndimage.uniform_filter(x * x, 7) - m * m, 0, None))
    return out


def feature_image(bands: dict, bg: dict, spatial: bool = True, extra: bool = False) -> tuple[np.ndarray, list[str]]:
    """(H, W, F) feature image from 2-D band and background arrays (same features as training)."""
    H, W = next(iter(bands.values())).shape
    base = feature_stack({k: np.nan_to_num(bands[k]) for k in S2_BANDS}, {k: np.nan_to_num(bg[k]) for k in S2_BANDS})
    names = list(FEATURES)
    F2 = {n: base[:, j].reshape(H, W) for j, n in enumerate(names)}
    if spatial:
        sp = spatial_features(F2)
        F2.update(sp)
        names += list(sp)
    if extra:
        ex = extra_spatial_features(F2)
        F2.update(ex)
        names += list(ex)
    return np.stack([F2[n] for n in names], axis=-1).astype("float32"), names


def background(bands: dict, valid: np.ndarray, block: int) -> dict:
    """Per-band local open-water background (block median over valid pixels)."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return {k: _block_median(np.where(valid, v, np.nan), block) for k, v in bands.items()}


# --- PACE OCI reader ----------------------------------------------------------------------------
def read_pace(path: Path, bbox=BBOX) -> Scene | None:
    import netCDF4
    nc = netCDF4.Dataset(path)
    nc.set_auto_mask(True)
    nav, geo = nc["navigation_data"], nc["geophysical_data"]
    lat = np.asarray(nav["latitude"][:], dtype="float32")
    lon = np.asarray(nav["longitude"][:], dtype="float32")
    inside = (lat >= bbox["lat_min"]) & (lat <= bbox["lat_max"]) & (lon >= bbox["lon_min"]) & (lon <= bbox["lon_max"])
    if inside.sum() < 1000:
        nc.close()
        return None
    rows = np.flatnonzero(inside.any(axis=1))
    cols = np.flatnonzero(inside.any(axis=0))
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    lat, lon, inside = lat[r0:r1, c0:c1], lon[r0:r1, c0:c1], inside[r0:r1, c0:c1]

    rhos = geo["rhos"]
    wl = None
    for grp in ("sensor_band_parameters",):
        for name in ("wavelength_3d", "wavelength"):
            if grp in nc.groups and name in nc[grp].variables and nc[grp][name].shape[0] == rhos.shape[-1]:
                wl = np.asarray(nc[grp][name][:], dtype="float32")
    if wl is None:
        raise RuntimeError("Could not find the wavelength array for rhos")
    bands = {}
    for bname, (lo_nm, hi_nm) in S2_RANGES.items():
        sel = np.flatnonzero((wl >= lo_nm) & (wl <= hi_nm))
        if sel.size == 0:  # nearest single band (e.g. SWIR has sparse sampling)
            sel = np.array([int(np.argmin(np.abs(wl - (lo_nm + hi_nm) / 2)))])
        cube = rhos[r0:r1, c0:c1, sel[0]:sel[-1] + 1]
        cube = np.ma.filled(np.ma.asarray(cube, dtype="float32"), np.nan)
        cube = cube[:, :, sel - sel[0]]
        bands[bname] = np.nanmean(cube, axis=2)

    bad = ~inside
    flags = geo["l2_flags"]
    data = np.asarray(np.ma.filled(flags[r0:r1, c0:c1], 0)).astype("int64")
    masks = np.atleast_1d(flags.getncattr("flag_masks")).astype("int64")
    meanings = flags.getncattr("flag_meanings").split()
    land = np.zeros(data.shape, bool)
    cloud = np.zeros(data.shape, bool)
    other = np.zeros(data.shape, bool)
    for m, n in zip(masks, meanings):
        hit = (data & int(m)) != 0
        if n == "LAND":
            land |= hit
        elif n in ("CLDICE",):
            cloud |= hit
        elif n in ("HIGLINT", "STRAYLIGHT", "ATMFAIL", "HILT", "NAVFAIL", "PRODFAIL", "HISATZEN", "HISOLZEN"):
            other |= hit
    # Extra brightness test: over open ocean NIR reflectance > 0.06 is haze / thin cloud, not debris
    cloud |= np.nan_to_num(bands["B8A"], nan=1.0) > 0.06
    cloud = ndimage.binary_dilation(cloud, iterations=3)  # cloud edges cause most false alarms
    finite = np.all([np.isfinite(bands[k]) for k in S2_BANDS], axis=0)
    valid = ~bad & ~land & ~cloud & ~other & finite
    t = path.name.split(".")[1]
    nc.close()
    return Scene("NASA PACE OCI (L2 SFREFL)", f"{t[:4]}-{t[4:6]}-{t[6:8]}T{t[9:11]}:{t[11:13]}:{t[13:15]}",
                 lat, lon, bands, valid, 1.2,
                 {"file": path.name, "cloud_fraction": round(float((cloud & ~land & inside).sum() / max(1, (~land & inside).sum())), 3)})


# --- anomaly + hotspots ---------------------------------------------------------------------
def _block_median(a: np.ndarray, block: int) -> np.ndarray:
    """Local background: NaN-aware median over blocks, smoothly upsampled back to full size."""
    ny, nx = a.shape
    py, px = (-ny) % block, (-nx) % block
    p = np.pad(a, ((0, py), (0, px)), constant_values=np.nan)
    blocks = p.reshape(p.shape[0] // block, block, p.shape[1] // block, block).swapaxes(1, 2)
    med = np.nanmedian(blocks.reshape(*blocks.shape[:2], -1), axis=2)
    holes = ~np.isfinite(med)
    if holes.all():
        return np.full(a.shape, np.nanmedian(a))
    if holes.any():
        idx = ndimage.distance_transform_edt(holes, return_distances=False, return_indices=True)
        med = med[tuple(idx)]
    up = ndimage.zoom(med, (p.shape[0] / med.shape[0], p.shape[1] / med.shape[1]), order=1)
    return up[:ny, :nx]


def anomaly_z(fdi: np.ndarray, valid: np.ndarray, window: int) -> np.ndarray:
    """Robust z-score of FDI against its local open-water background."""
    import warnings
    f = np.where(valid, fdi, np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN blocks (land / cloud)
        bg = _block_median(f, window)
    r = f - bg
    mad = np.nanmedian(np.abs(r - np.nanmedian(r)))
    sigma = 1.4826 * mad if mad > 0 else np.nanstd(r)
    return r / (sigma + 1e-9)


def find_hotspots(scene: Scene, rf=None, z_thresh: float = 3.5, max_hotspots: int = 25,
                  min_pixels: int = 2) -> tuple[list[dict], dict, dict]:
    from .sources.coast import coast_distance_km, on_land

    b = scene.bands
    idx = indices(b)
    native_s2 = scene.pixel_km < 0.1          # the RF was trained on this sensor
    window = 41 if not native_s2 else 101
    z = anomaly_z(idx["FDI"], scene.valid, window)
    bg = background(b, scene.valid, window)
    d_fdi = idx["FDI"] - (bg["B8"] - (bg["B6"] + (bg["B11"] - bg["B6"]) * ((WL["B8"] - WL["B4"]) / (WL["B11"] - WL["B4"])) * 10))
    # Very bright pixels in the visible are ships, platforms or cloud fragments, not floating litter
    bright = ((np.nan_to_num(b["B2"] - bg["B2"], nan=1) > 0.06) |
              (np.nan_to_num(b["B11"], nan=1) > 0.10))
    cand = scene.valid & (z >= z_thresh) & (d_fdi > 0) & ~bright
    # Drop the shoreline strip: mixed land/water pixels and port structures mimic floating material
    min_coast_km = 2.5 if not native_s2 else 0.4
    if cand.any():
        ci = np.flatnonzero(cand)
        la, lo = scene.lat.ravel()[ci], scene.lon.ravel()[ci]
        # also drop inland water (backwaters, canals, lakes): this is a *marine* debris product
        drop = (coast_distance_km(la, lo) < min_coast_km) | on_land(la, lo)
        cand.ravel()[ci[drop]] = False

    p_float = np.zeros_like(z, dtype="float32")
    p_debris = np.zeros_like(z, dtype="float32")
    label = np.zeros(z.shape, dtype="int16")
    if rf is not None and cand.any():
        if getattr(rf, "spatial", False):
            X = feature_image(b, bg, spatial=True, extra=getattr(rf, "extra", False))[0][cand]
        else:
            X = feature_stack({k: v[cand] for k, v in b.items()}, {k: v[cand] for k, v in bg.items()})
        proba = rf.predict_proba_groups(X)
        p_float[cand] = proba["floating"]
        p_debris[cand] = proba["debris"]
        label[cand] = proba["label"]
        # Reject what the model recognises as ships, wakes, waves, clouds or cloud shadows
        cand &= ~np.isin(label, list(rf.REJECT))
        if native_s2:  # same sensor as training: require the model to agree it is floating material
            cand &= p_float >= 0.5

    lab, n = ndimage.label(ndimage.binary_dilation(cand, iterations=1) & scene.valid | cand,
                           structure=np.ones((3, 3)))
    hotspots = []
    px_area = scene.pixel_km ** 2
    for k in range(1, n + 1):
        m = (lab == k) & cand
        npx = int(m.sum())
        if npx < min_pixels:
            continue
        w = np.clip(z[m], 0, None)
        clat = float(np.average(scene.lat[m], weights=w))
        clon = float(np.average(scene.lon[m], weights=w))
        zmax = float(np.nanmax(z[m]))
        # log scale so very strong anomalies do not all saturate at 100 %
        anomaly = float(np.clip(np.log10(max(np.nanmean(z[m]), z_thresh) / z_thresh) / 1.5, 0, 1))
        size = float(np.clip(np.log1p(npx) / np.log1p(40), 0, 1))
        ml = float(np.nanmean(p_float[m])) if rf is not None else None
        if ml is None:
            conf = 0.85 * anomaly + 0.15 * size
        elif native_s2:
            conf = 0.45 * anomaly + 0.15 * size + 0.40 * ml
        else:  # 10 m-trained model on ~1 km mixed pixels: supporting evidence only
            conf = 0.65 * anomaly + 0.15 * size + 0.20 * ml
        top = np.bincount(label[m]).argmax() if rf is not None else None
        # A detection right next to an invalid (cloud) region is less trustworthy
        edge = ndimage.binary_dilation(m, iterations=4) & ~scene.valid
        edge_frac = float(edge.sum() / max(1, ndimage.binary_dilation(m, iterations=4).sum()))
        conf *= 1.0 - 0.5 * edge_frac
        hotspots.append({
            "lat": round(clat, 4), "lon": round(clon, 4),
            "pixels": npx, "area_km2": round(npx * px_area, 3),
            "radius_km": round(float(max(scene.pixel_km, np.sqrt(npx * px_area / np.pi))), 2),
            "max_z": round(zmax, 2), "mean_fdi": round(float(np.nanmean(idx["FDI"][m])), 5),
            "mean_ndvi": round(float(np.nanmean(idx["NDVI"][m])), 3),
            "p_floating_ml": None if ml is None else round(ml, 3),
            "p_debris_ml": None if rf is None else round(float(np.nanmean(p_debris[m])), 3),
            "ml_class": None if rf is None else rf.CLASSES.get(int(top), "unknown"),
            "cloud_edge_fraction": round(edge_frac, 3),
            "confidence": round(float(np.clip(conf, 0, 1)), 3),
            "sensor": scene.sensor, "observed": scene.time,
        })
    hotspots.sort(key=lambda h: -h["confidence"])
    hotspots = hotspots[:max_hotspots]
    for i, h in enumerate(hotspots, 1):
        h["id"] = f"HS-{i:02d}"
    stats = {
        "sensor": scene.sensor, "observed": scene.time, "pixel_km": scene.pixel_km,
        "valid_pixels": int(scene.valid.sum()), "candidate_pixels": int(cand.sum()),
        "clusters": int(n), "hotspots": len(hotspots), "z_threshold": z_thresh, **scene.meta,
    }
    return hotspots, stats, {"z": z, "fdi": idx["FDI"]}


# --- map overlays ---------------------------------------------------------------------------
def render_overlays(scene: Scene, z: np.ndarray, outdir: Path, res: float | None = None) -> dict:
    """Grid the swath onto a regular lat/lon raster and write true-colour + anomaly PNGs."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    res = res or (0.012 if scene.pixel_km >= 0.5 else 0.002)
    lat, lon = scene.lat, scene.lon
    ok = np.isfinite(lat) & np.isfinite(lon)
    la0, la1 = float(np.nanmin(lat[ok])), float(np.nanmax(lat[ok]))
    lo0, lo1 = float(np.nanmin(lon[ok])), float(np.nanmax(lon[ok]))
    ny, nx = int((la1 - la0) / res) + 1, int((lo1 - lo0) / res) + 1
    iy = ((la1 - lat[ok]) / res).astype(int).clip(0, ny - 1)
    ix = ((lon[ok] - lo0) / res).astype(int).clip(0, nx - 1)

    def grid(values):
        s = np.zeros((ny, nx)); c = np.zeros((ny, nx))
        v = values[ok]; f = np.isfinite(v)
        np.add.at(s, (iy[f], ix[f]), v[f]); np.add.at(c, (iy[f], ix[f]), 1)
        g = np.where(c > 0, s / np.maximum(c, 1), np.nan)
        # fill 1-2 px gaps between swath samples
        holes = ~np.isfinite(g)
        if holes.any() and (~holes).any():
            d, ind = ndimage.distance_transform_edt(holes, return_indices=True)
            g = np.where(holes & (d <= 2), g[tuple(ind)], g)
        return g

    outdir.mkdir(parents=True, exist_ok=True)
    rgb = np.dstack([grid(scene.bands[k]) for k in ("B4", "B3", "B2")])
    alpha = np.isfinite(rgb).all(axis=2)
    rgb = np.nan_to_num(rgb)
    rgb = np.clip((rgb / 0.12) ** (1 / 2.2), 0, 1)  # simple stretch for ocean scenes
    plt.imsave(outdir / "truecolor.png", np.dstack([rgb, alpha.astype(float)]))

    zg = grid(np.where(scene.valid, z, np.nan))
    cmap = plt.get_cmap("magma")
    zn = np.clip((np.nan_to_num(zg, nan=0) - 1.5) / 6.0, 0, 1)
    img = cmap(zn)
    img[..., 3] = np.where(np.isfinite(zg) & (zg > 1.5), 0.25 + 0.75 * zn, 0)
    plt.imsave(outdir / "anomaly.png", img)
    bounds = [[la0, lo0], [la1, lo1]]
    return {"truecolor": "truecolor.png", "anomaly": "anomaly.png", "bounds": bounds}
