import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(
    db: Session,
    *,
    actor: str,
    action: str,
    entity: str,
    entity_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Add an audit entry to the current transaction (committed with the caller's change)."""
    db.add(
        AuditLog(actor=actor, action=action, entity=entity, entity_id=entity_id, details=details or {})
    )
