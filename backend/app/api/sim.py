from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.models import Message
from app.schemas import MessageOut
from app.sim.seed import reset

router = APIRouter(prefix="/sim", tags=["sandbox"])


@router.post("/reset")
def reset_sandbox(db: Session = Depends(get_db)) -> dict[str, int]:
    """Wipe and recreate the sandbox dealers, parts, mechanics and calendars (demo only)."""
    counts = reset(db)
    audit(db, actor="operator", action="sandbox_reset", entity="sandbox", details=counts)
    db.commit()
    return counts


@router.get("/messages", response_model=list[MessageOut])
def sandbox_inbox(to_kind: Literal["dealer", "mechanic"], db: Session = Depends(get_db)) -> list[Message]:
    """What the simulated dealers / mechanics were sent (order and booking confirmations)."""
    return list(db.scalars(select(Message).where(Message.to_kind == to_kind)
                           .order_by(Message.created_at.desc()).limit(50)))
