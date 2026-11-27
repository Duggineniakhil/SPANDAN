"""Repair feedback endpoints (M2-32, M2-33)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.feedback import FeedbackError, job_view, mark_false_alarm, submit_job_card
from app.schemas import AnomalyEventOut, FalseAlarmIn, FalseAlarmOut, JobCardIn, JobCardOut, JobOut

router = APIRouter(tags=["feedback"])


@router.post("/jobs/{job_id}/job-card", response_model=JobCardOut)
def job_card(job_id: uuid.UUID, body: JobCardIn, db: Session = Depends(get_db)) -> JobCardOut:
    """After the repair: what was actually wrong and what was replaced. Accepted from the booked mechanic's
    or the owner's number (403), once (409). Resolves the alert, stores the label, and puts the machine
    into a new baseline: the phone must learn normal vibration again before it monitors."""
    try:
        r = submit_job_card(db, job_id, actual_fault=body.actual_fault, parts_replaced=body.parts_replaced,
                            notes=body.notes, from_phone=body.from_phone)
    except FeedbackError as e:
        raise HTTPException(e.status, e.message)
    return JobCardOut(job=JobOut(**job_view(db, r.job)), event_status=r.event.status, machine_state=r.machine.state,
                      diagnosis_correct=r.diagnosis_correct)


@router.post("/alerts/{event_id}/false-alarm", response_model=FalseAlarmOut)
def false_alarm(event_id: uuid.UUID, body: FalseAlarmIn, db: Session = Depends(get_db)) -> FalseAlarmOut:
    """Owner says the alert was wrong. Only from the owner's number (403), only while the alert is open
    and nobody is booked yet (409). Withdraws a pending plan, and raises this machine's threshold by
    5 % per false alarm since its last baseline (max +30 %)."""
    try:
        r = mark_false_alarm(db, event_id, from_phone=body.from_phone, note=body.note)
    except FeedbackError as e:
        raise HTTPException(e.status, e.message)
    m = r.machine
    return FalseAlarmOut(event=AnomalyEventOut.model_validate(r.event), machine_state=m.state,
                         anomaly_threshold=m.anomaly_threshold, threshold_base=m.threshold_base,
                         threshold_raise_pct=round(r.raise_pct * 100, 1), cancelled_plan_id=r.cancelled_plan_id)
