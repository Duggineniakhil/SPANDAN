import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approval.decision import DecisionError, decide
from app.approval.sweep import sweep
from app.config import get_settings
from app.db import get_db
from app.events import plan_in_background
from app.models import PLAN_STATES, Message, Owner, Plan
from app.schemas import DecisionIn, DecisionOut, MessageOut, PlanOut, SweepOut

router = APIRouter(tags=["approval"])


@router.get("/plans/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: uuid.UUID, db: Session = Depends(get_db)) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    return plan


@router.post("/plans/{plan_id}/decision", response_model=DecisionOut)
def plan_decision(plan_id: uuid.UUID, body: DecisionIn, background: BackgroundTasks,
                  db: Session = Depends(get_db)) -> DecisionOut:
    """Owner approves or rejects. Accepted only from the owner's registered number (403 otherwise),
    only while the plan is pending and not expired (409). Approval runs the sandbox executor."""
    try:
        outcome = decide(db, plan_id, decision=body.decision, channel=body.channel,
                         from_phone=body.from_phone, transcript=body.transcript)
    except DecisionError as e:
        raise HTTPException(e.status, e.message)
    ex = outcome.execution
    if ex and ex.replan and get_settings().agent_auto_plan:
        background.add_task(plan_in_background, outcome.plan.event_id)
    return DecisionOut(plan=PlanOut.model_validate(outcome.plan), executed=ex.executed if ex else None,
                       reason=ex.reason if ex else None, job_id=ex.job_id if ex else None,
                       replanning=bool(ex and ex.replan))


@router.get("/owners/{owner_id}/plans", response_model=list[PlanOut])
def owner_plans(owner_id: uuid.UUID, state: str | None = None, db: Session = Depends(get_db)) -> list[Plan]:
    if db.get(Owner, owner_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Owner not found")
    if state is not None and state not in PLAN_STATES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"state must be one of {list(PLAN_STATES)}")
    stmt = select(Plan).where(Plan.owner_id == owner_id)
    if state:
        stmt = stmt.where(Plan.state == state)
    return list(db.scalars(stmt.order_by(Plan.created_at.desc()).limit(50)))


@router.get("/owners/{owner_id}/messages", response_model=list[MessageOut])
def owner_messages(owner_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Message]:
    if db.get(Owner, owner_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Owner not found")
    return list(db.scalars(select(Message).where(Message.to_kind == "owner", Message.to_id == owner_id)
                           .order_by(Message.created_at.desc()).limit(50)))


@router.post("/approval/sweep", response_model=SweepOut)
def run_sweep(db: Session = Depends(get_db)) -> SweepOut:
    """Send due 24 h reminders and expire plans past 48 h now (the app also does this on a timer)."""
    r = sweep(db)
    return SweepOut(reminded=r.reminded, expired=r.expired)
