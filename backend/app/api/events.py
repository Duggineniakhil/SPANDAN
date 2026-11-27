import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.events import OPEN_STATUSES, open_event, plan_in_background
from app.feedback import event_jobs
from app.models import AnomalyEvent, Diagnosis, Machine, Plan
from app.schemas import (AnomalyEventDetail, AnomalyEventIn, AnomalyEventOut, DiagnosisOut, JobOut, PlannerResultOut,
                         PlanOut)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/anomaly", response_model=AnomalyEventOut)
def report_anomaly(body: AnomalyEventIn, response: Response, background: BackgroundTasks,
                   db: Session = Depends(get_db)) -> AnomalyEvent:
    """Phone reports a confirmed anomaly. Returns the open event if one already exists (200),
    otherwise creates, diagnoses and (if enabled) plans it (201)."""
    machine = db.get(Machine, body.machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
    event, created = open_event(db, machine, body.started_at, body.peak_score, source="phone")
    db.commit()
    if created:
        response.status_code = status.HTTP_201_CREATED
        if get_settings().agent_auto_plan:
            background.add_task(plan_in_background, event.id)
    return event


@router.get("", response_model=list[AnomalyEventOut])
def list_events(machine_id: uuid.UUID, open_only: bool = False, db: Session = Depends(get_db)) -> list[AnomalyEvent]:
    stmt = select(AnomalyEvent).where(AnomalyEvent.machine_id == machine_id)
    if open_only:
        stmt = stmt.where(AnomalyEvent.status.in_(OPEN_STATUSES))
    return list(db.scalars(stmt.order_by(AnomalyEvent.started_at.desc()).limit(50)))


@router.get("/{event_id}", response_model=AnomalyEventDetail)
def get_event(event_id: uuid.UUID, db: Session = Depends(get_db)) -> AnomalyEventDetail:
    event = db.get(AnomalyEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    diagnosis = db.scalars(select(Diagnosis).where(Diagnosis.event_id == event_id)
                           .order_by(Diagnosis.created_at.desc())).first()
    plans = db.scalars(select(Plan).where(Plan.event_id == event_id).order_by(Plan.created_at.desc())).all()
    detail = AnomalyEventDetail.model_validate(event)
    detail.diagnosis = DiagnosisOut.model_validate(diagnosis) if diagnosis else None
    detail.plans = [PlanOut.model_validate(p) for p in plans]
    detail.jobs = [JobOut(**j) for j in event_jobs(db, event_id)]
    return detail


@router.post("/{event_id}/plan", response_model=PlannerResultOut)
def plan_event(event_id: uuid.UUID, db: Session = Depends(get_db)) -> PlannerResultOut:
    """Run the coordinator agent now (synchronous; can take up to the agent timeout)."""
    from app.agent.planner import run_planner

    if db.get(AnomalyEvent, event_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return PlannerResultOut(**run_planner(db, event_id).__dict__)
