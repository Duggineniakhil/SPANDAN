"""Owner's yes/no on a pending plan (M2-15, M2-18). Only the owner's registered number can decide;
an expired plan can't be approved; approval runs the executor straight away."""
import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.approval.executor import ExecutionResult, execute_plan
from app.approval.messages import notify_owner
from app.approval.state import now_utc, release_slot, reopen_event, transition
from app.audit import audit
from app.models import Owner, Plan


class DecisionError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class DecisionOutcome:
    plan: Plan
    execution: ExecutionResult | None = None


def same_number(a: str, b: str) -> bool:
    """Compare phone numbers by their last 10 digits (+91 98765 43210 == 09876543210)."""
    da, db_ = re.sub(r"\D", "", a or ""), re.sub(r"\D", "", b or "")
    return len(da) >= 10 and da[-10:] == db_[-10:]


def expire(db: Session, plan: Plan, owner: Owner, *, actor: str = "system") -> None:
    transition(db, plan, "expired", actor=actor, details={"expires_at": plan.expires_at.isoformat()})
    release_slot(db, plan)
    reopen_event(db, plan)
    notify_owner(db, owner, "expired", plan=plan)


def check_decidable(db: Session, plan_id: uuid.UUID, *, decision: str, channel: str,
                    from_phone: str) -> tuple[Plan, Owner]:
    """The plan (locked) and owner, if this number may decide it now. Otherwise raises DecisionError
    (audited, committed): 404 no plan, 403 not the owner's number, 409 not pending or expired."""
    plan = db.get(Plan, plan_id, with_for_update=True)
    if plan is None:
        raise DecisionError(404, "Plan not found")
    owner = db.get(Owner, plan.owner_id)

    def refuse(status: int, message: str, **details) -> DecisionError:
        audit(db, actor="system", action="decision_refused", entity="plan", entity_id=plan.id,
              details={"reason": message, "decision": decision, "channel": channel, **details})
        db.commit()
        return DecisionError(status, message)

    if not same_number(from_phone, owner.phone):
        # never echo the registered number back
        raise refuse(403, "Decision not accepted: it did not come from the owner's registered number",
                     from_phone_last4=re.sub(r"\D", "", from_phone or "")[-4:])
    if plan.state == "pending" and plan.expires_at is not None and now_utc() >= plan.expires_at:
        expire(db, plan, owner)
        db.commit()
        raise refuse(409, "The plan has expired; ask for a new plan")
    if plan.state != "pending":
        raise refuse(409, f"The plan is '{plan.state}', not waiting for a decision")
    return plan, owner


def decide(db: Session, plan_id: uuid.UUID, *, decision: str, channel: str, from_phone: str,
           transcript: str | None = None) -> DecisionOutcome:
    """Apply the owner's decision. Commits. Raises DecisionError (audited) when it is refused."""
    plan, owner = check_decidable(db, plan_id, decision=decision, channel=channel, from_phone=from_phone)
    now = now_utc()
    plan.decided_at, plan.decided_via = now, channel
    details = {"channel": channel, **({"transcript": transcript} if transcript else {})}
    if decision == "reject":
        transition(db, plan, "rejected", actor="owner", details=details)
        release_slot(db, plan)
        reopen_event(db, plan)
        notify_owner(db, owner, "rejected", plan=plan)
        db.commit()
        return DecisionOutcome(plan)

    transition(db, plan, "approved", actor="owner", details=details)
    result = execute_plan(db, plan)
    db.commit()
    return DecisionOutcome(plan, result)
