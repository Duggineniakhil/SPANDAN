"""Physics rule scorer for fault diagnosis (M2-21, doc 05 §2a).

Works on one raw window (radial axis, optionally the axial axis too):
  * bearing faults: envelope-spectrum peaks at BPFO / BPFI / 2×BSF (±2 %) and their harmonics,
    measured as prominence over the local noise floor; BPFI also checks ±1× shaft sidebands and
    2×BSF the ±cage sidebands
  * imbalance: 1× shaft amplitude against the machine's own baseline (or 1× dominance without one)
  * misalignment: 2× relative to 1×, plus axial vs radial vibration when the axial axis is given
  * looseness: many shaft harmonics (3×–10×) and half-order components

Each fault gets a score in [0, 1] with a plain evidence sentence. The scores are also inputs for the
classifier (M2-22). Thresholds were set on simulated windows (app/sim/vibration.py) and must be
re-checked on CWRU / IMS / bench data.
"""
import math
from dataclasses import dataclass, field

import numpy as np

from app.analytics.bearings import FaultOrders, fault_orders, lookup
from app.analytics.signal import Spectrum, amplitude_spectrum, envelope_spectrum, estimate_shaft_hz

VERSION = "rules-v1"
TOL = 0.02          # ±2 % around each fault frequency (slip, speed error)
MIN_TOL_HZ = 0.75   # never narrower than about one bin
STANDS_OUT = 0.3    # below this no fault is called


@dataclass
class RuleScore:
    fault: str
    score: float | None  # None = could not be evaluated (e.g. unknown bearing)
    evidence: str


@dataclass
class RuleReport:
    shaft_hz: float
    fault_hz: dict[str, float]
    measurements: dict[str, float]
    scores: list[RuleScore] = field(default_factory=list)  # sorted, best first
    version: str = VERSION

    def ranked(self) -> list[dict]:
        return [{"fault": s.fault, "score": s.score, "evidence": s.evidence} for s in self.scores]

    @property
    def top(self) -> RuleScore | None:
        best = self.scores[0] if self.scores else None
        return best if best and best.score is not None and best.score >= STANDS_OUT else None

    def features(self) -> dict[str, float]:
        """Flat numbers for the classifier."""
        return {**self.measurements, **{f"rule_{s.fault}": s.score or 0.0 for s in self.scores}}


def _clip01(v: float) -> float:
    return float(min(1.0, max(0.0, v)))


def _prominence(env: Spectrum, f: float) -> tuple[float, float]:
    """(found frequency, peak / local noise floor) for a peak expected at f."""
    tol = max(TOL * f, MIN_TOL_HZ)
    found, amp = env.peak(f, tol)
    floor = env.floor(0.8 * f, 1.2 * f, exclude=[(f - tol, f + tol)])
    return found, amp / floor if floor > 0 else 0.0


def _bearing_score(env: Spectrum, name: str, label: str, f0: float, order: float,
                   sidebands_hz: float | None, sideband_label: str) -> tuple[RuleScore, dict]:
    found, p1 = _prominence(env, f0)
    harmonics = [k for k in (2, 3) if _prominence(env, k * f0)[1] >= 2.0]
    side = 0
    if sidebands_hz:
        side = sum(_prominence(env, f0 + s)[1] >= 2.0 for s in (-sidebands_hz, sidebands_hz))
    support = len(harmonics) / 2 * 0.7 + side / 2 * 0.3 if sidebands_hz else len(harmonics) / 2
    score = _clip01((math.log2(max(p1, 1e-9)) - 1) / 4) * (0.7 + 0.3 * support)  # prominence 2× → 0, 32× → 1
    if p1 >= 2:
        ev = f"Envelope peak at {found:.1f} Hz = {label} ({order:.2f}× shaft), {p1:.1f}× the noise floor"
        if harmonics:
            ev += "; harmonics " + ", ".join(f"{k}×" for k in harmonics) + " present"
        if side:
            ev += f"; {sideband_label} sidebands present"
    else:
        ev = f"No envelope peak at {label} ({f0:.1f} Hz)"
    return RuleScore(name, round(score, 3), ev), {f"env_prom_{name}": round(p1, 3)}


def score_window(y: np.ndarray, fs: float, *, rpm: float | None = None, bearing_model: str | None = None,
                 z: np.ndarray | None = None, baseline: dict[str, float] | None = None) -> RuleReport:
    """Score one window. `baseline`: median `measurements` of healthy windows of this machine (see
    `baseline_from`); without it imbalance can only be judged from 1× dominance."""
    spec = amplitude_spectrum(y, fs)
    f1 = estimate_shaft_hz(spec, rpm / 60 if rpm else None)
    amps = [spec.peak(k * f1, 1.0)[1] for k in range(1, 11)]
    a1 = amps[0] or 1e-12
    half = sum(spec.peak((k + 0.5) * f1, 1.0)[1] for k in range(5))
    m: dict[str, float] = {
        "shaft_hz": round(f1, 3),
        **{f"amp_{k}x": round(a, 6) for k, a in enumerate(amps[:3], start=1)},
        "ratio_2x_1x": round(amps[1] / a1, 4),
        "harmonic_richness": round(sum(amps[2:]) / a1, 4),
        "half_order_ratio": round(half / a1, 4),
    }
    scores: list[RuleScore] = []
    fault_hz: dict[str, float] = {"1x": f1}

    # ---- bearing defects (envelope spectrum) ----
    bearing = lookup(bearing_model)
    if bearing is None:
        for name in ("bearing_outer", "bearing_inner", "bearing_ball"):
            scores.append(RuleScore(name, None, f"Bearing model {bearing_model!r} is not in the geometry table"))
    else:
        o: FaultOrders = fault_orders(bearing)
        fault_hz.update({k: round(v, 3) for k, v in o.hz(f1).items()})
        env = envelope_spectrum(y, fs)
        for name, label, order, side, side_label in (
            ("bearing_outer", "BPFO", o.bpfo, None, ""),
            ("bearing_inner", "BPFI", o.bpfi, f1, "±1× shaft"),
            ("bearing_ball", "2×BSF", 2 * o.bsf, o.ftf * f1, "±cage"),
        ):
            s, extra = _bearing_score(env, name, label, order * f1, order, side, side_label)
            if bearing.approximate:
                s.evidence += " (approximate bearing geometry)"
            scores.append(s)
            m.update(extra)

    # ---- shaft-related faults (plain spectrum) ----
    r21 = m["ratio_2x_1x"]
    rich, halfr = m["harmonic_richness"], m["half_order_ratio"]
    loose = _clip01((rich - 0.25) / 0.5) * 0.7 + _clip01((halfr - 0.1) / 0.2) * 0.3
    scores.append(RuleScore("looseness", round(loose, 3),
                            f"Shaft harmonics 3×–10× add up to {rich:.0%} of 1×; half-order components {halfr:.0%}"))

    axial = None
    if z is not None:
        zs = amplitude_spectrum(z, fs)
        za = zs.peak(f1, 1.0)[1] + zs.peak(2 * f1, 1.0)[1]
        axial = za / (amps[0] + amps[1]) if amps[0] + amps[1] > 0 else 0.0
        m["axial_radial_ratio"] = round(axial, 4)
    mis = _clip01((r21 - 0.5) / 1.0)
    mis *= (0.4 + 0.6 * _clip01((axial - 0.5) / 0.5)) if axial is not None else 0.7
    mis *= 1 - _clip01((rich - 0.3) / 0.5)  # lots of higher harmonics points to looseness instead
    ev = f"2× shaft ({2 * f1:.1f} Hz) is {r21:.0%} of 1×"
    ev += f"; axial vibration is {axial:.1f}× radial" if axial is not None else "; no axial axis to confirm"
    scores.append(RuleScore("misalignment", round(mis, 3), ev))

    if baseline and baseline.get("amp_1x"):
        ratio = amps[0] / baseline["amp_1x"]
        imb = _clip01((math.log2(max(ratio, 1e-9)) - 0.5) / 1.5)  # 1.4× baseline → 0, 4× → 1
        imb *= 1 - _clip01((r21 - 0.5) / 1.0)
        ev = f"1× shaft ({f1:.1f} Hz) is {ratio:.1f}× its baseline level"
    else:
        imb = _clip01((0.25 - r21) / 0.2) * 0.5  # capped: weak evidence without a baseline
        ev = f"1× shaft ({f1:.1f} Hz) dominates (2× is {r21:.0%} of it); no baseline to compare"
    scores.append(RuleScore("imbalance", round(imb, 3), ev))

    scores.sort(key=lambda s: -1 if s.score is None else s.score, reverse=True)
    return RuleReport(shaft_hz=f1, fault_hz=fault_hz, measurements=m, scores=scores)


def baseline_from(reports: list[RuleReport]) -> dict[str, float]:
    """Median measurements over healthy windows: the machine's own reference."""
    keys = set.intersection(*(set(r.measurements) for r in reports)) if reports else set()
    return {k: float(np.median([r.measurements[k] for r in reports])) for k in keys}
