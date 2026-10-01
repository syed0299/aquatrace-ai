"""Round-2 model selection on MARIDA, scored on the *validation* split only (test split untouched).

Tries: extended texture features (v2), more training pixels, a soft-voting ensemble, a
debris-specific decision threshold, and the two-expert hybrid (Extra Trees decides floating material,
the soft vote names the other classes) - the hybrid won and is what marida.train() builds.

    python -m aquatrace.experiments_v2      # writes models/experiments_v2_val.json
"""
from __future__ import annotations

import json
import time

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier

from .config import MODELS, RANDOM_SEED
from .experiments import evaluate
from .marida import _cap, hybrid_predict, load_split


def et(n=500):
    return ExtraTreesClassifier(n, min_samples_leaf=2, n_jobs=-1, class_weight="balanced_subsample", random_state=RANDOM_SEED)


def hgb():
    return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.08, max_leaf_nodes=63, l2_regularization=1.0,
                                          class_weight="balanced", early_stopping=False, random_state=RANDOM_SEED)


def predict_with_threshold(proba, classes, debris_t=None):
    """argmax, except: call a pixel Marine Debris whenever P(debris) >= debris_t."""
    pred = classes[proba.argmax(axis=1)]
    if debris_t is not None:
        k = list(classes).index(1)
        pred = np.where(proba[:, k] >= debris_t, 1, pred)
    return pred


def main():
    rng = np.random.default_rng(RANDOM_SEED)
    results, probas = [], {}

    def log(name, y, pred, secs, extra=None):
        row = {"name": name, **evaluate(y, pred), "seconds": round(secs, 1), **(extra or {})}
        results.append(row)
        print(json.dumps({k: (v["f1"] if isinstance(v, dict) else v) for k, v in row.items()}), flush=True)
        return row

    def fit(name, model, X, y, Xv, yv):
        t = time.time()
        model.fit(X, y)
        P = model.predict_proba(Xv)
        row = log(name, yv, model.classes_[P.argmax(1)], time.time() - t)
        probas[name] = (P, model.classes_)
        return row

    Xtr, ytr, wtr, names = load_split("train", extra=True)
    Xva, yva, _, _ = load_split("val", extra=True)
    n1 = len(names) - 9                                 # v1 = first 35 columns (v2 appends 9)
    print(f"train {Xtr.shape}, val {Xva.shape}, v1={n1} v2={len(names)} features", flush=True)

    # 1) current production setup vs extended features
    Xc, yc, _ = _cap(Xtr, ytr, wtr, 40000, rng)
    fit("ET500 v1 cap40k", et(), Xc[:, :n1], yc, Xva[:, :n1], yva)
    fit("ET500 v2 cap40k", et(), Xc, yc, Xva, yva)

    # 2) more training pixels (only the big classes - water, clouds, wakes - are capped)
    for cap in (100000, 10 ** 9):
        Xc2, yc2, _ = _cap(Xtr, ytr, wtr, cap, rng)
        fit(f"ET500 v2 cap{'all' if cap > 10 ** 8 else cap // 1000}k", et(), Xc2, yc2, Xva, yva)

    # 3) gradient boosting and a soft-voting ensemble with the best Extra Trees
    fit("HistGB v2 cap40k", hgb(), Xc, yc, Xva, yva)
    best = max((r for r in results if r["name"].startswith("ET500 v2")), key=lambda r: r["macro_f1"])["name"]
    (P_et, cls), (P_gb, cls_gb) = probas[best], probas["HistGB v2 cap40k"]
    assert list(cls) == list(cls_gb)
    for w in (0.5, 0.7):
        name = f"Ensemble {w:.1f} {best} + {1 - w:.1f} HistGB"
        P = w * P_et + (1 - w) * P_gb
        log(name, yva, cls[P.argmax(1)], 0)
        probas[name] = (P, cls)

    # 4) debris decision threshold: call debris when P(debris) >= t even if another class is the argmax
    for key in (best, "Ensemble 0.7 " + best + " + 0.3 HistGB"):
        P, cls = probas[key]
        for t_ in (0.2, 0.25, 0.3, 0.35, 0.4):
            log(f"{key} | debris>= {t_}", yva, predict_with_threshold(P, cls, t_), 0, {"debris_threshold": t_})

    # 5) two experts: Extra Trees decides floating vs not, the soft vote names everything else
    for w in (0.0, 0.3, 0.5, 0.7):
        log(f"Hybrid: {best} decides floating, {w:.1f} ET + {1 - w:.1f} HistGB names the rest", yva,
            hybrid_predict(P_et, P_gb, cls, w), 0, {"ensemble_weight": w})

    (MODELS / "experiments_v2_val.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
