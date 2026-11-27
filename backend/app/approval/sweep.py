"""Reminder and expiry sweep (M2-16): reminder after 24 h without a reply, expiry at 48 h.
Never auto-approves: silence means no action."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.approval.decision import expire
from app.approval.messages import notify_owner, plan_values
from app.approval.state import now_utc
from app.audit import audit
from app.models import Owner, Plan

log = logging.getLogger(__name__)
REMIND_AFTER = timedelta(hours=24)


@dataclass
class SweepResult:
    reminded: int = 0
    expired: int = 0


def sweep(db: Session, now: datetime | None = None) -> SweepResult:
    now = now or now_utc()
    result = SweepResult()
    plans = db.scalars(select(Plan).where(Plan.state == "pending").order_by(Plan.created_at)
                       .with_for_update(skip_locked=True)).all()
    for plan in plans:
        owner = db.get(Owner, plan.owner_id)
        if plan.expires_at is not None and now >= plan.expires_at:
            expire(db, plan, owner)
            result.expired += 1
        elif plan.reminded_at is None and now >= plan.created_at + REMIND_AFTER:
            plan.reminded_at = now
            notify_owner(db, owner, "reminder", plan=plan, **plan_values(plan))
            audit(db, actor="system", action="plan_reminder_sent", entity="plan", entity_id=plan.id,
                  details={"expires_at": plan.expires_at.isoformat() if plan.expires_at else None})
            result.reminded += 1
    db.commit()
    return result


async def sweep_loop(interval_s: float) -> None:
    """Background loop started by the app (see app.main lifespan)."""
    from app.db import SessionLocal

    while True:
        try:
            def _run() -> SweepResult:
                with SessionLocal() as db:
                    return sweep(db)
            r = await asyncio.to_thread(_run)
            if r.reminded or r.expired:
                log.info("approval sweep: %s reminded, %s expired", r.reminded, r.expired)
        except Exception:
            log.exception("approval sweep failed")
        await asyncio.sleep(interval_s)
