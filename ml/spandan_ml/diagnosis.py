"""Fault classifier (M2-22) and its evaluation (M2-23).

HistGradientBoosting on window features + rule scores, probability-calibrated, top-3 output with
evidence, `unknown` when the top confidence is below 0.5.

Evaluation never mixes windows of one recording across train and test:
  * leave-one-load-out (train on 3 motor loads, test on the 4th), the main number
  * grouped 5-fold by recording, as a second view
Also reported: the physics rules alone (no training) on the same windows.
"""
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut

from app.analytics.rules import STANDS_OUT

VERSION = "diagnosis-hgb-v1"
UNKNOWN_BELOW = 0.5


@dataclass
class Dataset:
    X: np.ndarray
    y: np.ndarray            # class names
    recording: np.ndarray    # group: recording id
    load: np.ndarray         # group: motor load (HP)
    feature_names: list[str]
    meta: list[dict] = field(default_factory=list)


def build_dataset(rows: list[dict]) -> Dataset:
    """rows: {"features": {...}, "label", "recording_id", "load_hp", ...}"""
    from spandan_ml.features import NOT_FOR_MODEL

    names = sorted(set.intersection(*(set(r["features"]) for r in rows)) - NOT_FOR_MODEL)
    X = np.array([[r["features"][n] for n in names] for r in rows], dtype=float)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    return Dataset(X, np.array([r["label"] for r in rows]), np.array([r["recording_id"] for r in rows]),
                   np.array([r["load_hp"] for r in rows]), names,
                   [{k: v for k, v in r.items() if k != "features"} for r in rows])


def make_model(groups: np.ndarray | None = None, X=None, y=None, seed: int = 0):
    n = len(y) if y is not None else 1000
    # default min leaf (20) can't split small folds; scale it with the data
    base = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.08, max_leaf_nodes=15,
                                          min_samples_leaf=max(3, min(20, n // 40)),
                                          l2_regularization=1.0, random_state=seed)
    if groups is None or len(set(groups)) < 3:
        return CalibratedClassifierCV(base, method="sigmoid", cv=3)
    cv = list(GroupKFold(n_splits=min(3, len(set(groups)))).split(X, y, groups))  # calibrate on held-out recordings
    return CalibratedClassifierCV(base, method="sigmoid", cv=cv)


def _metrics(y_true, y_pred, classes) -> dict:
    return {
        "n": int(len(y_true)),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=classes, average="macro", zero_division=0)), 4),
        "confusion": {"labels": list(classes),
                      "matrix": confusion_matrix(y_true, y_pred, labels=classes).tolist()},
    }


def rules_only(ds: Dataset, classes: list[str]) -> np.ndarray:
    """Physics rules without training: best bearing rule score, else normal."""
    idx = {c: ds.feature_names.index(f"rule_{c}") for c in classes if f"rule_{c}" in ds.feature_names}
    out = []
    for row in ds.X:
        best = max(idx, key=lambda c: row[idx[c]]) if idx else "normal"
        out.append(best if idx and row[idx[best]] >= STANDS_OUT else "normal")
    return np.array(out)


def evaluate(ds: Dataset, seed: int = 0) -> dict:
    classes = sorted(str(c) for c in set(ds.y))
    report: dict = {"version": VERSION, "classes": classes, "n_windows": int(len(ds.y)),
                    "n_recordings": int(len(set(ds.recording))), "features": ds.feature_names}

    def run(splitter, groups, name):
        pred = np.empty(len(ds.y), dtype=object)
        conf = np.zeros(len(ds.y))
        for tr, te in splitter.split(ds.X, ds.y, groups):
            if len(set(ds.y[tr])) < len(classes):
                continue  # a fold missing a class can't be trained fairly; skip it
            model = make_model(ds.recording[tr], ds.X[tr], ds.y[tr], seed).fit(ds.X[tr], ds.y[tr])
            proba = model.predict_proba(ds.X[te])
            pred[te] = model.classes_[proba.argmax(1)]
            conf[te] = proba.max(1)
        done = pred != None  # noqa: E711
        y_t, y_p, c = ds.y[done], pred[done].astype(str), conf[done]
        known = c >= UNKNOWN_BELOW
        res = _metrics(y_t, y_p, classes)
        res["unknown_rate"] = round(float(1 - known.mean()), 4) if len(c) else None
        res["accuracy_when_confident"] = round(float(accuracy_score(y_t[known], y_p[known])), 4) if known.any() else None
        report[name] = res
        return pred

    run(LeaveOneGroupOut(), ds.load, "leave_one_load_out")
    run(GroupKFold(n_splits=min(5, len(set(ds.recording)))), ds.recording, "grouped_5fold_by_recording")
    report["rules_only"] = _metrics(ds.y, rules_only(ds, classes), classes)
    return report


def train_final(ds: Dataset, seed: int = 0):
    return make_model(ds.recording, ds.X, ds.y, seed).fit(ds.X, ds.y)


def save(model, ds: Dataset, report: dict, out_dir: str | Path, extra: dict | None = None) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    artifact = {"model": model, "version": VERSION, "feature_names": ds.feature_names,
                "classes": [str(c) for c in model.classes_], "unknown_below": UNKNOWN_BELOW,
                "trained_at": time.strftime("%Y-%m-%dT%H:%M:%S"), **(extra or {})}
    path = out / f"{VERSION}.joblib"
    joblib.dump(artifact, path)
    (out / f"{VERSION}_report.json").write_text(json.dumps(report, indent=2))
    return path


def predict_top3(artifact: dict, features: dict[str, float], evidence: dict[str, str] | None = None) -> list[dict]:
    """Inference for the analytics worker: top-3 with confidence; `unknown` first if not confident."""
    x = np.array([[features.get(n, 0.0) for n in artifact["feature_names"]]], dtype=float)
    proba = artifact["model"].predict_proba(np.nan_to_num(x))[0]
    order = np.argsort(proba)[::-1][:3]
    top = [{"fault": str(artifact["model"].classes_[i]), "confidence": round(float(proba[i]), 3),
            "evidence": (evidence or {}).get(str(artifact["model"].classes_[i]), "")} for i in order]
    if top[0]["confidence"] < artifact["unknown_below"]:
        top.insert(0, {"fault": "unknown", "confidence": top[0]["confidence"],
                       "evidence": "No fault is likely enough (confidence below 0.5); inspect the machine."})
        top = top[:3]
    return top


def plot_confusion(report: dict, key: str, path: str | Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cm = np.array(report[key]["confusion"]["matrix"])
    labels = report[key]["confusion"]["labels"]
    fig, ax = plt.subplots(figsize=(5, 4.2))
    ax.imshow(cm, cmap="Greens")
    ax.set_xticks(range(len(labels)), labels, rotation=35, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, cm[i, j], ha="center", va="center", color="black")
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(f"{key.replace('_', ' ')}: acc {report[key]['accuracy']:.2f}, F1 {report[key]['macro_f1']:.2f}")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
