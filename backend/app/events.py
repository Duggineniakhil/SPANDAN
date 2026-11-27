"""Anomaly events: opened by the phone or by the server rule, then diagnosed and handed to the agent."""
import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.worker import diagnose_event
from app.audit import audit
from app.config import get_settings
from app.models import AnomalyEvent, Machine, Telemetry

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


def plan_in_background(event_id: uuid.UUID) -> None:
    """Run the coordinator agent for an event in its own DB session (FastAPI background task)."""
    from app.agent.planner import run_planner
    from app.db import SessionLocal

    with SessionLocal() as db:
        try:
            run_planner(db, event_id)
        except Exception:  # never let a background failure go unnoticed
            log.exception("planner crashed for event %s", event_id)
            db.rollback()
            audit(db, actor="system", action="agent_crashed", entity="anomaly_event", entity_id=event_id)
            db.commit()
