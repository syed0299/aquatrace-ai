"""Confidence calibration ("TRUST" on the deck): when the model says 80 %, is it right ~80 % of the time?

Uses the MARIDA test-split probabilities saved by marida.train(). Reports a reliability curve,
expected calibration error (ECE) and Brier score for P(floating material) and P(marine debris).

    python -m aquatrace.calibration
"""
from __future__ import annotations

import json

import numpy as np

from .config import MODELS
from .marida import FLOATING


def reliability(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges) - 1, 0, bins - 1)
    curve, ece = [], 0.0
    for b in range(bins):
        m = idx == b
        if not m.any():
            continue
        conf, acc, n = float(p[m].mean()), float(y[m].mean()), int(m.sum())
        curve.append({"bin": [round(edges[b], 2), round(edges[b + 1], 2)], "confidence": round(conf, 3),
                      "observed": round(acc, 3), "n": n})
        ece += n / len(p) * abs(conf - acc)
    return {"curve": curve, "ece": round(float(ece), 4), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "positives": int(y.sum()), "n": int(len(y))}


def run() -> dict:
    z = np.load(MODELS / "marida_test_proba.npz")
    y = z["y"]
    out = {
        "floating_material": reliability(z["p_floating"], np.isin(y, FLOATING).astype(float)),
        "marine_debris": reliability(z["p_debris"], (y == 1).astype(float)),
        "note": "MARIDA test split; ECE = average gap between stated confidence and observed frequency.",
    }
    (MODELS / "calibration.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    r = run()
    for k in ("floating_material", "marine_debris"):
        print(k, "ECE", r[k]["ece"], "Brier", r[k]["brier"])
        for c in r[k]["curve"]:
            print(f"   stated {c['confidence']:.2f} -> observed {c['observed']:.2f}  (n={c['n']})")
