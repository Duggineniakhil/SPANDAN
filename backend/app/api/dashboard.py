"""Read endpoints for the dashboard and the owner app (M2-04)."""
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import Float, cast, false, func, literal, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.events import OPEN_STATUSES
from app.models import AUDIT_ACTORS, AnomalyEvent, AuditLog, Diagnosis, Job, Machine, Plan, Quote, Telemetry
from app.schemas import (AnomalyEventOut, AuditOut, HealthOut, LastReading, LatestDiagnosisOut, TelemetryPoint,
                         TelemetrySeries)

router = APIRouter(tags=["dashboard"])

MAX_RANGE = timedelta(days=60)
FEATURE_NAME = re.compile(r"^[a-z0-9_]{1,40}$")


def _machine(db: Session, machine_id: uuid.UUID) -> Machine:
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
    return machine


def _range(frm: datetime | None, to: datetime | None, default: timedelta) -> tuple[datetime, datetime]:
    to = to or datetime.now(UTC)
    frm = frm or to - default
    if frm >= to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'from' must be before 'to'")
    if to - frm > MAX_RANGE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "range is limited to 60 days")
    return frm, to


def _feature(name: str):
    return Telemetry.features[name].as_float()


@router.get("/machines/{machine_id}/telemetry", response_model=TelemetrySeries)
def machine_telemetry(
    machine_id: uuid.UUID,
    frm: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: AwareDatetime | None = None,
    features: Annotated[str | None, Query(description="Comma-separated feature names, max 10")] = None,
    max_points: Annotated[int, Query(ge=10, le=2000)] = 500,
    db: Session = Depends(get_db),
) -> TelemetrySeries:
    """Time series for charts (default: last 24 h). Long ranges are bucketed to at most `max_points`."""
    _machine(db, machine_id)
    frm, to = _range(frm, to, timedelta(hours=24))
    names = [n.strip() for n in (features or "").split(",") if n.strip()]
    if len(names) > 10 or not all(FEATURE_NAME.match(n) for n in names):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "features: up to 10 names of [a-z0-9_]")

    where = (Telemetry.machine_id == machine_id, Telemetry.ts >= frm, Telemetry.ts < to)
    total = db.scalar(select(func.count()).select_from(Telemetry).where(*where))

    if total <= max_points:
        rows = db.execute(select(Telemetry.ts, Telemetry.anomaly_score, Telemetry.health_index,
                                 Telemetry.rpm_estimate, *[_feature(n).label(f"f_{n}") for n in names])
                          .where(*where).order_by(Telemetry.ts)).all()
        points = [TelemetryPoint(ts=r.ts, anomaly_score=r.anomaly_score, health_index=r.health_index,
                                 rpm_estimate=r.rpm_estimate, features={n: getattr(r, f"f_{n}") for n in names})
                  for r in rows]
        return TelemetrySeries(machine_id=machine_id, from_ts=frm, to_ts=to, total_rows=total,
                               downsampled=False, points=points)

    step = (to - frm).total_seconds() / max_points
    bucket = func.floor((func.extract("epoch", Telemetry.ts) - frm.timestamp()) / literal(step, Float)).label("b")
    rows = db.execute(
        select(bucket, func.min(Telemetry.ts).label("ts"),
               func.max(Telemetry.anomaly_score).label("score"),  # worst case in the bucket
               func.min(Telemetry.health_index).label("health"),
               cast(func.avg(Telemetry.rpm_estimate), Float).label("rpm"),
               *[cast(func.avg(_feature(n)), Float).label(f"f_{n}") for n in names])
        .where(*where).group_by(bucket).order_by(bucket)
    ).all()
    points = [TelemetryPoint(ts=r.ts, anomaly_score=r.score, health_index=r.health, rpm_estimate=r.rpm,
                             features={n: getattr(r, f"f_{n}") for n in names}) for r in rows]
    return TelemetrySeries(machine_id=machine_id, from_ts=frm, to_ts=to, total_rows=total, downsampled=True,
                           bucket_seconds=step, points=points)


@router.get("/machines/{machine_id}/health", response_model=HealthOut)
def machine_health(machine_id: uuid.UUID, db: Session = Depends(get_db)) -> HealthOut:
    """Latest health index and score, machine state, open event and pending plan (home screen)."""
    machine = _machine(db, machine_id)
    now = datetime.now(UTC)
    last = db.scalars(select(Telemetry).where(Telemetry.machine_id == machine_id)
                      .order_by(Telemetry.ts.desc()).limit(1)).first()
    n24 = db.scalar(select(func.count()).select_from(Telemetry)
                    .where(Telemetry.machine_id == machine_id, Telemetry.ts >= now - timedelta(hours=24)))
    event = db.scalars(select(AnomalyEvent).where(AnomalyEvent.machine_id == machine_id,
                                                  AnomalyEvent.status.in_(OPEN_STATUSES))
                       .order_by(AnomalyEvent.started_at.desc())).first()
    pending = db.scalar(select(Plan.id).where(Plan.event_id == event.id, Plan.state == "pending")
                        .order_by(Plan.created_at.desc())) if event else None
    return HealthOut(
        machine_id=machine.id, state=machine.state, anomaly_threshold=machine.anomaly_threshold,
        last_reading=LastReading(ts=last.ts, anomaly_score=last.anomaly_score, health_index=last.health_index,
                                 received_at=last.received_at) if last else None,
        minutes_since_last_reading=round((now - last.ts).total_seconds() / 60, 1) if last else None,
        readings_24h=n24, open_event=AnomalyEventOut.model_validate(event) if event else None,
        pending_plan_id=pending,
    )


@router.get("/machines/{machine_id}/diagnosis/latest", response_model=LatestDiagnosisOut)
def latest_diagnosis(machine_id: uuid.UUID, db: Session = Depends(get_db)) -> Diagnosis:
    """Top faults with evidence and the RUL range of the machine's most recent diagnosis."""
    _machine(db, machine_id)
    diag = db.scalars(select(Diagnosis).join(AnomalyEvent, AnomalyEvent.id == Diagnosis.event_id)
                      .where(AnomalyEvent.machine_id == machine_id)
                      .order_by(Diagnosis.created_at.desc()).limit(1)).first()
    if diag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No diagnosis for this machine yet")
    return diag


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    machine_id: uuid.UUID | None = None,
    frm: Annotated[AwareDatetime | None, Query(alias="from")] = None,
    to: AwareDatetime | None = None,
    actor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    """Audit trail, newest first. With `machine_id`: entries about the machine, its events, plans,
    jobs and quotes, plus slot changes made for its plans."""
    if actor is not None and actor not in AUDIT_ACTORS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"actor must be one of {list(AUDIT_ACTORS)}")
    stmt = select(AuditLog)
    if frm:
        stmt = stmt.where(AuditLog.ts >= frm)
    if to:
        stmt = stmt.where(AuditLog.ts < to)
    if actor:
        stmt = stmt.where(AuditLog.actor == actor)
    if machine_id:
        _machine(db, machine_id)
        event_ids = list(db.scalars(select(AnomalyEvent.id).where(AnomalyEvent.machine_id == machine_id)))
        plan_ids = list(db.scalars(select(Plan.id).where(Plan.event_id.in_(event_ids)))) if event_ids else []
        job_ids = list(db.scalars(select(Job.id).where(Job.plan_id.in_(plan_ids)))) if plan_ids else []
        quote_ids = list(db.scalars(select(Quote.id).where(Quote.event_id.in_(event_ids)))) if event_ids else []
        ids = [machine_id, *event_ids, *plan_ids, *job_ids, *quote_ids]
        by_plan = (AuditLog.details["plan_id"].astext.in_([str(p) for p in plan_ids]) if plan_ids else false())
        stmt = stmt.where(or_(AuditLog.entity_id.in_(ids), by_plan))
    return list(db.scalars(stmt.order_by(AuditLog.id.desc()).limit(limit)))
