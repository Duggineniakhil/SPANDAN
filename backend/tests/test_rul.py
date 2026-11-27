"""RUL estimator (M2-24) on synthetic degradation curves."""
import json
from pathlib import Path

import numpy as np
import pytest

from app.analytics.rul import RulConfig, estimate_rul, find_onset, smooth

CFG = RulConfig(failure_ratios=(4.0,), n_boot=300)
STEP = 1 / 144  # one reading every 10 minutes, in days


def series(days: float, growth: float, *, onset_day: float, noise: float = 0.03, seed: int = 0):
    """Flat at 1.0, then exponential growth from `onset_day`."""
    rng = np.random.default_rng(seed)
    t = np.arange(0, days, STEP)
    r = np.where(t < onset_day, 1.0, np.exp(growth * (t - onset_day)))
    return t, r * np.exp(noise * rng.standard_normal(len(t)))


def test_exponential_degradation_is_predicted():
    growth, onset = 0.8, 2.0  # ratio 1.5 at onset+0.5 d, 4.0 at onset+1.73 d
    t, r = series(10, growth, onset_day=onset)
    true_fail = onset + np.log(4.0) / growth
    now = onset + 1.0
    keep = t <= now
    res = estimate_rul(t[keep], r[keep], CFG)
    assert res.status == "ok", res
    assert res.low_days <= true_fail - now <= res.high_days
    assert res.median_days == pytest.approx(true_fail - now, abs=0.25)
    assert res.r2 > 0.8 and res.onset_days == pytest.approx(onset + np.log(1.5) / growth, abs=0.1)


def test_healthy_machine_has_no_degradation():
    t, r = series(5, 0.0, onset_day=0)
    res = estimate_rul(t, r, CFG)
    assert res.status == "no_degradation" and res.low_days is None


def test_too_soon_after_onset_is_insufficient():
    t, r = series(10, 0.8, onset_day=2.0)
    i = find_onset(smooth(r, CFG.smooth_points), CFG) + CFG.min_points - 2
    res = estimate_rul(t[: i + 1], r[: i + 1], CFG)
    assert res.status == "insufficient_data" and "readings since degradation began" in res.reason


def test_transient_dip_does_not_hide_the_trend():
    """Wear doesn't heal: a temporary dip after onset must not stop the prediction."""
    t, r = series(10, 0.8, onset_day=2.0, noise=0.02)
    dip = (t > 3.0) & (t < 3.3)
    r = r.copy()
    r[dip] *= 0.75
    keep = t <= 3.6
    res = estimate_rul(t[keep], r[keep], CFG)
    assert res.status == "ok"
    raw = estimate_rul(t[keep], r[keep], RulConfig(failure_ratios=(4.0,), monotone=False, n_boot=300))
    assert res.r2 >= (raw.r2 or 0)


def test_already_past_failure_level_says_zero():
    t, r = series(10, 0.8, onset_day=2.0)
    keep = t <= 2.0 + np.log(5.0) / 0.8
    res = estimate_rul(t[keep], r[keep], CFG)
    assert res.status == "ok" and res.median_days == 0 and res.low_days == 0


def test_range_reflects_uncertain_failure_level():
    t, r = series(10, 0.8, onset_day=2.0)
    keep = t <= 3.0
    narrow = estimate_rul(t[keep], r[keep], RulConfig(failure_ratios=(4.0,)))
    wide = estimate_rul(t[keep], r[keep], RulConfig(failure_ratios=(2.5, 4.0, 7.0)))
    assert (wide.high_days - wide.low_days) > (narrow.high_days - narrow.low_days)


def test_calibration_only_widens():
    t, r = series(10, 0.8, onset_day=2.0)
    keep = t <= 3.0
    plain = estimate_rul(t[keep], r[keep], CFG)
    cal = estimate_rul(t[keep], r[keep], RulConfig(failure_ratios=(4.0,), n_boot=300, calibration=(-1.0, 1.5)))
    assert cal.median_days == plain.median_days
    assert cal.low_days <= plain.low_days and cal.high_days >= plain.high_days


def test_bad_input_is_handled():
    assert estimate_rul([], [], CFG).status == "insufficient_data"
    t, r = series(5, 0.8, onset_day=1.0)
    r = r.copy()
    r[::7] = np.nan
    assert estimate_rul(t, r, CFG).status in ("ok", "insufficient_data")


def test_config_from_ml_results_loads():
    path = Path(__file__).resolve().parents[2] / "ml" / "results" / "rul_config_v1.json"
    if not path.exists():
        pytest.skip("RUL config not generated")
    cfg = RulConfig.from_dict(json.loads(path.read_text()))
    assert len(cfg.failure_ratios) == 4 and cfg.monotone and cfg.calibration is None
