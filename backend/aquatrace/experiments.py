"""Model-selection experiments on MARIDA, scored on the *validation* split only.

The test split is never used here; marida.train() scores it once with the chosen setup.

    python -m aquatrace.experiments      # writes models/experiments_val.json
"""
from __future__ import annotations

import json
import time

import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import f1_score

from .config import MODELS, RANDOM_SEED
from .marida import FLOATING, _binary, _cap, load_split


def evaluate(y, p):
    return {"accuracy": round(float((y == p).mean()), 4),
            "macro_f1": round(float(f1_score(y, p, average="macro")), 4),
            "debris": _binary(y, p, [1]), "floating": _binary(y, p, FLOATING)}


def models():
    return {
        "RF": lambda: RandomForestClassifier(300, min_samples_leaf=2, max_depth=28, n_jobs=-1,
                                             class_weight="balanced_subsample", random_state=RANDOM_SEED),
        "ExtraTrees": lambda: ExtraTreesClassifier(400, min_samples_leaf=2, n_jobs=-1,
                                                   class_weight="balanced_subsample", random_state=RANDOM_SEED),
        "HistGB": lambda: HistGradientBoostingClassifier(max_iter=400, learning_rate=0.08, max_leaf_nodes=63,
                                                         l2_regularization=1.0, class_weight="balanced",
                                                         early_stopping=False, random_state=RANDOM_SEED),
    }


def main():
    rng = np.random.default_rng(RANDOM_SEED)
    results = []
    for spatial in (False, True):
        t0 = time.time()
        Xtr, ytr, wtr, names = load_split("train", spatial=spatial)
        Xva, yva, _, _ = load_split("val", spatial=spatial)
        Xtr, ytr, wtr = _cap(Xtr, ytr, wtr, 30000, rng)
        label = "pixel+texture" if spatial else "pixel"
        print(f"features={label} ({len(names)}) loaded in {time.time() - t0:.0f}s", flush=True)
        for mname, make in models().items():
            for use_w in (False, True):
                t1 = time.time()
                m = make()
                m.fit(Xtr, ytr, sample_weight=wtr if use_w else None)
                row = {"features": label, "model": mname, "conf_weighted": use_w,
                       **evaluate(yva, m.predict(Xva)), "seconds": round(time.time() - t1, 1)}
                results.append(row)
                print(json.dumps(row), flush=True)
    (MODELS / "experiments_val.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
