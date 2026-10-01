"""Debris classifier trained on MARIDA (Marine Debris Archive, Kikaki et al. 2022).

MARIDA provides labelled Sentinel-2 pixels in 15 classes. Model choices were made on the official
*validation* split (see experiments.py); the final model is trained on train + validation and the
untouched *test* split is scored once for the numbers we report.

Features: background-relative spectra (transfer across sensors) + neighbourhood texture at 3x3, 7x7
and 15x15 plus edge strength (debris lines, ships, waves and foam differ in shape as much as in colour).

Two experts (chosen on the validation split, experiments_v2.py):
  * Extra Trees decides *floating material or not* (best debris / floating F1, well calibrated);
  * an Extra Trees + gradient-boosting soft vote names every other class (water types, clouds,
    ships, waves), which is where gradient boosting is much stronger.

    python -m aquatrace.marida        # trains, writes models/marida_rf.joblib + marida_metrics.json
"""
from __future__ import annotations

import json
import time

import joblib
import numpy as np
import rasterio
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix, precision_recall_fscore_support

from .config import MODELS, RANDOM_SEED, RAW
from .detect import S2_BANDS, feature_image

MARIDA = RAW / "marida"
CLASSES = {1: "Marine Debris", 2: "Dense Sargassum", 3: "Sparse Sargassum", 4: "Natural Organic Material",
           5: "Ship", 6: "Clouds", 7: "Marine Water", 8: "Sediment-Laden Water", 9: "Foam",
           10: "Turbid Water", 11: "Shallow Water", 12: "Waves", 13: "Cloud Shadows", 14: "Wakes",
           15: "Mixed Water"}
FLOATING = [1, 2, 3]  # marine debris, dense + sparse sargassum (foam / organic classes are too small and noisy)
CONF_WEIGHT = {1: 1.0, 2: 0.7, 3: 0.4}  # annotator confidence: high / moderate / low
MODEL_PATH = MODELS / "marida_rf.joblib"
METRICS_PATH = MODELS / "marida_metrics.json"
SPATIAL = True
EXTRA = True  # feature set v2: 15x15 context + edge strength (models/experiments_v2_val.json)
MODEL_KIND = "ExtraTrees"  # chosen on the validation split (models/experiments_val.json)
ENSEMBLE_WEIGHT = 0.5  # share of Extra Trees in the soft vote that names non-floating classes
CONF_WEIGHTED = False  # confidence weighting did not help Extra Trees on the validation split


def load_split(name: str, spatial: bool = SPATIAL, extra: bool = False):
    X, y, w = [], [], []
    names = None
    for pid in (MARIDA / "splits" / f"{name}_X.txt").read_text().split():
        base = MARIDA / "patches" / ("S2_" + pid.rsplit("_", 1)[0]) / f"S2_{pid}"
        with rasterio.open(f"{base}.tif") as s:
            img = np.nan_to_num(s.read().astype("float32"))
        with rasterio.open(f"{base}_cl.tif") as s:
            cl = s.read(1).astype(int)
        with rasterio.open(f"{base}_conf.tif") as s:
            conf = s.read(1).astype(int)
        m = cl > 0
        if not m.any():
            continue
        # patch background: median over the whole 256 x 256 patch (~2.5 km, mostly water),
        # matching the local-background block used on Sentinel-2 / PACE scenes
        med = np.median(img.reshape(img.shape[0], -1), axis=1)
        bands = {k: img[i] for i, k in enumerate(S2_BANDS)}
        bg = {k: np.full(img.shape[1:], med[i], dtype="float32") for i, k in enumerate(S2_BANDS)}
        F, names = feature_image(bands, bg, spatial=spatial, extra=extra)
        X.append(F[m]); y.append(cl[m]); w.append(np.vectorize(CONF_WEIGHT.get)(conf[m], 0.4))
    X, y, w = np.vstack(X), np.concatenate(y), np.concatenate(w)
    ok = np.isfinite(X).all(axis=1)
    return X[ok], y[ok], w[ok], names


def _cap(X, y, w, per_class: int, rng):
    keep = np.concatenate([rng.choice(np.flatnonzero(y == c), min(per_class, int((y == c).sum())), replace=False)
                           for c in np.unique(y)])
    return X[keep], y[keep], w[keep]


def _binary(y_true, y_pred, positive):
    p, r, f, _ = precision_recall_fscore_support(np.isin(y_true, positive), np.isin(y_pred, positive),
                                                 average="binary", zero_division=0)
    return {"precision": round(float(p), 3), "recall": round(float(r), 3), "f1": round(float(f), 3),
            "support": int(np.isin(y_true, positive).sum())}


def make_model(kind: str = MODEL_KIND):
    if kind == "ExtraTrees":
        return ExtraTreesClassifier(500, min_samples_leaf=2, n_jobs=-1, class_weight="balanced_subsample",
                                    random_state=RANDOM_SEED)
    return RandomForestClassifier(300, min_samples_leaf=2, max_depth=28, n_jobs=-1,
                                  class_weight="balanced_subsample", random_state=RANDOM_SEED)


def make_booster():
    return HistGradientBoostingClassifier(max_iter=400, learning_rate=0.08, max_leaf_nodes=63, l2_regularization=1.0,
                                          class_weight="balanced", early_stopping=False, random_state=RANDOM_SEED)


def hybrid_predict(P_et: np.ndarray, P_gb: np.ndarray | None, classes, w: float = ENSEMBLE_WEIGHT) -> np.ndarray:
    """Extra Trees decides floating material; elsewhere the soft vote picks the best non-floating class."""
    classes = np.asarray(classes)
    pe = classes[P_et.argmax(axis=1)]
    if P_gb is None:
        return pe
    P = w * P_et + (1 - w) * P_gb
    P[:, np.isin(classes, FLOATING)] = -1
    return np.where(np.isin(pe, FLOATING), pe, classes[P.argmax(axis=1)])


def train(per_class: int = 40000, kind: str = MODEL_KIND) -> dict:
    t0 = time.time()
    rng = np.random.default_rng(RANDOM_SEED)
    Xtr, ytr, wtr, names = load_split("train", extra=EXTRA)
    Xva, yva, wva, _ = load_split("val", extra=EXTRA)
    Xte, yte, _, _ = load_split("test", extra=EXTRA)
    X, y, w = np.vstack([Xtr, Xva]), np.concatenate([ytr, yva]), np.concatenate([wtr, wva])
    counts = {CLASSES[int(c)]: int(n) for c, n in zip(*np.unique(y, return_counts=True))}
    X, y, w = _cap(X, y, w, per_class, rng)
    model = make_model(kind)
    model.fit(X, y, sample_weight=w if CONF_WEIGHTED else None)
    booster = make_booster().fit(X, y)
    assert list(booster.classes_) == list(model.classes_)
    proba = model.predict_proba(Xte)
    pred = hybrid_predict(proba, booster.predict_proba(Xte), model.classes_)
    labels = sorted(CLASSES)
    rep = classification_report(yte, pred, labels=labels, target_names=[CLASSES[c] for c in labels],
                                output_dict=True, zero_division=0)
    metrics = {
        "model": f"Two experts: {kind} ({model.n_estimators} trees) decides floating material; a "
                 f"{ENSEMBLE_WEIGHT:.1f}/{1 - ENSEMBLE_WEIGHT:.1f} soft vote with gradient boosting "
                 f"({booster.max_iter} rounds) names the other classes. Features: background-relative Sentinel-2 "
                 "bands, FDI/FAI/NDVI/NDWI, 3x3 / 7x7 / 15x15 neighbourhood texture and edge strength; "
                 + ("confidence-weighted labels" if CONF_WEIGHTED else "all labels weighted equally"),
        "dataset": "MARIDA (Kikaki et al. 2022): trained on train+val, scored once on the official test split",
        "train_pixels_by_class": counts,
        "test_pixels": int(len(yte)),
        "debris": _binary(yte, pred, [1]),
        "floating_material": _binary(yte, pred, FLOATING),
        "macro_f1": round(float(rep["macro avg"]["f1-score"]), 3),
        "accuracy": round(float(rep["accuracy"]), 3),
        "per_class": {k: {m: round(float(v[m]), 3) for m in ("precision", "recall", "f1-score", "support")}
                      for k, v in rep.items() if k in CLASSES.values()},
        "confusion_matrix": {"labels": [CLASSES[c] for c in labels],
                             "matrix": confusion_matrix(yte, pred, labels=labels).tolist()},
        "feature_importance": dict(sorted(((n, round(float(i), 4)) for n, i in zip(names, model.feature_importances_)),
                                          key=lambda kv: -kv[1])[:20]),
        "train_seconds": round(time.time() - t0, 1),
    }
    # keep test-set probabilities for the confidence-calibration check (calibration.py)
    col = {c: i for i, c in enumerate(model.classes_)}
    np.savez_compressed(MODELS / "marida_test_proba.npz", y=yte,
                        p_debris=proba[:, col[1]], p_floating=proba[:, [col[c] for c in FLOATING]].sum(axis=1))
    joblib.dump({"model": model, "booster": booster, "ensemble_weight": ENSEMBLE_WEIGHT,
                 "spatial": SPATIAL, "extra": EXTRA, "features": names}, MODEL_PATH, compress=3)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    return metrics


class RFModel:
    CLASSES = CLASSES
    REJECT = {5, 6, 12, 13, 14}  # ship, clouds, waves, cloud shadows, wakes

    def __init__(self, bundle):
        if isinstance(bundle, dict):
            self.rf, self.spatial = bundle["model"], bundle.get("spatial", False)
            self.extra = bundle.get("extra", False)  # feature set v2 (wider context + edges)
            self.booster, self.w = bundle.get("booster"), bundle.get("ensemble_weight", ENSEMBLE_WEIGHT)
        else:  # older pickles: bare pixel-feature model
            self.rf, self.spatial, self.extra, self.booster, self.w = bundle, False, False, None, 1.0
        self.cls = list(self.rf.classes_)

    def predict_proba_groups(self, X: np.ndarray) -> dict:
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        P = self.rf.predict_proba(X)
        col = {c: i for i, c in enumerate(self.cls)}
        debris = P[:, col[1]] if 1 in col else np.zeros(len(X))
        floating = sum(P[:, col[c]] for c in FLOATING if c in col)
        label = hybrid_predict(P, None if self.booster is None else self.booster.predict_proba(X), self.cls, self.w)
        return {"debris": debris, "floating": floating, "label": label}


def load_model() -> RFModel:
    return RFModel(joblib.load(MODEL_PATH))


if __name__ == "__main__":
    m = train()
    print(json.dumps({k: m[k] for k in ("debris", "floating_material", "macro_f1", "accuracy", "train_seconds")}, indent=2))
