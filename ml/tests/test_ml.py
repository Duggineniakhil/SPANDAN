"""Loaders and pipelines on small fake datasets laid out like the Kaggle mirrors (no downloads)."""
import csv
import json
from datetime import datetime, timedelta

import joblib
import numpy as np
import pytest
from scipy.io import savemat

from spandan_ml import cwru, ims
from spandan_ml.diagnosis import predict_top3
from spandan_ml.features import window_features, windows
from spandan_ml.pipelines import run_cwru, run_ims

from app.sim.vibration import generate_window  # noqa: E402  (backend, via spandan_ml)

SIM_FAULT = {"normal": "none", "bearing_inner": "bearing_inner", "bearing_outer": "bearing_outer",
             "bearing_ball": "bearing_ball"}
FIRST = {"bearing_inner": 105, "bearing_ball": 118, "bearing_outer": 130}


def _mat(path, number, label, hp, fs=12000, seconds=6.0, seed=0, stray=None):
    rpm = cwru.RPM_BY_LOAD[hp]
    w = generate_window(SIM_FAULT[label], 0.5, rpm=rpm, fs=fs, seconds=seconds, seed=seed)
    data = {f"X{number:03d}_DE_time": w.y[:, None], f"X{number:03d}_FE_time": w.x[:, None],
            f"X{number:03d}RPM": np.array([[rpm]])}
    if stray:
        data[f"X{stray:03d}_DE_time"] = w.z[:, None]
    savemat(path, data)


@pytest.fixture(scope="module")
def cwru_root(tmp_path_factory):
    """Mirror A: numbered files (with 99.mat carrying a stray X098 channel, normal at 48 kHz).
    Mirror B style names for the faults: IR007_0.mat … in a 12k_DE folder."""
    root = tmp_path_factory.mktemp("cwru")
    (root / "numbered").mkdir()
    (root / "12k_DE").mkdir()
    for hp in range(4):
        _mat(root / "numbered" / f"{97 + hp}.mat", 97 + hp, "normal", hp, fs=48000, seconds=3.0, seed=hp,
             stray=98 if hp == 2 else None)
        for label, first in FIRST.items():
            code = {"bearing_inner": "IR007", "bearing_ball": "B007", "bearing_outer": "OR007@6"}[label]
            _mat(root / "12k_DE" / f"{code}_{hp}.mat", first + hp, label, hp, seed=10 * hp + first)
    (root / "numbered" / "readme.mat").write_bytes(b"not a mat file")  # must be skipped, not crash
    return root


def test_cwru_discovery_labels_loads_and_rates(cwru_root):
    recs = cwru.discover(cwru_root)
    assert len(recs) == 16
    by = {(r.label, r.load_hp): r for r in recs}
    assert by[("bearing_outer", 2)].fault_size == "007@6" and by[("bearing_outer", 2)].label_source == "filename"
    assert by[("normal", 0)].label_source == "cwru_number"
    assert all(by[("normal", hp)].fs == 48000 for hp in range(4))  # measured from the signal
    assert all(r.fs == 12000 for r in recs if r.label != "normal")
    assert by[("normal", 2)].key == "X099_DE_time"  # not the stray X098 channel
    assert by[("bearing_inner", 3)].rpm == 1730
    assert len({r.recording_id for r in recs}) == 16


def test_number_table_is_consistent():
    assert cwru.NUMBERS[105][:3] == ("bearing_inner", "007", 0)
    assert cwru.NUMBERS[121][:3] == ("bearing_ball", "007", 3)
    assert cwru.NUMBERS[197][:3] == ("bearing_outer", "014@6", 0)
    assert cwru.NUMBERS[3001][3] == 12000 and cwru.NUMBERS[109][3] == 48000


def test_resampling_keeps_frequency(cwru_root):
    rec = next(r for r in cwru.discover(cwru_root) if r.label == "normal")
    y = cwru.load(rec)
    assert len(y) == pytest.approx(3.0 * 3200, abs=2)
    from app.analytics.signal import amplitude_spectrum
    f, _ = amplitude_spectrum(y, 3200).peak(rec.rpm / 60, 2)
    assert f == pytest.approx(rec.rpm / 60, abs=0.6)


def test_window_features_are_finite():
    w = generate_window("bearing_outer", 0.5, rpm=1797, seconds=2, seed=1)
    f = window_features(w.y, 3200, rpm=1797, bearing_model="6205")
    assert len(f) > 30 and all(np.isfinite(v) for v in f.values())
    assert f["rule_bearing_outer"] > 0.5
    assert len(windows(np.zeros(3200 * 6), 3200, 2.0, 1.0)) == 5


def test_cwru_pipeline_end_to_end(cwru_root, tmp_path):
    report = run_cwru(str(cwru_root), str(tmp_path), window_s=2.0, hop_s=1.0, max_windows=4, n_jobs=1)
    for key in ("leave_one_load_out", "grouped_5fold_by_recording", "rules_only"):
        assert report[key]["accuracy"] >= 0.9, (key, report[key])
        assert (tmp_path / f"confusion_{key}.png").exists()
    assert report["n_recordings"] == 16
    saved = json.loads((tmp_path / "diagnosis-hgb-v1_report.json").read_text())
    assert saved["classes"] == ["bearing_ball", "bearing_inner", "bearing_outer", "normal"]
    manifest = list(csv.DictReader((tmp_path / "cwru_manifest.csv").open()))
    assert len(manifest) == 16

    art = joblib.load(tmp_path / "diagnosis-hgb-v1.joblib")
    assert art["sklearn_version"] and art["fs"] == 3200
    # a new recording made like the training data (12 kHz, then resampled to 3.2 kHz)
    assert not {"rms", "peak", "shaft_hz"} & set(art["feature_names"])  # scale-free inputs only
    for fault, label, fs in (("bearing_inner", "bearing_inner", 12000), ("bearing_outer", "bearing_outer", 12000),
                             ("none", "normal", 48000)):
        w = generate_window(fault, 0.5, rpm=1772, fs=fs, seconds=2, seed=99)
        y = cwru.resample_to(w.y, fs)
        top = predict_top3(art, window_features(y, 3200, rpm=1772, bearing_model="6205"))
        assert top[0]["fault"] == label and len(top) == 3, top


def test_predict_returns_unknown_when_unsure(cwru_root, tmp_path):
    run_cwru(str(cwru_root), str(tmp_path), max_windows=3, n_jobs=1)
    art = joblib.load(tmp_path / "diagnosis-hgb-v1.joblib")
    art["unknown_below"] = 1.01  # nothing can be that confident
    assert predict_top3(art, {})[0]["fault"] == "unknown"


# ---------- IMS ----------

@pytest.fixture(scope="module")
def ims_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("ims")
    t0 = datetime(2004, 2, 12, 10, 32, 39)
    for folder, channels in (("1st_test", 8), ("2nd_test", 4), ("4th_test/txt", 4)):
        d = root / folder
        d.mkdir(parents=True)
        for i in range(3):
            w = generate_window("bearing_outer" if i == 2 else "none", 0.6, rpm=2000, fs=20000, seconds=0.25,
                               bearing="ZA-2115", seed=i)
            data = np.column_stack([w.y if c == 0 else w.x for c in range(channels)])
            np.savetxt(d / (t0 + timedelta(minutes=10 * i)).strftime("%Y.%m.%d.%H.%M.%S"), data, fmt="%.4f",
                       delimiter="\t")
    return root


def test_ims_discovery(ims_root):
    sets = ims.discover(ims_root)
    assert [s.number for s in sets] == [1, 2, 3]  # "4th_test" is set 3
    assert all(len(s.snapshots) == 3 for s in sets)
    assert sets[0].times()[1] - sets[0].times()[0] == timedelta(minutes=10)
    snap = ims.load_snapshot(sets[0].snapshots[0])
    assert snap.shape[1] == 8 and len(ims.bearing_signal(snap, 1, 4)) == snap.shape[0]


def test_ims_pipeline_writes_indicators(ims_root, tmp_path):
    paths = run_ims(str(ims_root), str(tmp_path), n_jobs=1)
    assert [p.name for p in paths] == [f"ims_test{n}_indicators.csv" for n in (1, 2, 3)]
    rows = list(csv.DictReader(paths[1].open()))
    assert len(rows) == 3 * 4
    b1 = [r for r in rows if r["bearing"] == "1"]
    assert b1[0]["failed_with"] == "bearing_outer" and b1[0]["unit_id"] == "ims-2-b1"
    assert float(b1[2]["kurtosis_raw"]) > float(b1[0]["kurtosis_raw"])  # the faulty snapshot is impulsive


def test_training_refuses_a_different_sklearn(monkeypatch, tmp_path):
    import sklearn

    from spandan_ml import pinned_sklearn
    assert pinned_sklearn() == sklearn.__version__  # local env matches the pin
    monkeypatch.setattr(sklearn, "__version__", "0.0.1")
    with pytest.raises(RuntimeError, match="pinned"):
        run_cwru(str(tmp_path), str(tmp_path))


# ---------- RUL evaluation (M2-25) ----------

def test_rul_evaluation_leave_one_bearing_out():
    from app.analytics.rul import RulConfig
    from spandan_ml.rul_eval import FAILED, evaluate

    rng = np.random.default_rng(0)
    series = {}
    for k, unit in enumerate([(t, b) for t in (1, 2, 3) for b in range(1, 5)]):
        t = np.arange(0, 6, 1 / 144)
        if unit in FAILED:  # degrades from day 3, fails at the end at ratio ~ 4-6
            g = np.log(4 + k % 3) / 3
            r = np.where(t < 3, 1.0, np.exp(g * (t - 3)))
        else:
            r = np.ones_like(t)
        series[unit] = {"t_days": t, "ratio": r * np.exp(0.02 * rng.standard_normal(len(t))),
                        "failed_with": "bearing_outer" if unit in FAILED else ""}
    rep = evaluate(series, RulConfig(n_boot=100), step=24)
    a = rep["all_points_after_onset"]
    assert a["n_predicted"] > 0 and a["mae_days"] < 1.0 and a["low_bound_safe"] >= 0.8
    assert all(u["onset_days"] is not None for u in rep["units"].values())
    assert all(h["onset_days_before_test_end"] is None for h in rep["healthy_bearings"].values())
    assert rep["life_checkpoints"]["life_50"]["no_degradation"] == 4  # before day 3 nothing is predicted
