"""Analytics worker (M2-26): on an anomaly event → diagnosis + RUL → `diagnoses` row → agent.

Diagnosis
  * With raw alert windows from the device: physics rules (rules.py) on every window, combined with the
    CWRU-trained classifier for the bearing faults. The classifier only knows bearing faults and was
    trained on a different machine, so it is weighted below the rules:
        bearing fault:  1 − (1 − rule) · (1 − 0.6 · classifier)
        other faults:   rule score
    Best below 0.5 → `unknown` (the owner is asked to get it inspected).
  * Without raw windows: the earlier feature-ratio rules (diagnosis_v0), so phones that only send
    features still work.
RUL
  * From telemetry `rms_y` against the machine's own baseline readings (rows without a score), one
    reading = `reading_interval_min`. Recomputed on every upload while the event is open.
  * No trend yet → a conservative default repair window (`default_repair_days`), labelled as such.
"""
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import diagnosis_v0
from app.analytics.artifacts import classify, diagnosis_model, rul_config
from app.analytics.features import window_features
from app.analytics.rul import VERSION as RUL_VERSION
from app.analytics.rul import estimate_rul
from app.analytics.rules import VERSION as RULES_VERSION
from app.analytics.rules import baseline_from, score_window
from app.audit import audit
from app.config import get_settings
from app.models import AnomalyEvent, Diagnosis, Machine, RawWindow, Telemetry

CLASSIFIER_WEIGHT = 0.6
UNKNOWN_BELOW = 0.5
ALERT_WINDOW_MAX_AGE = timedelta(hours=2)
FAULT_ORDER = ("bearing_outer", "bearing_inner", "bearing_ball", "imbalance", "misalignment", "looseness")


# ---------- raw windows ----------

def store_windows(db: Session, machine: Machine, kind: str, ts: datetime, fs: int, rpm: float | None,
                  windows: list[list[float]]) -> int:
    for w in windows:
        db.add(RawWindow(id=uuid.uuid4(), machine_id=machine.id, kind=kind, ts=ts, fs=fs, rpm=rpm,
                         samples=np.asarray(w, dtype="<f4").tobytes()))
    db.flush()
    keep = get_settings().raw_windows_keep
    old = select(RawWindow.id).where(RawWindow.machine_id == machine.id, RawWindow.kind == kind) \
        .order_by(RawWindow.ts.desc(), RawWindow.created_at.desc()).offset(keep)
    db.execute(delete(RawWindow).where(RawWindow.id.in_(old)))
    return len(windows)


def _load(db: Session, machine: Machine, kind: str, since: datetime | None = None, limit: int = 3) -> list[RawWindow]:
    stmt = select(RawWindow).where(RawWindow.machine_id == machine.id, RawWindow.kind == kind)
    if since is not None:
        stmt = stmt.where(RawWindow.created_at >= since)
    return list(db.scalars(stmt.order_by(RawWindow.ts.desc(), RawWindow.created_at.desc()).limit(limit)))


def _samples(w: RawWindow) -> np.ndarray:
    return np.frombuffer(w.samples, dtype="<f4").astype(float)


# ---------- diagnosis ----------

def diagnose_windows(machine: Machine, alert: list[RawWindow], baseline: list[RawWindow]) -> tuple[list[dict], dict]:
    """Rank faults from raw windows (rules + classifier). Returns (faults, model_versions)."""
    rpm = lambda w: w.rpm or machine.motor_rpm  # noqa: E731
    base = baseline_from([score_window(_samples(w), w.fs, rpm=rpm(w), bearing_model=machine.bearing_model)
                          for w in baseline]) if baseline else None
    artifact = diagnosis_model()
    rule_scores: dict[str, list[float]] = {}
    evidence: dict[str, tuple[float, str]] = {}
    clf: dict[str, list[float]] = {}
    for w in alert:
        y = _samples(w)
        report = score_window(y, w.fs, rpm=rpm(w), bearing_model=machine.bearing_model, baseline=base)
        for s in report.scores:
            rule_scores.setdefault(s.fault, []).append(s.score or 0.0)
            if s.score is not None and s.score >= evidence.get(s.fault, (-1, ""))[0]:
                evidence[s.fault] = (s.score, s.evidence)
        if artifact is not None and w.fs == artifact.get("fs", w.fs):
            feats = window_features(y, w.fs, rpm=rpm(w), bearing_model=machine.bearing_model or "")
            for c, p in classify(artifact, feats).items():
                clf.setdefault(c, []).append(p)

    rule = {f: float(np.mean(v)) for f, v in rule_scores.items()}
    prob = {c: float(np.mean(v)) for c, v in clf.items()}
    combined = {}
    for f in FAULT_ORDER:
        r = rule.get(f, 0.0)
        if f.startswith("bearing_") and f in prob:
            combined[f] = 1 - (1 - r) * (1 - CLASSIFIER_WEIGHT * prob[f])
        else:
            combined[f] = r

    def ev(f: str) -> str:
        text = evidence.get(f, (0, ""))[1]
        if f in prob and prob[f] >= 0.2:
            text += f"; trained classifier (CWRU bearings): {prob[f]:.0%}"
        return text.lstrip("; ")

    ranked = sorted(combined, key=combined.get, reverse=True)
    faults = [{"fault": f, "confidence": round(combined[f], 2), "evidence": ev(f)} for f in ranked[:3]]
    if faults[0]["confidence"] < UNKNOWN_BELOW:
        best = faults[0]
        faults = [{"fault": "unknown", "confidence": best["confidence"],
                   "evidence": f"Vibration changed, but no known fault pattern stands out (closest: "
                               f"{best['fault'].replace('_', ' ')}, {best['confidence']:.0%})."}] + faults[:2]
    versions = {"diagnosis": RULES_VERSION + ("+" + artifact["version"] if artifact and prob else ""),
                "windows": str(len(alert)), "baseline_windows": str(len(baseline))}
    return faults, versions


# ---------- RUL ----------

def live_rul(db: Session, machine: Machine) -> dict:
    """RUL from telemetry rms_y vs baseline. Returns diagnosis fields: low, high, status, details."""
    settings = get_settings()
    base_rows = db.scalars(select(Telemetry.features).where(
        Telemetry.machine_id == machine.id, Telemetry.anomaly_score.is_(None)).order_by(Telemetry.ts.desc()).limit(500)).all()
    base_vals = [f["rms_y"] for f in base_rows if isinstance(f.get("rms_y"), (int, float)) and f["rms_y"] > 0]
    rows = db.scalars(select(Telemetry.features).where(
        Telemetry.machine_id == machine.id, Telemetry.anomaly_score.is_not(None)).order_by(Telemetry.ts.desc()).limit(3000)).all()
    vals = [f.get("rms_y") for f in reversed(rows)]
    vals = [v for v in vals if isinstance(v, (int, float)) and v > 0]
    default = {"low": settings.default_repair_days, "high": None}
    if not base_vals or not vals:
        return {**default, "status": "default_window", "reason": "no baseline rms_y readings"}
    ratio = np.asarray(vals) / float(np.median(base_vals))
    t = np.arange(len(ratio)) * settings.reading_interval_min / 1440.0
    res = estimate_rul(t, ratio, rul_config())
    if res.status == "ok":
        return {"low": res.low_days, "high": res.high_days, "status": "ok", "reason": f"R² {res.r2}",
                "median": res.median_days, "current_ratio": res.current_ratio}
    return {**default, "status": "default_window", "reason": f"{res.status}: {res.reason}",
            "current_ratio": res.current_ratio}


# ---------- entry points ----------

def diagnose_event(db: Session, machine: Machine, event: AnomalyEvent) -> Diagnosis:
    since = datetime.now(UTC) - ALERT_WINDOW_MAX_AGE
    alert = _load(db, machine, "alert", since=since, limit=3)
    if alert:
        faults, versions = diagnose_windows(machine, alert, _load(db, machine, "baseline", limit=3))
    else:
        faults = diagnosis_v0.rank_faults(*diagnosis_v0.feature_rows(db, machine))
        versions = {"diagnosis": diagnosis_v0.MODEL_VERSIONS["diagnosis"], "windows": "0"}
    known = faults[0]["fault"] != "unknown"
    rul = live_rul(db, machine) if known else {"low": None, "high": None, "status": "insufficient_data",
                                               "reason": "no clear fault"}
    diagnosis = Diagnosis(id=uuid.uuid4(), event_id=event.id, faults=faults, rul_days_low=rul["low"],
                          rul_days_high=rul["high"], rul_status=rul["status"],
                          model_versions={**versions, "rul": RUL_VERSION, "rul_reason": rul.get("reason", "")})
    db.add(diagnosis)
    return diagnosis


def refresh_rul(db: Session, machine: Machine) -> Diagnosis | None:
    """New readings arrived: update days-left on the open event's latest diagnosis."""
    from app.events import OPEN_STATUSES

    event = db.scalars(select(AnomalyEvent).where(AnomalyEvent.machine_id == machine.id,
                                                  AnomalyEvent.status.in_(OPEN_STATUSES))
                       .order_by(AnomalyEvent.started_at.desc())).first()
    if event is None:
        return None
    diag = db.scalars(select(Diagnosis).where(Diagnosis.event_id == event.id)
                      .order_by(Diagnosis.created_at.desc())).first()
    if diag is None or diag.rul_status == "insufficient_data":
        return None
    rul = live_rul(db, machine)
    if (rul["status"], rul["low"], rul["high"]) == (diag.rul_status, diag.rul_days_low, diag.rul_days_high):
        return None
    if rul["status"] != diag.rul_status:
        audit(db, actor="system", action="rul_updated", entity="anomaly_event", entity_id=event.id,
              details={"from": diag.rul_status, "to": rul["status"], "low": rul["low"], "high": rul["high"]})
    diag.rul_days_low, diag.rul_days_high, diag.rul_status = rul["low"], rul["high"], rul["status"]
    diag.model_versions = {**(diag.model_versions or {}), "rul_reason": rul.get("reason", "")}
    return diag
