"""Charts for the technical report (matplotlib, print-friendly, validated palette)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK = "#0B1F3A"
INK2 = "#52514E"
GRID = "#E6E8EC"
BLUE = "#2A78D6"      # categorical slot 1
ORANGE = "#EB6834"    # categorical slot 2
GREY = "#B4B2A9"      # de-emphasis
H24 = "#7AA9E3"       # ordinal light (+24 h)
H48 = "#1F5FAE"       # ordinal dark (+48 h)

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.titlesize": 10, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False, "figure.dpi": 200, "savefig.dpi": 200,
})


def _bar_labels(ax, bars, fmt, color=INK, dy=0.6):
    for b in bars:
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() + dy, fmt.format(b.get_height()),
                ha="center", va="bottom", fontsize=8, color=color)


def model_improvement(series, out: Path):
    """series: [(label, (accuracy, floating F1, debris F1, macro F1)), ...] oldest first; the last is highlighted."""
    cats = ["Accuracy", "Floating F1", "Debris F1", "Macro F1"]
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    x = range(len(cats))
    k = len(series)
    w = 0.8 / k
    shades = [GREY, H24, BLUE][-k:]
    for j, (label, vals) in enumerate(series):
        bars = ax.bar([i - 0.4 + w * (j + 0.5) for i in x], vals, w - 0.02, color=shades[j], label=label)
        if j == k - 1:
            _bar_labels(ax, bars, "{:.1f}")
    ax.set_xticks(list(x), cats)
    ax.set_ylim(0, 105)
    ax.set_ylabel("score (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.22), ncol=k, fontsize=7.5)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def per_class_f1(rows, out: Path, highlight):
    rows = sorted(rows, key=lambda r: r[1])
    names = [r[0] for r in rows]
    vals = [r[1] for r in rows]
    fig, ax = plt.subplots(figsize=(6.2, 4.1))
    colors = [BLUE if n in highlight else GREY for n in names]
    bars = ax.barh(names, vals, height=0.62, color=colors)
    for b, v in zip(bars, vals):
        ax.text(v + 0.012, b.get_y() + b.get_height() / 2, f"{v:.2f}", va="center", fontsize=7.5, color=INK)
    ax.set_xlim(0, 1.08)
    ax.set_xlabel("F1 score on the MARIDA test split")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def reliability(cal, out: Path):
    fig, ax = plt.subplots(figsize=(4.6, 3.4))
    ax.plot([0, 1], [0, 1], color="#9AA3AF", lw=1, ls=(0, (4, 3)), label="Perfect calibration")
    for key, color, label in (("floating_material", BLUE, "Floating material"), ("marine_debris", ORANGE, "Marine debris")):
        pts = [c for c in cal[key]["curve"] if c["n"] >= 20]
        ax.plot([c["confidence"] for c in pts], [c["observed"] for c in pts], color=color, lw=2,
                marker="o", ms=4.5, mec="white", mew=1.2, label=f"{label} (ECE {cal[key]['ece'] * 100:.1f}%)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("stated confidence (model probability)")
    ax.set_ylabel("observed frequency")
    ax.legend(loc="upper left", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def drift_errors(val, out: Path):
    cats = ["Snapshot\n(debris stays put)", "Currents only", "AquaTrace\n(currents + wind)"]
    keys = ["persistence", "currents_only", "summary"]
    v24 = [val[k]["24"]["median_km"] for k in keys]
    v48 = [val[k]["48"]["median_km"] for k in keys]
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    x = range(3)
    w = 0.32
    b1 = ax.bar([i - w / 2 - 0.01 for i in x], v24, w, color=H24, label="+24 h")
    b2 = ax.bar([i + w / 2 + 0.01 for i in x], v48, w, color=H48, label="+48 h")
    _bar_labels(ax, list(b1) + list(b2), "{:.1f}", dy=0.8)
    ax.set_xticks(list(x), cats)
    ax.set_ylabel("median position error (km)")
    ax.set_ylim(0, max(v48) * 1.18)
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper right", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def windage(w, out: Path):
    xs = [r["windage"] * 100 for r in w["results"]]
    e24 = [r["median_24_km"] for r in w["results"]]
    e48 = [r["median_48_km"] for r in w["results"]]
    fig, ax = plt.subplots(figsize=(6.2, 2.7))
    ax.plot(xs, e48, color=H48, lw=2, marker="o", ms=4.5, mec="white", mew=1.2, label="+48 h")
    ax.plot(xs, e24, color=H24, lw=2, marker="o", ms=4.5, mec="white", mew=1.2, label="+24 h")
    best = min(w["results"], key=lambda r: r["median_48_km"])
    ax.annotate(f"best: {best['windage'] * 100:.0f}% of wind speed\n{best['median_48_km']:.1f} km at +48 h",
                xy=(best["windage"] * 100, best["median_48_km"]), xytext=(best["windage"] * 100 + 0.55, best["median_48_km"] + 4.5),
                fontsize=7.5, color=INK, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.axvspan(1, 3, color=H24, alpha=0.10, lw=0)
    top = max(e48) + 2.5
    ax.set_ylim(min(e24) - 3, top + 3)
    ax.text(2, top, "ensemble range 1–3%", ha="center", fontsize=7, color=INK2)
    ax.set_xlabel("windage (share of 10 m wind speed added to the current, %)")
    ax.set_ylabel("median error (km)")
    ax.legend(loc="upper right", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def cone_coverage(before, after, out: Path):
    """90 % cone hit rate (%) on the held-out month at +24 h / +48 h, before and after tuning, vs the 90 % target."""
    cats = ["+24 h", "+48 h"]
    fig, ax = plt.subplots(figsize=(6.2, 2.7))
    x = range(2)
    w = 0.32
    b1 = ax.bar([i - w / 2 - 0.01 for i in x], before, w, color=GREY, label="Before: diffusion only (K = 20 m²/s)")
    b2 = ax.bar([i + w / 2 + 0.01 for i in x], after, w, color=BLUE, label="After: + per-particle current error")
    _bar_labels(ax, list(b1) + list(b2), "{:.0f}%", dy=1.2)
    ax.axhline(90, color=ORANGE, lw=1.2, ls=(0, (4, 3)))
    ax.text(-0.48, 92, "target 90%", ha="left", va="bottom", fontsize=7.5, color=INK2)
    ax.set_xticks(list(x), cats)
    ax.set_ylim(0, 105)
    ax.set_ylabel("buoys inside the 90% cone (%)")
    ax.grid(axis="x", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.2), ncol=2, fontsize=7.5)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def windage_tuning(tuning, out: Path):
    """Median buoy error vs windage on the January tuning month (current scale 1.0)."""
    rows = [r for r in tuning["stage1"][1:] if r["cscale"] == 1.0]
    xs = [r["windage"][0] * 100 for r in rows]
    e24 = [r["24"]["median_km"] for r in rows]
    e48 = [r["48"]["median_km"] for r in rows]
    fig, ax = plt.subplots(figsize=(6.2, 2.7))
    ax.plot(xs, e48, color=H48, lw=2, marker="o", ms=4.5, mec="white", mew=1.2, label="+48 h")
    ax.plot(xs, e24, color=H24, lw=2, marker="o", ms=4.5, mec="white", mew=1.2, label="+24 h")
    best = min(rows, key=lambda r: r["24"]["median_km"] + r["48"]["median_km"])
    bx, by = best["windage"][0] * 100, best["48"]["median_km"]
    ax.annotate(f"best: {bx:.1f}% of wind speed\n{by:.1f} km at +48 h", xy=(bx, by), xytext=(bx - 1.1, by + 4.5),
                fontsize=7.5, color=INK, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    lo, hi = tuning["chosen"]["windage"]
    ax.axvspan(lo * 100, hi * 100, color=H24, alpha=0.12, lw=0)
    ax.set_ylim(min(e24) - 3, max(e48) + 8)
    ax.text((lo + hi) * 50, max(e48) + 5, f"ensemble {lo * 100:.0f}–{hi * 100:.0f}%", ha="center", fontsize=7, color=INK2)
    ax.set_xlabel("windage (share of 10 m wind speed added to the current, %)")
    ax.set_ylabel("median error (km)")
    ax.legend(loc="upper right", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
