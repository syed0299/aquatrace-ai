"""Evidence figures: how AquaTrace identifies floating debris, from the raw satellite data.

    cd backend && ../.venv/bin/python ../docs/evidence/make_evidence.py

Writes docs/evidence/e_pixels.png, e_spectra.png, e_marida.png and evidence.json (the numbers quoted with them).
Needs the cached Sentinel-2 scenes (data/processed/s2) and MARIDA (data/raw/marida) for the reference curves.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from pyproj import Transformer  # noqa: E402

from aquatrace.config import PROCESSED  # noqa: E402
from aquatrace.detect import S2_BANDS, anomaly_z, background, feature_image, indices  # noqa: E402
from aquatrace.marida import CLASSES, FLOATING, MARIDA, load_model  # noqa: E402

OUT = Path(__file__).resolve().parent
INK, INK2, GRID = "#0B1F3A", "#52514E", "#E6E8EC"
WATER, DEBRIS, ALGAE = "#2a78d6", "#eb6834", "#1baf7a"  # validated categorical slots (light surface)
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.titlesize": 9.5, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "figure.dpi": 250, "savefig.dpi": 250,
})
WAVE = {"B1": 443, "B2": 490, "B3": 560, "B4": 665, "B5": 705, "B6": 740, "B7": 783, "B8": 842, "B8A": 865,
        "B11": 1610, "B12": 2190}
SHOW = ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"]
LABEL = {"B2": "blue", "B3": "green", "B4": "red", "B5": "red\nedge", "B6": "", "B7": "", "B8": "near-\ninfrared",
         "B8A": "", "B11": "SWIR", "B12": ""}

# hotspots from the saved runs (Sentinel-2 scenes cached by the pipeline)
DEBRIS_HS = dict(run="20260314_pace", id="HS-04", scene="S2C_44QQE_20260312_1_L2A_17.65_83.35_15km_20m.npz",
                 lat=17.7186, lon=83.4536, name="HS-04, 9 km off Visakhapatnam")
VEG_HS = dict(run="20260305_s2", id="HS-06", scene="S2B_45QXD_20260304_0_L2A_21.55_88.15_15km_20m.npz",
              lat=21.5854, lon=88.1873, name="HS-06, Hooghly estuary")
MARIDA_PATCH = "27-1-19_16PCC_28"


def load_scene(fname):
    z = np.load(PROCESSED / "s2" / fname)
    b = {k: z[k].astype("float64") for k in S2_BANDS}
    return b, z["valid"], z["lat"], z["lon"], str(z["time"])


def hotspot_pixels(hs, half=3):
    """Spectrum of the hotspot's anomalous pixels and of the local water background, plus a chip for display."""
    b, valid, lat, lon, t = load_scene(hs["scene"])
    idx = indices(b)
    bg = background(b, valid, 101)
    z = anomaly_z(idx["FDI"], valid, 101)
    d = (lat - hs["lat"]) ** 2 + ((lon - hs["lon"]) * np.cos(np.deg2rad(hs["lat"]))) ** 2
    i, j = np.unravel_index(np.argmin(d), d.shape)
    win = (slice(i - half, i + half + 1), slice(j - half, j + half + 1))
    hot = z[win] >= 3.5
    spec = {k: float(b[k][win][hot].mean()) for k in S2_BANDS}
    water = {k: float(np.nanmean(bg[k][win][hot])) for k in S2_BANDS}
    return dict(b=b, z=z, lat=lat, i=i, j=j, hot_win=hot, half=half, time=t, spec=spec, water=water,
                n=int(hot.sum()), fdi=float(idx["FDI"][win][hot].mean()), zmax=float(z[win].max()))


def stretch(rgb, mask):
    lo, hi = np.percentile(rgb[mask], 1), np.percentile(rgb[mask], 99.7)
    return np.clip((rgb - lo) / (hi - lo), 0, 1)


def fig_pixels(hp, out, figsize=(5.4, 2.95)):
    """True colour and FDI anomaly around the hotspot at native 20 m pixels."""
    r = 30  # 61 x 61 px = 1.2 km
    i, j, h = hp["i"], hp["j"], hp["half"]
    sl = (slice(i - r, i + r + 1), slice(j - r, j + r + 1))
    rgb = np.dstack([hp["b"][k][sl] for k in ("B4", "B3", "B2")])
    rgb = stretch(rgb, np.ones(rgb.shape[:2], bool))
    hot = np.zeros(rgb.shape[:2], bool)
    hot[r - h:r + h + 1, r - h:r + h + 1] = hp["hot_win"]
    ys, xs = np.nonzero(hot)
    flip = hp["lat"][0, 0] < hp["lat"][-1, 0]  # put north up
    fig, axes = plt.subplots(1, 2, figsize=figsize)
    for ax, img, title in ((axes[0], rgb, "Real image"),
                           (axes[1], np.clip(hp["z"][sl], -3, 30), "Debris signal (FDI)")):
        if flip:
            img = img[::-1]
        kw = {} if img.ndim == 3 else dict(cmap="Oranges", vmin=0, vmax=30)
        im = ax.imshow(img, interpolation="nearest", **kw)
        y0 = (2 * r - ys.max()) if flip else ys.min()
        ax.add_patch(Rectangle((xs.min() - 1.5, y0 - 1.5), xs.max() - xs.min() + 3, ys.max() - ys.min() + 3,
                               fill=False, ec="#E5383B" if img.ndim == 3 else INK, lw=1.4))
        ax.set_title(title, loc="left", pad=4)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        ax.plot([3, 13], [2 * r - 3, 2 * r - 3], color="white" if img.ndim == 3 else INK, lw=2.2)
        ax.text(8, 2 * r - 5, "200 m", ha="center", va="bottom", fontsize=7.5, color="white" if img.ndim == 3 else INK)
    cb = fig.colorbar(im, ax=axes[1], fraction=0.046, pad=0.03)
    cb.set_label("σ above the water around it", fontsize=7.5)
    cb.outline.set_visible(False)
    fig.text(0.01, 0.02, f"Sentinel-2, {hp['time'][:16].replace('T', ' ')} UTC · 20 m pixels · boxed: {hp['n']} "
             f"flagged (≈{hp['n'] * 400:,} m²)", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    fig.savefig(out)
    plt.close(fig)


def marida_spectra():
    acc = {}
    for pid in (MARIDA / "splits" / "train_X.txt").read_text().split():
        base = MARIDA / "patches" / ("S2_" + pid.rsplit("_", 1)[0]) / f"S2_{pid}"
        with rasterio.open(f"{base}.tif") as s:
            img = np.nan_to_num(s.read().astype("float64"))
        with rasterio.open(f"{base}_cl.tif") as s:
            cl = s.read(1).astype(int)
        for c in (1, 2, 5, 7, 9):
            m = cl == c
            if m.any():
                a = acc.setdefault(c, [np.zeros(len(S2_BANDS)), 0])
                a[0] += img[:, m].sum(axis=1)
                a[1] += int(m.sum())
    return {CLASSES[c]: ({k: float(v) for k, v in zip(S2_BANDS, s / n)}, n) for c, (s, n) in acc.items()}


def fig_spectra(ref, deb, veg, out, figsize=(5.4, 3.3), legend_cols=3):
    x = np.arange(len(SHOW))
    fig, ax = plt.subplots(figsize=figsize)
    ax.axvspan(5.5, 7.5, color="#F3F6F9", lw=0, zorder=0)
    ax.text(6.5, 0.197, "near-infrared:\nwater absorbs it", ha="center", va="top", fontsize=6.8, color=INK2)
    series = [
        (ref["Marine Water"][0], WATER, "-", None, "water (labelled)"),
        (ref["Marine Debris"][0], DEBRIS, "-", None, "marine debris (labelled)"),
        (ref["Dense Sargassum"][0], ALGAE, "-", None, "floating algae (labelled)"),
        (deb["spec"], DEBRIS, (0, (3, 2)), "o", "our HS-04, Visakhapatnam"),
        (veg["spec"], ALGAE, (0, (3, 2)), "s", "our HS-06, Hooghly"),
    ]
    for spec, color, ls, mk, label in series:
        ax.plot(x, [spec[k] for k in SHOW], color=color, ls=ls, lw=2, marker=mk, ms=4.5, mec="white", mew=0.8,
                label=label)
    # direct labels in text ink (identity also carried by colour + line style + legend)
    ax.text(2.95, 0.15, "algae: jumps at\nthe red edge", ha="right", va="center", fontsize=7, color=INK)
    ax.text(3.85, 0.068, "debris: flat and bright", ha="left", va="center", fontsize=7, color=INK)
    ax.text(5.6, 0.024, "water: dark", ha="left", va="center", fontsize=7, color=INK)
    ax.set_xticks(x, [f"{LABEL[k]}\n{WAVE[k]}" if LABEL[k] else f"\n{WAVE[k]}" for k in SHOW], fontsize=6.5)
    ax.set_xlabel("band (wavelength, nm)", fontsize=7.5)
    ax.set_ylabel("reflectance (share of sunlight)", fontsize=7.5)
    ax.set_ylim(0, 0.2)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32), fontsize=6.4, ncol=legend_cols, handlelength=2.6, columnspacing=1.2)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def fig_marida(out, figsize=(5.4, 2.95)):
    """A MARIDA test patch the model never saw: expert labels vs the model's prediction."""
    m = load_model()
    base = MARIDA / "patches" / ("S2_" + MARIDA_PATCH.rsplit("_", 1)[0]) / f"S2_{MARIDA_PATCH}"
    with rasterio.open(f"{base}.tif") as s:
        img = np.nan_to_num(s.read().astype("float32"))
        bounds, crs = s.bounds, s.crs
    with rasterio.open(f"{base}_cl.tif") as s:
        cl = s.read(1).astype(int)
    med = np.median(img.reshape(img.shape[0], -1), axis=1)
    bands = {k: img[i] for i, k in enumerate(S2_BANDS)}
    bg = {k: np.full(img.shape[1:], med[i], dtype="float32") for i, k in enumerate(S2_BANDS)}
    F, _ = feature_image(bands, bg, spatial=True, extra=m.extra)
    pred = m.predict_proba_groups(F.reshape(-1, F.shape[-1]))["label"].reshape(cl.shape)
    lon, lat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform(
        (bounds.left + bounds.right) / 2, (bounds.top + bounds.bottom) / 2)

    deb, wat = cl == 1, (cl > 0) & ~np.isin(cl, FLOATING)
    found = int((pred[deb] == 1).sum())
    false_alarm = int(np.isin(pred[wat], FLOATING).sum())
    ys, xs = np.nonzero(deb)
    pad = 28
    size = max(ys.max() - ys.min(), xs.max() - xs.min()) + 2 * pad  # square crop around the debris line
    cy, cx = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
    y0 = int(np.clip(cy - size // 2, 0, cl.shape[0] - size)); y1 = y0 + size
    x0 = int(np.clip(cx - size // 2, 0, cl.shape[1] - size)); x1 = x0 + size
    sl = (slice(y0, y1), slice(x0, x1))
    rgb = stretch(np.dstack([bands[k] for k in ("B4", "B3", "B2")]), np.ones(cl.shape, bool))[sl]

    fig, axes = plt.subplots(1, 2, figsize=figsize)
    for ax, title in zip(axes, ("Experts' labels", "AquaTrace prediction")):
        ax.imshow(rgb, interpolation="nearest")
        ax.set_title(title, loc="left", pad=4)
        ax.set_xticks([]); ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
    ov = np.zeros(rgb.shape[:2] + (4,))
    ov[deb[sl]] = matplotlib.colors.to_rgba(DEBRIS, 1.0)
    axes[0].imshow(ov, interpolation="nearest")
    ov2 = np.zeros(rgb.shape[:2] + (4,))
    ov2[pred[sl] == 1] = matplotlib.colors.to_rgba(DEBRIS, 1.0)
    ov2[np.isin(pred[sl], [2, 3])] = matplotlib.colors.to_rgba(ALGAE, 1.0)
    axes[1].imshow(ov2, interpolation="nearest")
    h = (y1 - y0)
    for ax in axes:
        ax.plot([4, 14], [h - 4, h - 4], color="white", lw=2.2)
        ax.text(4, h - 6, "100 m", ha="left", va="bottom", fontsize=7.5, color="white")
    fig.text(0.01, 0.02, f"orange = marine debris · {found} of {int(deb.sum())} found · "
             f"{false_alarm} of {int(wat.sum())} water pixels flagged", fontsize=7, color=INK2)
    fig.tight_layout(rect=(0, 0.05, 1, 0.97))
    fig.savefig(out)
    plt.close(fig)
    return dict(patch=MARIDA_PATCH, lat=round(lat, 2), lon=round(lon, 2), debris_labelled=int(deb.sum()),
                debris_found=found, water_labelled=int(wat.sum()), water_flagged_floating=false_alarm,
                date=MARIDA_PATCH.split("_")[0])


def main():
    deb, veg = hotspot_pixels(DEBRIS_HS), hotspot_pixels(VEG_HS, half=15)
    fig_pixels(deb, OUT / "e_pixels.png")
    ref = marida_spectra()
    fig_spectra(ref, deb, veg, OUT / "e_spectra.png")
    mp = fig_marida(OUT / "e_marida.png")
    # slide versions: smaller canvas, so the text is larger once scaled to a deck panel
    fig_pixels(deb, OUT / "s_pixels.png", figsize=(4.0, 2.6))
    fig_spectra(ref, deb, veg, OUT / "s_spectra.png", figsize=(4.0, 3.15), legend_cols=2)
    fig_marida(OUT / "s_marida.png", figsize=(4.0, 2.6))
    nums = {
        "debris_hotspot": {**{k: v for k, v in DEBRIS_HS.items()}, "pixels": deb["n"], "time": deb["time"],
                           "fdi": round(deb["fdi"], 4), "z_max": round(deb["zmax"], 1),
                           "spectrum": {k: round(v, 4) for k, v in deb["spec"].items()},
                           "water": {k: round(v, 4) for k, v in deb["water"].items()}},
        "vegetation_hotspot": {**{k: v for k, v in VEG_HS.items()}, "pixels": veg["n"], "time": veg["time"],
                               "spectrum": {k: round(v, 4) for k, v in veg["spec"].items()},
                               "water": {k: round(v, 4) for k, v in veg["water"].items()}},
        "marida_reference": {c: {"pixels": n, "spectrum": {k: round(v, 4) for k, v in s.items()}} for c, (s, n) in ref.items()},
        "marida_patch_check": mp,
    }
    (OUT / "evidence.json").write_text(json.dumps(nums, indent=2))
    print(json.dumps({"debris_hotspot_pixels": deb["n"], "veg_pixels": veg["n"], "marida": mp}, indent=2))


if __name__ == "__main__":
    main()
