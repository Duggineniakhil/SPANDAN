"""Remaining useful life (M2-24, doc 05 §3).

Health indicator: vibration RMS divided by the machine's own baseline RMS (1.0 = like when healthy).
Degradation is fitted as exponential growth, i.e. a straight line on log(ratio), using only the points
since degradation began (onset). The day the line reaches the failure level is the predicted failure.

The range comes from a bootstrap over both uncertainties:
  * the trend (residuals resampled, line refitted)
  * the failure level, which varies a lot between bearings (IMS: 2.8× to 7.2× normal); each bootstrap
    draw picks one of the failure levels seen in training
Reported as the 10th–90th percentile. Too few points, a falling trend or a poor fit (R² < 0.6)
→ `insufficient_data`. No sustained rise above the onset level → `no_degradation` (no RUL needed).

Pure NumPy; the parameters (failure levels, onset rule) come from `ml/results/rul_config_v1.json`,
produced by the IMS evaluation (M2-25).
"""
from dataclasses import dataclass, field

import numpy as np

VERSION = "rul-loglinear-v1"


@dataclass(frozen=True)
class RulConfig:
    failure_ratios: tuple[float, ...] = (2.78, 3.43, 6.04, 7.16)  # RMS / baseline at failure (IMS, overwritten by config)
    onset_ratio: float = 1.5         # degradation has started when the smoothed ratio stays above this …
    onset_points: int = 6            # … for this many readings in a row
    smooth_points: int = 6           # rolling median length
    min_points: int = 12             # points since onset needed for a fit
    min_r2: float = 0.6
    fit_days: float | None = None    # only fit the most recent N days since onset (None = all)
    monotone: bool = True            # fit the running maximum: wear doesn't heal, dips are transient
    block: int = 6                   # bootstrap blocks of consecutive residuals (they are correlated)
    # Range calibration: 10th/90th percentile of log(true RUL / predicted median) on training bearings.
    # When set, the reported range is median × exp(these); the bootstrap range alone is too narrow
    # because the final failure phase is more abrupt than any trend fitted before it.
    calibration: tuple[float, float] | None = None
    n_boot: int = 400
    quantiles: tuple[float, float] = (0.1, 0.9)
    max_days: float = 90.0           # cap: further out than this is reported as this

    @classmethod
    def from_dict(cls, d: dict) -> "RulConfig":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        for k in ("failure_ratios", "quantiles", "calibration"):
            if known.get(k) is not None:
                known[k] = tuple(known[k])
        return cls(**known)


@dataclass
class RulResult:
    status: str                      # ok | insufficient_data | no_degradation
    low_days: float | None = None
    median_days: float | None = None
    high_days: float | None = None
    r2: float | None = None
    n_points: int = 0
    onset_days: float | None = None  # time of onset on the input's time axis
    current_ratio: float | None = None
    reason: str = ""
    version: str = field(default=VERSION)


def smooth(x: np.ndarray, k: int) -> np.ndarray:
    """Trailing rolling median (uses only past points, like live data would)."""
    x = np.asarray(x, dtype=float)
    if k <= 1:
        return x.copy()
    return np.array([np.median(x[max(0, i - k + 1): i + 1]) for i in range(len(x))])


def find_onset(ratio_smooth: np.ndarray, cfg: RulConfig) -> int | None:
    """Index where the smoothed ratio first stays above the onset level for `onset_points` readings."""
    above = ratio_smooth >= cfg.onset_ratio
    run = 0
    for i, a in enumerate(above):
        run = run + 1 if a else 0
        if run >= cfg.onset_points:
            return i - cfg.onset_points + 1
    return None


def _fit(t: np.ndarray, y: np.ndarray) -> tuple[float, float, float, np.ndarray]:
    A = np.column_stack([np.ones_like(t), t])
    (a, b), *_ = np.linalg.lstsq(A, y, rcond=None)
    pred = a + b * t
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return float(a), float(b), r2, y - pred


def estimate_rul(t_days: np.ndarray, ratio: np.ndarray, cfg: RulConfig = RulConfig(), *, seed: int = 0) -> RulResult:
    """RUL at the last time point. `t_days`: increasing times in days; `ratio`: RMS / baseline RMS."""
    t = np.asarray(t_days, dtype=float)
    r = np.asarray(ratio, dtype=float)
    ok = np.isfinite(t) & np.isfinite(r) & (r > 0)
    t, r = t[ok], r[ok]
    if len(t) < cfg.onset_points:
        return RulResult("insufficient_data", n_points=len(t), reason="too few readings")
    rs = smooth(r, cfg.smooth_points)
    now, current = t[-1], float(rs[-1])
    onset = find_onset(rs, cfg)
    if onset is None:
        return RulResult("no_degradation", n_points=len(t), current_ratio=round(current, 3),
                         reason=f"vibration has not stayed above {cfg.onset_ratio}× normal")

    sel = slice(onset, None)
    level = np.maximum.accumulate(rs[sel]) if cfg.monotone else r[sel]
    tf, yf = t[sel], np.log(level)
    if cfg.fit_days is not None:
        recent = tf >= now - cfg.fit_days
        tf, yf = tf[recent], yf[recent]
    base = RulResult("insufficient_data", n_points=len(tf), onset_days=round(float(t[onset]), 3),
                     current_ratio=round(current, 3))
    if len(tf) < cfg.min_points:
        base.reason = f"only {len(tf)} readings since degradation began (need {cfg.min_points})"
        return base
    a, b, r2, resid = _fit(tf, yf)
    base.r2 = round(r2, 3)
    if b <= 0:
        base.reason = "vibration is not rising"
        return base
    if r2 < cfg.min_r2:
        base.reason = f"trend too irregular (R² {r2:.2f} < {cfg.min_r2})"
        return base

    rng = np.random.default_rng(seed)
    levels = np.log(np.asarray(cfg.failure_ratios, dtype=float))
    pred = a + b * tf
    ruls = np.empty(cfg.n_boot)
    n, blk = len(resid), max(1, min(cfg.block, len(resid)))
    for i in range(cfg.n_boot):
        starts = rng.integers(0, n - blk + 1, size=-(-n // blk))  # moving-block bootstrap
        yb = pred + np.concatenate([resid[s:s + blk] for s in starts])[:n]
        ab, bb, _, _ = _fit(tf, yb)
        level = rng.choice(levels)
        if level <= np.log(max(current, 1e-9)):
            ruls[i] = 0.0  # already at or past this failure level
        elif bb <= 0:
            ruls[i] = cfg.max_days
        else:
            ruls[i] = (level - ab) / bb - now
    ruls = np.clip(ruls, 0.0, cfg.max_days)
    med = float(np.median(ruls))
    lo, hi = np.quantile(ruls, cfg.quantiles)
    if cfg.calibration is not None:
        lo = min(lo, med * float(np.exp(cfg.calibration[0])))
        hi = min(cfg.max_days, max(hi, med * float(np.exp(cfg.calibration[1]))))
    base.status = "ok"
    base.low_days, base.median_days, base.high_days = (round(float(v), 2) for v in (lo, med, hi))
    return base
