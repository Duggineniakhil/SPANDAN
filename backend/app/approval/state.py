"""Plan state machine (doc 06 §5). Every transition is checked and audited."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.audit import audit
from app.models import AnomalyEvent, MechanicSlot, Plan

TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"pending", "cancelled"}),
    "pending": frozenset({"approved", "rejected", "expired", "cancelled"}),
    "approved": frozenset({"executed", "cancelled"}),
    "rejected": frozenset(),
    "expired": frozenset(),
    "executed": frozenset(),
    "cancelled": frozenset(),
}


class TransitionError(Exception):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def transition(db: Session, plan: Plan, to: str, *, actor: str, details: dict[str, Any] | None = None) -> None:
    if to not in TRANSITIONS.get(plan.state, frozenset()):
        raise TransitionError(f"plan is '{plan.state}'; cannot move to '{to}'")
    frm, plan.state = plan.state, to
    audit(db, actor=actor, action=f"plan_{to}", entity="plan", entity_id=plan.id,
          details={"from": frm, "to": to, **(details or {})})


def release_slot(db: Session, plan: Plan) -> bool:
    """Free the slot this plan was holding (only if it is still held for this plan's event)."""
    slot_id = next((a["slot_id"] for a in plan.plan.get("actions", []) if a["type"] == "book_mechanic"), None)
    slot = db.get(MechanicSlot, slot_id, with_for_update=True) if slot_id else None
    if slot is None or slot.status != "held" or slot.held_for_event_id != plan.event_id:
        return False
    slot.status, slot.held_for_event_id, slot.held_until = "free", None, None
    audit(db, actor="system", action="slot_released", entity="mechanic_slot", entity_id=slot.id,
          details={"plan_id": str(plan.id)})
    return True


def reopen_event(db: Session, plan: Plan) -> None:
    """The plan is gone; the event waits for a new plan (manual, or automatic after a lost slot)."""
    event = db.get(AnomalyEvent, plan.event_id)
    if event is not None and event.status == "planned":
        event.status = "diagnosed"
