"""Anomaly events: opened by the phone or by the server rule, then diagnosed and handed to the agent."""
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.worker import diagnose_event
from app.audit import audit
from app.config import get_settings
from app.models import AnomalyEvent, Diagnosis, Machine, Plan, Telemetry

log = logging.getLogger(__name__)

OPEN_STATUSES = ("open", "diagnosed", "planned")


def open_event(db: Session, machine: Machine, started_at: datetime, peak_score: float | None, source: str) -> tuple[AnomalyEvent, bool]:
    """Return the machine's open event (updating its peak) or create and diagnose a new one."""
    existing = db.scalars(
        select(AnomalyEvent).where(AnomalyEvent.machine_id == machine.id, AnomalyEvent.status.in_(OPEN_STATUSES))
        .order_by(AnomalyEvent.started_at.desc()).with_for_update()
    ).first()
    if existing:
        if peak_score is not None and (existing.peak_score is None or peak_score > existing.peak_score):
            existing.peak_score = peak_score
        return existing, False

    event = AnomalyEvent(id=uuid.uuid4(), machine_id=machine.id, started_at=started_at, peak_score=peak_score, source=source)
    db.add(event)
    machine.state = "alert"
    db.flush()
    audit(db, actor="device" if source == "phone" else "system", action="anomaly_event_opened",
          entity="anomaly_event", entity_id=event.id, details={"source": source, "peak_score": peak_score})

    diagnosis = diagnose_event(db, machine, event)
    event.status = "diagnosed"
    audit(db, actor="system", action="event_diagnosed", entity="anomaly_event", entity_id=event.id,
          details={"faults": diagnosis.faults, "rul_status": diagnosis.rul_status})
    return event, True


def rediagnose_if_unclear(db: Session, machine: Machine) -> AnomalyEvent | None:
    """An early alert often comes before the fault has a clear signature (the detector reacts to any
    change; the rules need the fault's own frequencies). While the open alert is still "unknown" and
    unplanned, fresh alert windows are diagnosed again. Returns the event if the fault is now clear."""
    event = db.scalars(select(AnomalyEvent).where(AnomalyEvent.machine_id == machine.id,
                                                  AnomalyEvent.status == "diagnosed")
                       .order_by(AnomalyEvent.started_at.desc()).with_for_update(key_share=True)).first()
    if event is None:
        return None
    last = db.scalars(select(Diagnosis).where(Diagnosis.event_id == event.id)
                      .order_by(Diagnosis.created_at.desc())).first()
    planned = db.scalar(select(Plan.id).where(Plan.event_id == event.id,
                                              Plan.state.in_(("draft", "pending", "approved", "executed"))))
    if planned or (last and last.faults and last.faults[0]["fault"] != "unknown"):
        return None
    diagnosis = diagnose_event(db, machine, event)
    top = diagnosis.faults[0]
    audit(db, actor="system", action="event_rediagnosed", entity="anomaly_event", entity_id=event.id,
          details={"faults": diagnosis.faults, "rul_status": diagnosis.rul_status})
    return event if top["fault"] != "unknown" else None


def check_server_rule(db: Session, machine: Machine) -> tuple[AnomalyEvent, bool] | None:
    """Backup alert: the last N scored readings are all above the machine's threshold."""
    if machine.state != "monitoring" or machine.anomaly_threshold is None:
        return None
    n = get_settings().server_alert_consecutive
    rows = db.execute(
        select(Telemetry.ts, Telemetry.anomaly_score).where(Telemetry.machine_id == machine.id)
        .order_by(Telemetry.ts.desc()).limit(n)
    ).all()
    if len(rows) < n or any(r.anomaly_score is None or r.anomaly_score <= machine.anomaly_threshold for r in rows):
        return None
    return open_event(db, machine, rows[-1].ts, max(r.anomaly_score for r in rows), source="server")


def plan_in_background(event_id: uuid.UUID, owner_request: str | None = None) -> None:
    """Run the coordinator agent for an event in its own DB session (FastAPI background task),
    then pre-generate the new plan's voice note."""
    from app.agent.planner import run_planner
    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            result = run_planner(db, event_id, owner_request=owner_request)
        except Exception:  # never let a background failure go unnoticed
            log.exception("planner crashed for event %s", event_id)
            db.rollback()
            audit(db, actor="system", action="agent_crashed", entity="anomaly_event", entity_id=event_id)
            db.commit()
            return
    if result.plan_id is not None:
        # TTS as soon as the rules accept the plan, so the note is ready when the owner opens it
        from app.voice.notes import prepare_note_in_background

        prepare_note_in_background(result.plan_id)
