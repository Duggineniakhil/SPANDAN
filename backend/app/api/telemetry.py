from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.events import check_server_rule, plan_in_background
from app.models import Machine, Telemetry
from app.schemas import RejectedRow, TelemetryBatch, TelemetryBatchResult

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


@router.post("/batch", response_model=TelemetryBatchResult)
def upload_batch(batch: TelemetryBatch, background: BackgroundTasks, db: Session = Depends(get_db)) -> TelemetryBatchResult:
    """Idempotent upload of feature rows from the phone.

    - A whole malformed batch → 422 (the phone retries later).
    - Rows with an already-stored `row_id` count as duplicates (safe to resend).
    - Rows with an out-of-range timestamp are rejected individually.
    """
    machine = db.get(Machine, batch.machine_id)
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")

    settings = get_settings()
    now = datetime.now(UTC)
    latest_ok = now + timedelta(minutes=settings.max_future_skew_minutes)
    earliest_ok = now - timedelta(days=settings.max_row_age_days)

    rejected: list[RejectedRow] = []
    values: list[dict] = []
    seen: set = set()
    in_batch_duplicates = 0

    for row in batch.rows:
        if row.ts > latest_ok:
            rejected.append(RejectedRow(row_id=row.row_id, reason="timestamp_in_future"))
            continue
        if row.ts < earliest_ok:
            rejected.append(RejectedRow(row_id=row.row_id, reason="timestamp_too_old"))
            continue
        if row.row_id in seen:
            in_batch_duplicates += 1
            continue
        seen.add(row.row_id)
        values.append({**row.model_dump(), "machine_id": batch.machine_id, "device_id": batch.device_id})

    accepted = 0
    if values:
        stmt = (
            insert(Telemetry)
            .values(values)
            .on_conflict_do_nothing(index_elements=[Telemetry.row_id])
            .returning(Telemetry.row_id)
        )
        accepted = len(db.execute(stmt).all())

    duplicates = in_batch_duplicates + (len(values) - accepted)
    audit(db, actor="device", action="telemetry_batch", entity="machine", entity_id=batch.machine_id,
          details={"device_id": batch.device_id, "accepted": accepted,
                   "duplicates": duplicates, "rejected": len(rejected)})
    opened = check_server_rule(db, machine) if accepted else None
    db.commit()
    if opened and opened[1] and settings.agent_auto_plan:
        background.add_task(plan_in_background, opened[0].id)
    return TelemetryBatchResult(accepted=accepted, duplicates=duplicates, rejected=rejected)
