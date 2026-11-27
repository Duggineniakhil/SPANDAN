"""Bearing geometry (M2-20) and the physics rule scorer (M2-21), on simulated windows."""
import numpy as np
import pytest

from app.analytics.bearings import fault_orders, lookup, normalise_model, table
from app.analytics.rules import baseline_from, score_window
from app.analytics.signal import amplitude_spectrum, envelope_spectrum
from app.sim.vibration import FAULTS, generate_window

# ---------- bearings ----------


@pytest.mark.parametrize("model,bpfo,bpfi,bsf2,ftf", [
    # Published CWRU multiples of shaft speed (their "rolling element" value is 2×BSF)
    ("6205", 3.5848, 5.4152, 4.7135, 0.39828),
    ("6203", 3.0530, 4.9469, 3.9874, 0.3817),
])
def test_fault_orders_match_cwru(model, bpfo, bpfi, bsf2, ftf):
    o = fault_orders(lookup(model))
    assert o.bpfo == pytest.approx(bpfo, abs=5e-4)
    assert o.bpfi == pytest.approx(bpfi, abs=5e-4)
    assert 2 * o.bsf == pytest.approx(bsf2, abs=2e-3)
    assert o.ftf == pytest.approx(ftf, abs=5e-4)


def test_ims_bearing_bpfo_at_2000_rpm():
    # IMS documentation: BPFO ≈ 236 Hz at 2000 rpm
    assert fault_orders(lookup("ZA-2115")).hz(2000 / 60)["bpfo"] == pytest.approx(236.4, abs=0.5)


@pytest.mark.parametrize("raw,norm", [("SKF 6205-2RS JEM", "6205"), ("6205-2RS", "6205"), ("6205 ZZ C3", "6205"),
                                      ("UCP204", "UC204"), ("ucp 204", "UC204"), ("za2115", "ZA-2115")])
def test_model_names_normalise(raw, norm):
    assert normalise_model(raw) == norm and lookup(raw) is not None


def test_table_flags_approximate_rows_and_physics_holds():
    t = table()
    assert not t["6205"].approximate and t["6204"].approximate
    for b in t.values():
        o = fault_orders(b)
        assert o.bpfo + o.bpfi == pytest.approx(b.n_elements)  # identity of the formulas
        assert 0 < o.ftf < 0.5


# ---------- signal ----------

def test_spectrum_amplitude_and_envelope_rate():
    fs, t = 3200, np.arange(32000) / 3200
    x = 0.2 * np.sin(2 * np.pi * 48 * t)
    f, a = amplitude_spectrum(x, fs).peak(48, 1)
    assert f == pytest.approx(48, abs=0.5) and a == pytest.approx(0.2, rel=0.1)
    # 1 kHz carrier switched on/off 120 times a second → envelope line at 120 Hz
    am = (1 + np.sign(np.sin(2 * np.pi * 120 * t))) * np.sin(2 * np.pi * 1000 * t)
    env = envelope_spectrum(am, fs)
    assert env.freqs[np.argmax(env.amp[env.freqs > 20]) + np.sum(env.freqs <= 20)] == pytest.approx(120, abs=1)


# ---------- rule scorer ----------

@pytest.fixture(scope="module")
def baseline():
    return baseline_from([score_window(generate_window(seed=100 + i).y, 3200, rpm=2880, bearing_model="6205")
                          for i in range(5)])


def _top(w, baseline, **kw):
    r = score_window(w.y, w.fs, rpm=w.rpm, bearing_model=kw.pop("bearing_model", "6205-2RS"), z=w.z,
                     baseline=baseline, **kw)
    return r, (r.top.fault if r.top else "none")


@pytest.mark.parametrize("fault", [f for f in FAULTS if f != "none"])
@pytest.mark.parametrize("severity", [0.3, 0.6])
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_each_fault_is_ranked_first(baseline, fault, severity, seed):
    r, top = _top(generate_window(fault, severity, seed=seed), baseline)
    assert top == fault, r.ranked()[:3]


def test_healthy_windows_raise_nothing(baseline):
    tops = [_top(generate_window("none", seed=s), baseline)[1] for s in range(30)]
    assert tops.count("none") == 30


@pytest.mark.parametrize("fault", ["bearing_outer", "bearing_inner", "bearing_ball"])
def test_mild_faults_are_never_misread(baseline, fault):
    """At low severity the scorer may stay silent, but must not name a different fault."""
    for seed in range(5):
        _, top = _top(generate_window(fault, 0.15, seed=seed), baseline)
        assert top in ("none", fault)


def test_score_grows_with_severity(baseline):
    scores = [next(s.score for s in _top(generate_window("bearing_outer", sev, seed=4), baseline)[0].scores
                   if s.fault == "bearing_outer") for sev in (0.1, 0.2, 0.3)]
    assert scores == sorted(scores) and scores[-1] > scores[0]


@pytest.mark.parametrize("rpm", [1440, 2880])
@pytest.mark.parametrize("fs", [3200, 12000])  # our sensor and CWRU's 12 kHz
def test_other_speeds_and_sample_rates(rpm, fs):
    w = generate_window("bearing_outer", 0.5, rpm=rpm, fs=fs, seed=9)
    r = score_window(w.y, w.fs, rpm=rpm, bearing_model="6205")
    assert r.top.fault == "bearing_outer"
    assert r.fault_hz["bpfo"] == pytest.approx(3.5848 * rpm / 60, rel=0.02)


def test_evidence_names_the_frequency(baseline):
    r, _ = _top(generate_window("bearing_inner", 0.5, seed=3), baseline)
    ev = r.scores[0].evidence
    assert "BPFI" in ev and "Hz" in ev and "noise floor" in ev and "sidebands" in ev


def test_unknown_bearing_is_reported_not_guessed():
    w = generate_window("bearing_outer", 0.6, seed=1)
    r = score_window(w.y, w.fs, rpm=w.rpm, bearing_model="XYZ-999")
    bearing = [s for s in r.scores if s.fault.startswith("bearing_")]
    assert all(s.score is None and "not in the geometry table" in s.evidence for s in bearing)
    assert r.top is None or not r.top.fault.startswith("bearing_")


def test_imbalance_without_baseline_is_capped():
    w = generate_window("imbalance", 0.8, seed=2)
    r = score_window(w.y, w.fs, rpm=w.rpm, bearing_model="6205")
    imb = next(s for s in r.scores if s.fault == "imbalance")
    assert imb.score <= 0.5 and "no baseline" in imb.evidence


def test_features_for_classifier_are_flat_numbers(baseline):
    r, _ = _top(generate_window("looseness", 0.5, seed=1), baseline)
    feats = r.features()
    assert {"rule_looseness", "rule_bearing_outer", "ratio_2x_1x", "env_prom_bearing_outer"} <= set(feats)
    assert all(isinstance(v, float) for v in feats.values())
