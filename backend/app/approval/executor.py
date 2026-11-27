"""Executor for approved plans (M2-17). Plain code, never the LLM: it performs exactly the plan's
listed actions in the sandbox, each step audited. No payments, no machine start/stop."""
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.approval.messages import (DEALER_ORDER, MECHANIC_BOOKING, fmt_when, notify_owner, owner_text, plan_values,
                                   send)
from app.approval.state import now_utc, release_slot, reopen_event, transition
from app.audit import audit
from app.models import Job, Machine, MechanicSlot, Owner, Plan

ALLOWED_ACTIONS = {"buy_part", "book_mechanic", "schedule_downtime"}


@dataclass
class ExecutionResult:
    executed: bool
    reason: str | None = None
    job_id: uuid.UUID | None = None
    replan: bool = False  # slot was lost: the event should get a new plan


def execute_plan(db: Session, plan: Plan) -> ExecutionResult:
    """Run an approved plan. On a lost slot the plan is cancelled (nothing booked) and the event reopened.
    The caller commits."""
    if plan.state != "approved":
        raise ValueError(f"only approved plans are executed (plan is '{plan.state}')")
    owner = db.get(Owner, plan.owner_id)
    actions = plan.plan.get("actions", [])
    unknown = {a["type"] for a in actions} - ALLOWED_ACTIONS
    if unknown:  # can't happen for plans built by submit_plan; refuse rather than guess
        transition(db, plan, "cancelled", actor="system", details={"reason": f"unknown action types {sorted(unknown)}"})
        release_slot(db, plan)
        reopen_event(db, plan)
        return ExecutionResult(False, f"unknown action types {sorted(unknown)}")

    acts = {a["type"]: a for a in actions}
    book = acts["book_mechanic"]
    slot = db.get(MechanicSlot, uuid.UUID(book["slot_id"]), with_for_update=True)
    now = now_utc()
    if slot is None or slot.status != "held" or slot.held_for_event_id != plan.event_id or slot.start_at <= now:
        reason = ("the mechanic slot has already started" if slot is not None and slot.start_at <= now
                  else "the mechanic slot is no longer held for this plan")
        transition(db, plan, "cancelled", actor="system", details={"reason": reason})
        release_slot(db, plan)
        reopen_event(db, plan)
        notify_owner(db, owner, "slot_lost", plan=plan)
        return ExecutionResult(False, reason, replan=True)

    ref = str(plan.id)[:8]
    machine = db.get(Machine, uuid.UUID(plan.plan["machine_id"]))

    # 1. book the mechanic (held -> booked) and create the job
    slot.status, slot.held_until = "booked", None
    job = Job(id=uuid.uuid4(), plan_id=plan.id, mechanic_id=uuid.UUID(book["mechanic_id"]), slot_id=slot.id)
    db.add(job)
    db.flush()
    audit(db, actor="system", action="mechanic_booked", entity="job", entity_id=job.id,
          details={"plan_id": str(plan.id), "slot_id": str(slot.id), "mechanic_id": book["mechanic_id"],
                   "start": book["start"], "rate_inr": book["rate_inr"]})
    send(db, to_kind="mechanic", to_id=job.mechanic_id, kind="booking", lang="en", plan_id=plan.id,
         event_id=plan.event_id, text=MECHANIC_BOOKING.format(
             when=fmt_when(book["start"]), end=fmt_when(book["end"])[-5:], owner=owner.name, machine=machine.name,
             rate=book["rate_inr"], fault=plan.plan["fault"]["code"], ref=ref))

    # 2. confirm the part order with the dealer (no payment: the owner pays at pickup)
    part = acts.get("buy_part")
    if part:
        audit(db, actor="system", action="dealer_order_confirmed", entity="quote",
              entity_id=uuid.UUID(part["quote_id"]),
              details={"plan_id": str(plan.id), "dealer_id": part["dealer_id"], "part_code": part["part_code"],
                       "qty": part["qty"], "price_inr": part["price_inr"], "payment": "at pickup, by the owner"})
        send(db, to_kind="dealer", to_id=uuid.UUID(part["dealer_id"]), kind="order", lang="en", plan_id=plan.id,
             event_id=plan.event_id, text=DEALER_ORDER.format(
                 qty=part["qty"], part_code=part["part_code"], owner=owner.name, price=part["price_inr"], ref=ref))

    # 3. downtime on the owner's calendar (the plan record is the calendar in the prototype)
    down = acts.get("schedule_downtime")
    if down:
        audit(db, actor="system", action="downtime_scheduled", entity="machine", entity_id=machine.id,
              details={"plan_id": str(plan.id), "start": down["start"], "end": down["end"]})

    # 4. tell the owner
    values = plan_values(plan)
    lang = owner.language
    values["part_line"] = owner_text("part_line", lang, part=part["part_code"], dealer=part["dealer"],
                                     part_cost=part["price_inr"]) if part else ""
    notify_owner(db, owner, "booking_confirmed", plan=plan, **values)

    transition(db, plan, "executed", actor="system", details={"job_id": str(job.id)})
    return ExecutionResult(True, job_id=job.id)
