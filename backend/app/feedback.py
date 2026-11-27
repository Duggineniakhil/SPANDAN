"""Repair feedback (M2-32) and false alarms (M2-33): the labels that close the loop.

- Job card: what the mechanic actually found → label for retraining, the event is resolved, and the
  machine learns a new baseline (a repaired machine vibrates differently).
- False alarm: the owner says nothing is wrong → label, any pending plan is withdrawn, and this
  machine's alert threshold goes up 5 % per false alarm since its last baseline (at most +30 %).
"""
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.approval.decision import same_number
from app.approval.messages import fault_text, notify_owner
from app.approval.state import release_slot, transition
from app.audit import audit
from app.events import OPEN_STATUSES
from app.models import AnomalyEvent, Diagnosis, FeedbackLabel, Job, Machine, Mechanic, MechanicSlot, Owner, Plan

# FOR NO KEY UPDATE: we change status columns, never keys, so we must not wait on rows that merely
# reference these (e.g. the agent's quotes hold a key-share lock on the event while it plans).
NO_KEY = {"key_share": True}

FALSE_ALARM_STEP = 0.05
FALSE_ALARM_MAX = 0.30


class FeedbackError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _refuse(db: Session, status: int, message: str, *, action: str, entity: str, entity_id: uuid.UUID,
            **details) -> FeedbackError:
    audit(db, actor="system", action=action, entity=entity, entity_id=entity_id, details={"reason": message, **details})
    db.commit()
    return FeedbackError(status, message)


def _last4(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")[-4:]


def job_view(db: Session, job: Job) -> dict:
    slot = db.get(MechanicSlot, job.slot_id)
    return {"id": job.id, "plan_id": job.plan_id, "status": job.status, "mechanic": db.get(Mechanic, job.mechanic_id).name,
            "start": slot.start_at, "end": slot.end_at, "job_card": job.job_card}


def event_jobs(db: Session, event_id: uuid.UUID) -> list[dict]:
    jobs = db.scalars(select(Job).join(Plan, Plan.id == Job.plan_id).where(Plan.event_id == event_id)
                      .order_by(Job.id)).all()
    return [job_view(db, j) for j in jobs]


# ---------- job card (M2-32) ----------

@dataclass
class JobCardResult:
    job: Job
    event: AnomalyEvent
    machine: Machine
    diagnosis_correct: bool | None


def submit_job_card(db: Session, job_id: uuid.UUID, *, actual_fault: str, parts_replaced: list[str], notes: str,
                    from_phone: str) -> JobCardResult:
    job = db.get(Job, job_id, with_for_update=NO_KEY)
    if job is None:
        raise FeedbackError(404, "Job not found")
    plan = db.get(Plan, job.plan_id)
    event = db.get(AnomalyEvent, plan.event_id, with_for_update=NO_KEY)
    machine = db.get(Machine, event.machine_id, with_for_update=NO_KEY)
    owner = db.get(Owner, plan.owner_id)
    mechanic = db.get(Mechanic, job.mechanic_id)

    if same_number(from_phone, mechanic.phone):
        submitted_by = "mechanic"
    elif same_number(from_phone, owner.phone):
        submitted_by = "owner"
    else:
        raise _refuse(db, 403, "Job card not accepted: it did not come from the mechanic's or the owner's number",
                      action="job_card_refused", entity="job", entity_id=job.id, from_phone_last4=_last4(from_phone))
    if job.status != "scheduled":
        raise _refuse(db, 409, f"The job is already '{job.status}'", action="job_card_refused", entity="job",
                      entity_id=job.id)

    diagnosis = db.scalars(select(Diagnosis).where(Diagnosis.event_id == event.id)
                           .order_by(Diagnosis.created_at.desc())).first()
    predicted = diagnosis.faults[0]["fault"] if diagnosis and diagnosis.faults else None
    correct = None if predicted in (None, "unknown") or actual_fault == "other" else predicted == actual_fault
    now = datetime.now(UTC)
    job.status = "done"
    job.job_card = {"actual_fault": actual_fault, "parts_replaced": parts_replaced, "notes": notes,
                    "submitted_by": submitted_by, "submitted_at": now.isoformat(),
                    "predicted_fault": predicted, "diagnosis_correct": correct}
    db.add(FeedbackLabel(id=uuid.uuid4(), machine_id=machine.id, event_id=event.id, label=actual_fault,
                         source="job_card", created_at=now))
    audit(db, actor="mechanic" if submitted_by == "mechanic" else "owner", action="job_card_submitted",
          entity="job", entity_id=job.id, details={**job.job_card, "event_id": str(event.id)})

    event.status = "resolved"
    audit(db, actor="system", action="event_resolved", entity="anomaly_event", entity_id=event.id,
          details={"job_id": str(job.id), "actual_fault": actual_fault})

    # A repaired machine vibrates differently: learn its normal again before monitoring.
    previous = machine.state
    machine.state, machine.baseline_started_at, machine.baseline_done_at = "baseline", now, None
    audit(db, actor="system", action="baseline_started", entity="machine", entity_id=machine.id,
          details={"from_state": previous, "reason": "repair done (job card)", "job_id": str(job.id)})

    notify_owner(db, owner, "job_done", event_id=event.id, machine=machine.name,
                 fault=fault_text(actual_fault, owner.language))
    db.commit()
    return JobCardResult(job, event, machine, correct)


# ---------- false alarm (M2-33) ----------

@dataclass
class FalseAlarmResult:
    event: AnomalyEvent
    machine: Machine
    raise_pct: float
    cancelled_plan_id: uuid.UUID | None


def mark_false_alarm(db: Session, event_id: uuid.UUID, *, from_phone: str, note: str = "") -> FalseAlarmResult:
    event = db.get(AnomalyEvent, event_id, with_for_update=NO_KEY)
    if event is None:
        raise FeedbackError(404, "Alert not found")
    machine = db.get(Machine, event.machine_id, with_for_update=NO_KEY)
    owner = db.get(Owner, machine.owner_id)

    def refuse(status: int, message: str, **details) -> FeedbackError:
        return _refuse(db, status, message, action="false_alarm_refused", entity="anomaly_event",
                       entity_id=event.id, **details)

    if not same_number(from_phone, owner.phone):
        raise refuse(403, "Not accepted: only the owner's registered number can mark a false alarm",
                     from_phone_last4=_last4(from_phone))
    if event.status not in OPEN_STATUSES:
        raise refuse(409, f"The alert is already '{event.status}'")
    plans = db.scalars(select(Plan).where(Plan.event_id == event.id).with_for_update(key_share=True)).all()
    if any(p.state in ("approved", "executed") for p in plans):
        # someone is coming: their job card records what they find ("no_fault_found" if nothing)
        raise refuse(409, "A mechanic is already booked for this alert; the job card will record what they find")

    cancelled = None
    for p in plans:
        if p.state in ("draft", "pending"):
            transition(db, p, "cancelled", actor="owner", details={"reason": "owner marked a false alarm"})
            release_slot(db, p)
            cancelled = p.id

    event.status = "false_alarm"
    # same clock as baseline_done_at (the app's, not the database's) for the count below
    db.add(FeedbackLabel(id=uuid.uuid4(), machine_id=machine.id, event_id=event.id, label="false_alarm",
                         source="owner", created_at=datetime.now(UTC)))
    db.flush()
    since = machine.baseline_done_at or machine.created_at
    n = db.scalar(select(func.count()).select_from(FeedbackLabel).where(
        FeedbackLabel.machine_id == machine.id, FeedbackLabel.label == "false_alarm",
        FeedbackLabel.created_at >= since)) or 1
    raise_pct = min(FALSE_ALARM_STEP * n, FALSE_ALARM_MAX)
    base = machine.threshold_base or machine.anomaly_threshold
    old = machine.anomaly_threshold
    if base is not None:
        machine.threshold_base = base
        machine.anomaly_threshold = round(base * (1 + raise_pct), 6)
    if machine.state == "alert":
        machine.state = "monitoring"
    audit(db, actor="owner", action="false_alarm_marked", entity="anomaly_event", entity_id=event.id,
          details={"note": note, "cancelled_plan_id": str(cancelled) if cancelled else None,
                   "threshold_from": old, "threshold_to": machine.anomaly_threshold,
                   "raise_pct": round(raise_pct * 100, 1), "false_alarms_since_baseline": n})
    notify_owner(db, owner, "false_alarm", event_id=event.id, machine=machine.name)
    db.commit()
    return FalseAlarmResult(event, machine, raise_pct, cancelled)
