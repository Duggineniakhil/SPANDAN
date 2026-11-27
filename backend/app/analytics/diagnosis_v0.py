"""Feature-ratio fault ranking (v0): the fallback when the device sent no raw windows.

Compares the latest readings with this machine's baseline readings on a few physics-based
indicators and ranks the likely faults. Used by app/analytics/worker.py.
"""
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Machine, Telemetry

MODEL_VERSIONS = {"diagnosis": "ratio-rules-v0"}

# fault → [(feature, plain-language evidence)]
INDICATORS: dict[str, list[tuple[str, str]]] = {
    "bearing_outer": [
        ("env_bpfo_y", "envelope peak at the bearing outer-race frequency (BPFO)"),
        ("kurtosis_y", "impulsiveness (kurtosis)"),
    ],
    "imbalance": [("amp_1x_y", "vibration at 1× shaft speed")],
    "looseness": [
        ("amp_3x_y", "vibration at 3× shaft speed"),
        ("band_0_25_y", "sub-synchronous (½×) vibration"),
    ],
}

MIN_RATIO = 1.5  # below this nothing stands out → "unknown"


def _mean(rows: list[dict], name: str) -> float | None:
    vals = [r[name] for r in rows if isinstance(r.get(name), (int, float))]
    return sum(vals) / len(vals) if vals else None


def rank_faults(baseline: list[dict], recent: list[dict]) -> list[dict]:
    scores: dict[str, tuple[float, str]] = {}
    for fault, indicators in INDICATORS.items():
        best = (0.0, "")
        for feature, label in indicators:
            b, r = _mean(baseline, feature), _mean(recent, feature)
            if not b or r is None or b <= 0:
                continue
            ratio = r / b
            if ratio > best[0]:
                best = (ratio, f"{label} is {ratio:.1f}× its normal level")
        scores[fault] = best

    if not scores or max(s[0] for s in scores.values()) < MIN_RATIO:
        return [{"fault": "unknown", "confidence": 0.0, "evidence": "No known fault signature stands out."}]

    # softmax over log-ratios → confidence
    logits = {f: math.log(max(s[0], 1e-6)) * 2.0 for f, s in scores.items()}
    z = sum(math.exp(v) for v in logits.values())
    ranked = sorted(scores, key=lambda f: logits[f], reverse=True)
    return [
        {"fault": f, "confidence": round(math.exp(logits[f]) / z, 2), "evidence": scores[f][1] or "no change"}
        for f in ranked[:3]
    ]


def current_rows(machine: Machine, scored: bool) -> list:
    """Filters for this machine's readings since its current baseline: baseline readings (no anomaly
    score) received since the baseline started, scored readings since it was completed. After a repair
    the machine learns a new baseline, so older readings must not mix in (M2-32)."""
    where = [Telemetry.machine_id == machine.id]
    if scored:
        where.append(Telemetry.anomaly_score.is_not(None))
        if machine.baseline_done_at is not None:
            where.append(Telemetry.received_at >= machine.baseline_done_at)
    else:
        where.append(Telemetry.anomaly_score.is_(None))
        if machine.baseline_started_at is not None:
            where.append(Telemetry.received_at >= machine.baseline_started_at)
    return where


def feature_rows(db: Session, machine: Machine) -> tuple[list[dict], list[dict]]:
    """(baseline feature rows, latest monitoring feature rows). Baseline readings carry no anomaly score."""
    baseline_rows = db.scalars(
        select(Telemetry.features).where(*current_rows(machine, scored=False))
        .order_by(Telemetry.ts.desc()).limit(200)
    ).all()
    recent_rows = db.scalars(
        select(Telemetry.features).where(*current_rows(machine, scored=True))
        .order_by(Telemetry.ts.desc()).limit(5)
    ).all()
    return list(baseline_rows), list(recent_rows)
