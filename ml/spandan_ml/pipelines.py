"""End-to-end runs used by the Kaggle notebooks (and runnable locally).

    python -m spandan_ml.pipelines cwru <cwru_root> <out_dir>
    python -m spandan_ml.pipelines ims  <ims_root>  <out_dir> [--every 1]
"""
import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np
import sklearn
from joblib import Parallel, delayed

from spandan_ml import TARGET_FS, cwru, ims
from spandan_ml.diagnosis import build_dataset, evaluate, plot_confusion, save, train_final
from spandan_ml.features import window_features, windows


def _cwru_rows(rec: cwru.Recording, window_s: float, hop_s: float, max_windows: int) -> list[dict]:
    y = cwru.load(rec)
    ws = windows(y, TARGET_FS, window_s, hop_s)[:max_windows]
    return [{"features": window_features(w, TARGET_FS, rpm=rec.rpm, bearing_model=cwru.BEARING),
             "label": rec.label, "recording_id": rec.recording_id, "load_hp": rec.load_hp,
             "fault_size": rec.fault_size, "window": i} for i, w in enumerate(ws)]


def run_cwru(root: str, out_dir: str, *, window_s: float = 2.0, hop_s: float = 1.0, max_windows: int = 40,
             include_48k: bool = False, n_jobs: int = -1) -> dict:
    """Discover → manifest → features → leave-one-load-out evaluation → final model + report."""
    t0 = time.time()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    recs = [r for r in cwru.discover(root) if include_48k or r.fs == 12000 or r.label == "normal"]
    with (out / "cwru_manifest.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "cwru_number", "label", "fault_size", "load_hp", "rpm", "fs", "label_source", "split_unit"])
        for r in recs:
            w.writerow([r.path.name, r.number, r.label, r.fault_size, r.load_hp, r.rpm, r.fs, r.label_source,
                        r.recording_id])
    counts = {c: sum(r.label == c for r in recs) for c in cwru.CLASSES}
    print(f"{len(recs)} recordings: {counts}")
    if min(counts.values()) == 0:
        raise SystemExit(f"Some classes have no recordings ({counts}); check the dataset path")

    rows = [row for chunk in Parallel(n_jobs=n_jobs)(
        delayed(_cwru_rows)(r, window_s, hop_s, max_windows) for r in recs) for row in chunk]
    ds = build_dataset(rows)
    print(f"{len(rows)} windows of {window_s:g} s at {TARGET_FS} Hz, {len(ds.feature_names)} features")

    report = evaluate(ds)
    report.update({"dataset": "CWRU drive end, resampled to 3.2 kHz", "window_s": window_s, "hop_s": hop_s,
                   "recordings": counts, "runtime_s": round(time.time() - t0, 1)})
    model = train_final(ds)
    path = save(model, ds, report, out, extra={"window_s": window_s, "fs": TARGET_FS, "bearing": cwru.BEARING,
                                               "sklearn_version": sklearn.__version__,
                                               "trained_on": "CWRU DE (12 kHz faults + normal)"})
    for key in ("leave_one_load_out", "grouped_5fold_by_recording", "rules_only"):
        plot_confusion(report, key, out / f"confusion_{key}.png")
    summary = {k: {m: report[k][m] for m in ("accuracy", "macro_f1")}
               for k in ("leave_one_load_out", "grouped_5fold_by_recording", "rules_only")}
    print(json.dumps(summary, indent=2))
    print(f"model → {path}")
    return report


# ---------- IMS: health-indicator time series for RUL (M2-24 / M2-25) ----------

def _ims_snapshot(path: Path, test: int) -> list[dict]:
    from app.analytics.signal import kurtosis
    from app.analytics.rules import score_window

    snap = ims.load_snapshot(path)
    out = []
    for b in range(1, 5):
        x = ims.bearing_signal(snap, test, b)
        y = cwru.resample_to(x, ims.FS, TARGET_FS)
        r = score_window(y, TARGET_FS, rpm=ims.RPM, bearing_model=ims.BEARING)
        out.append({"rms_raw": float(np.sqrt(np.mean((x - x.mean()) ** 2))), "kurtosis_raw": kurtosis(x),
                    "rms": float(np.sqrt(np.mean((y - y.mean()) ** 2))), "kurtosis": kurtosis(y),
                    **{f"rule_{s.fault}": s.score or 0.0 for s in r.scores}, "bearing": b})
    return out


def run_ims(root: str, out_dir: str, *, every: int = 1, n_jobs: int = -1) -> list[Path]:
    """One CSV per test: time, bearing, unit, failure label, health indicators."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for ts in ims.discover(root):
        snaps = ts.snapshots[::every]
        print(f"IMS test {ts.number}: {len(snaps)} snapshots")
        res = Parallel(n_jobs=n_jobs, batch_size=16)(delayed(_ims_snapshot)(p, ts.number) for p in snaps)
        p = out / f"ims_test{ts.number}_indicators.csv"
        with p.open("w", newline="") as f:
            fields = ["time", "test", "bearing", "unit_id", "failed_with"] + [k for k in res[0][0] if k != "bearing"]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for snap_path, per_bearing in zip(snaps, res):
                for row in per_bearing:
                    b = row.pop("bearing")
                    w.writerow({"time": snap_path.name, "test": ts.number, "bearing": b,
                                "unit_id": ims.unit_id(ts.number, b),
                                "failed_with": ims.FAILURES[ts.number].get(b, ""), **row})
        paths.append(p)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", choices=["cwru", "ims"])
    ap.add_argument("root")
    ap.add_argument("out")
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--every", type=int, default=1, help="IMS: use every n-th snapshot")
    ap.add_argument("--jobs", type=int, default=-1)
    a = ap.parse_args()
    if a.dataset == "cwru":
        run_cwru(a.root, a.out, window_s=a.window, n_jobs=a.jobs)
    else:
        run_ims(a.root, a.out, every=a.every, n_jobs=a.jobs)


if __name__ == "__main__":
    main()
