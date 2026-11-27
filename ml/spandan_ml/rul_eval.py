"""RUL evaluation on NASA IMS, leave-one-bearing-out (M2-25).

Units: the four bearings that failed (test 1 bearings 3 and 4, test 2 bearing 1, test 3 bearing 3).
Each is predicted with failure levels learned from the other three only. The failure time is the last
snapshot of the test. Healthy bearings are used to measure false onsets.

Reported:
  * at checkpoints after onset (25 / 50 / 75 / 90 % of the time between onset and failure):
    MAE of the median RUL (days), interval coverage (true RUL inside [low, high]), interval width
  * at 50 / 70 / 90 % of total life (doc 05 §3), which is mostly before onset: how often we (correctly)
    say "no degradation" there
  * over every snapshot after onset: coverage and MAE
    python -m spandan_ml.rul_eval ml/results ml/results
"""
import csv
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

import numpy as np

import spandan_ml  # noqa: F401  (backend on sys.path)
from app.analytics.rul import VERSION, RulConfig, estimate_rul, find_onset, smooth

FAILED = [(1, 3), (1, 4), (2, 1), (3, 3)]


def load_series(results_dir: str | Path) -> dict[tuple[int, int], dict]:
    """(test, bearing) → {t_days, ratio, failed_with}. Ratio = raw RMS / median RMS of the first 10 % of the test."""
    out = {}
    for test in (1, 2, 3):
        path = Path(results_dir) / f"ims_test{test}_indicators.csv"
        rows = list(csv.DictReader(path.open()))
        for b in range(1, 5):
            rb = [r for r in rows if int(r["bearing"]) == b]
            ts = np.array([datetime.strptime(r["time"], "%Y.%m.%d.%H.%M.%S").timestamp() for r in rb])
            rms = np.array([float(r["rms_raw"]) for r in rb])
            base = np.median(rms[: max(10, len(rms) // 10)])
            out[(test, b)] = {"t_days": (ts - ts[0]) / 86400, "ratio": rms / base, "failed_with": rb[0]["failed_with"]}
    return out


def failure_ratio(s: dict, cfg: RulConfig) -> float:
    """Smoothed ratio at failure (mean of the last smoothing window)."""
    return float(np.mean(smooth(s["ratio"], cfg.smooth_points)[-cfg.smooth_points:]))


def calibrate(series: dict, units: list, cfg: RulConfig, *, step: int = 6) -> tuple[float, float]:
    """10th/90th percentile of log(true / predicted median) over `units` (each predicted with the
    failure levels of the *other* units in the list, as at deployment)."""
    errs = []
    for unit in units:
        levels = tuple(failure_ratio(series[u], cfg) for u in units if u != unit) or (failure_ratio(series[unit], cfg),)
        c = replace(cfg, failure_ratios=levels, calibration=None)
        t, r = series[unit]["t_days"], series[unit]["ratio"]
        onset = find_onset(smooth(r, c.smooth_points), c)
        if onset is None:
            continue
        for i in range(onset + c.min_points, len(t), step):
            res = estimate_rul(t[: i + 1], r[: i + 1], c)
            if res.status == "ok":
                errs.append(np.log((t[-1] - t[i] + 0.05) / (res.median_days + 0.05)))
    if not errs:
        return (np.log(0.5), np.log(2.0))
    lo, hi = np.quantile(errs, [0.1, 0.9])
    return (round(float(lo), 4), round(float(hi), 4))


def evaluate(series: dict, cfg: RulConfig, *, step: int = 3, calibrated: bool = True) -> dict:
    per_unit, sweep = {}, []
    for unit in FAILED:
        s = series[unit]
        train = [u for u in FAILED if u != unit]
        train_levels = tuple(round(failure_ratio(series[u], cfg), 3) for u in train)
        c = replace(cfg, failure_ratios=train_levels,
                    calibration=calibrate(series, train, cfg) if calibrated else None)
        t, r = s["t_days"], s["ratio"]
        t_fail = t[-1]
        onset = find_onset(smooth(r, c.smooth_points), c)
        unit_res = {"failed_with": s["failed_with"], "life_days": round(float(t_fail), 2),
                    "train_failure_ratios": train_levels, "calibration": c.calibration, "own_failure_ratio": round(failure_ratio(s, c), 3),
                    "onset_days": round(float(t[onset]), 2) if onset is not None else None, "checkpoints": {}}
        # checkpoints after onset
        if onset is not None:
            for frac in (0.25, 0.5, 0.75, 0.9):
                tc = t[onset] + frac * (t_fail - t[onset])
                i = int(np.searchsorted(t, tc, side="right"))
                res = estimate_rul(t[:i], r[:i], c)
                unit_res["checkpoints"][f"after_onset_{int(frac * 100)}"] = _score(res, t_fail - t[i - 1])
            # every `step`-th snapshot after onset
            for i in range(onset + c.min_points, len(t), step):
                res = estimate_rul(t[: i + 1], r[: i + 1], c)
                sweep.append((unit, _score(res, t_fail - t[i])))
        for frac in (0.5, 0.7, 0.9):
            i = int(np.searchsorted(t, frac * t_fail, side="right"))
            unit_res["checkpoints"][f"life_{int(frac * 100)}"] = _score(estimate_rul(t[:i], r[:i], c), t_fail - t[i - 1])
        per_unit[f"ims-{unit[0]}-b{unit[1]}"] = unit_res

    def summary(items: list[dict]) -> dict:
        ok = [x for x in items if x["status"] == "ok"]
        return {"n": len(items), "n_predicted": len(ok),
                "mae_days": round(float(np.mean([abs(x["error_days"]) for x in ok])), 2) if ok else None,
                "coverage": round(float(np.mean([x["covered"] for x in ok])), 3) if ok else None,
                "low_bound_safe": round(float(np.mean([x["low_safe"] for x in ok])), 3) if ok else None,
                "late_side_misses": round(float(np.mean([x["true_rul_days"] > x["high"] for x in ok])), 3) if ok else None,
                "mean_width_days": round(float(np.mean([x["width_days"] for x in ok])), 2) if ok else None}

    after = {k: summary([u["checkpoints"][k] for u in per_unit.values() if k in u["checkpoints"]])
             for k in ("after_onset_25", "after_onset_50", "after_onset_75", "after_onset_90")}
    life = {k: {"n": len(per_unit),
                "no_degradation": sum(u["checkpoints"][k]["status"] == "no_degradation" for u in per_unit.values()),
                **summary([u["checkpoints"][k] for u in per_unit.values()])}
            for k in ("life_50", "life_70", "life_90")}

    healthy = {}
    for unit, s in series.items():
        if unit in FAILED:
            continue
        onset = find_onset(smooth(s["ratio"], cfg.smooth_points), cfg)
        healthy[f"ims-{unit[0]}-b{unit[1]}"] = {
            "onset_days_before_test_end": round(float(s["t_days"][-1] - s["t_days"][onset]), 2) if onset is not None else None}
    return {"version": VERSION, "config": {k: v for k, v in asdict(cfg).items() if k != "failure_ratios"},
            "after_onset": after, "life_checkpoints": life, "all_points_after_onset": summary([x for _, x in sweep]),
            "units": per_unit, "healthy_bearings": healthy}


def _score(res, true_rul: float) -> dict:
    d = {"status": res.status, "true_rul_days": round(float(true_rul), 2), "reason": res.reason}
    if res.status == "ok":
        d.update(low=res.low_days, median=res.median_days, high=res.high_days,
                 error_days=round(res.median_days - true_rul, 2),
                 covered=bool(res.low_days <= true_rul <= res.high_days),
                 low_safe=bool(true_rul >= res.low_days),  # the low end is the repair deadline
                 width_days=round(res.high_days - res.low_days, 2))
    return d


def plot(series: dict, cfg: RulConfig, path: str | Path, step: int = 3) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, len(FAILED), figsize=(4.2 * len(FAILED), 6.4), sharex="col")
    for col, unit in enumerate(FAILED):
        s = series[unit]
        others = [u for u in FAILED if u != unit]
        c = replace(cfg, failure_ratios=tuple(failure_ratio(series[u], cfg) for u in others))
        t, r = s["t_days"], s["ratio"]
        onset = find_onset(smooth(r, c.smooth_points), c)
        start = max(0, (onset or len(t)) - 300)
        ax = axes[0, col]
        ax.plot(t[start:], r[start:], lw=0.6, color="0.6")
        ax.plot(t[start:], smooth(r, c.smooth_points)[start:], lw=1.2, color="black")
        ax.axhline(c.onset_ratio, ls=":", color="tab:orange")
        ax.set_title(f"IMS test {unit[0]} bearing {unit[1]} ({s['failed_with'].replace('bearing_', '')})", fontsize=9)
        ax.set_ylabel("RMS / baseline")
        ax2 = axes[1, col]
        if onset is not None:
            xs, lo, med, hi = [], [], [], []
            for i in range(onset + c.min_points, len(t), step):
                res = estimate_rul(t[: i + 1], r[: i + 1], c)
                if res.status == "ok":
                    xs.append(t[i]); lo.append(res.low_days); med.append(res.median_days); hi.append(res.high_days)
            ax2.fill_between(xs, lo, hi, color="#ccff00", alpha=0.6, label="predicted 10–90 %")
            ax2.plot(xs, med, color="black", lw=1, label="predicted median")
            tt = t[onset:]
            ax2.plot(tt, t[-1] - tt, color="tab:red", lw=1.2, ls="--", label="true RUL")
        ax2.set_xlabel("days since test start")
        ax2.set_ylabel("RUL (days)")
        if col == 0:
            ax2.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main(results_dir: str, out_dir: str) -> dict:
    """Evaluate the bootstrap range (production choice) and the calibrated range side by side.

    Choice: the bootstrap range. Its misses are mostly on the safe side (the bearing lasted longer than
    predicted) and its low end, used as the repair deadline, held in ~94 % of predictions. Calibrating
    to 80 % coverage needed ranges of ~24 days, which says nothing useful to an owner."""
    cfg = RulConfig()
    series = load_series(results_dir)
    report = {"chosen": "bootstrap",
              "bootstrap": evaluate(series, cfg, calibrated=False),
              "calibrated": evaluate(series, cfg, calibrated=True)}
    out = Path(out_dir)
    (out / "rul_eval_report.json").write_text(json.dumps(report, indent=2))
    # Production config: failure levels from all four failed bearings, no range calibration
    final = replace(cfg, failure_ratios=tuple(round(failure_ratio(series[u], cfg), 3) for u in FAILED))
    (out / "rul_config_v1.json").write_text(json.dumps({"version": VERSION, **asdict(final),
                                                        "indicator": "rms_y / baseline median rms_y",
                                                        "trained_on": "NASA IMS failed bearings (4)"}, indent=2))
    plot(series, cfg, out / "rul_ims.png")
    print(json.dumps({v: {k: report[v][k] for k in ("after_onset", "all_points_after_onset")}
                      for v in ("bootstrap", "calibrated")}, indent=2))
    return report


if __name__ == "__main__":
    main(*(sys.argv[1:3] if len(sys.argv) >= 3 else ("ml/results", "ml/results")))
