"""Placeholder fault diagnosis (v0) until the trained models land (tasks M2-19 – M2-26).

Compares the latest readings with this machine's baseline readings on a few physics-based
indicators and ranks the likely faults. RUL is a fixed placeholder range, clearly labelled.
"""
import math
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnomalyEvent, Diagnosis, Machine, Telemetry

MODEL_VERSIONS = {"diagnosis": "ratio-rules-v0", "rul": "placeholder-v0"}

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
PLACEHOLDER_RUL = (4.0, 8.0)


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


def diagnose(db: Session, machine: Machine, event: AnomalyEvent) -> Diagnosis:
    # Baseline readings carry no anomaly score; monitoring readings do.
    baseline_rows = db.scalars(
        select(Telemetry.features).where(Telemetry.machine_id == machine.id, Telemetry.anomaly_score.is_(None))
        .order_by(Telemetry.ts.desc()).limit(200)
    ).all()
    recent_rows = db.scalars(
        select(Telemetry.features).where(Telemetry.machine_id == machine.id, Telemetry.anomaly_score.is_not(None))
        .order_by(Telemetry.ts.desc()).limit(5)
    ).all()

    faults = rank_faults(list(baseline_rows), list(recent_rows))
    known = faults[0]["fault"] != "unknown"
    diagnosis = Diagnosis(
        id=uuid.uuid4(),
        event_id=event.id,
        faults=faults,
        rul_days_low=PLACEHOLDER_RUL[0] if known else None,
        rul_days_high=PLACEHOLDER_RUL[1] if known else None,
        rul_status="placeholder" if known else "insufficient_data",
        model_versions=MODEL_VERSIONS,
    )
    db.add(diagnosis)
    return diagnosis
