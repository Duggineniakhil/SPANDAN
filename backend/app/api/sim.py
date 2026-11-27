from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.sim.seed import reset

router = APIRouter(prefix="/sim", tags=["sandbox"])


@router.post("/reset")
def reset_sandbox(db: Session = Depends(get_db)) -> dict[str, int]:
    """Wipe and recreate the sandbox dealers, parts, mechanics and calendars (demo only)."""
    counts = reset(db)
    audit(db, actor="operator", action="sandbox_reset", entity="sandbox", details=counts)
    db.commit()
    return counts
