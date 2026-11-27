import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics.worker import store_windows
from app.audit import audit
from app.db import get_db
from app.models import Machine, Owner
from app.schemas import BaselineComplete, MachineCreate, MachineOut, RawWindowsIn, RawWindowsOut

router = APIRouter(prefix="/machines", tags=["machines"])

# States from which a (new) baseline may start: first setup, or after a repair.
BASELINE_START_FROM = {"setup", "monitoring", "maintenance"}


def _get_machine(db: Session, machine_id: uuid.UUID, *, lock: bool = False) -> Machine:
    stmt = select(Machine).where(Machine.id == machine_id)
    if lock:
        stmt = stmt.with_for_update()
    machine = db.scalars(stmt).first()
    if machine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
    return machine


@router.post("", response_model=MachineOut, status_code=status.HTTP_201_CREATED)
def create_machine(body: MachineCreate, db: Session = Depends(get_db)) -> Machine:
    if db.get(Owner, body.owner_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Owner not found")
    machine = Machine(**body.model_dump())
    db.add(machine)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This sensor is already paired with another machine")
    audit(db, actor="operator", action="machine_registered", entity="machine", entity_id=machine.id,
          details={"owner_id": str(machine.owner_id), "sensor_id": machine.sensor_id})
    db.commit()
    return machine


@router.get("", response_model=list[MachineOut])
def list_machines(owner_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Machine]:
    return list(db.scalars(select(Machine).where(Machine.owner_id == owner_id).order_by(Machine.created_at)))


@router.get("/{machine_id}", response_model=MachineOut)
def get_machine(machine_id: uuid.UUID, db: Session = Depends(get_db)) -> Machine:
    return _get_machine(db, machine_id)


@router.post("/{machine_id}/baseline/start", response_model=MachineOut)
def start_baseline(machine_id: uuid.UUID, db: Session = Depends(get_db)) -> Machine:
    machine = _get_machine(db, machine_id, lock=True)
    if machine.state not in BASELINE_START_FROM:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot start baseline while machine is '{machine.state}'")
    previous = machine.state
    machine.state = "baseline"
    machine.baseline_started_at = datetime.now(UTC)
    machine.baseline_done_at = None
    audit(db, actor="operator", action="baseline_started", entity="machine", entity_id=machine.id,
          details={"from_state": previous})
    db.commit()
    return machine


@router.post("/{machine_id}/baseline/complete", response_model=MachineOut)
def complete_baseline(machine_id: uuid.UUID, body: BaselineComplete, db: Session = Depends(get_db)) -> Machine:
    machine = _get_machine(db, machine_id, lock=True)
    if machine.state != "baseline":
        raise HTTPException(status.HTTP_409_CONFLICT, "Machine is not in baseline")
    machine.state = "monitoring"
    machine.anomaly_threshold = machine.threshold_base = body.anomaly_threshold
    machine.model_version = body.model_version
    machine.baseline_done_at = datetime.now(UTC)
    audit(db, actor="device", action="baseline_completed", entity="machine", entity_id=machine.id,
          details=body.model_dump())
    db.commit()
    return machine


@router.post("/{machine_id}/windows", response_model=RawWindowsOut, status_code=status.HTTP_201_CREATED)
def upload_windows(machine_id: uuid.UUID, body: RawWindowsIn, db: Session = Depends(get_db)) -> RawWindowsOut:
    """Up to 3 raw radial-axis windows (g): a few from the baseline, and the last ones before an alert
    (send these before the alert's readings and `POST /events/anomaly`). Used for diagnosis."""
    machine = _get_machine(db, machine_id)
    n = store_windows(db, machine, body.kind, body.ts, body.fs, body.rpm, body.windows)
    audit(db, actor="device", action="raw_windows_uploaded", entity="machine", entity_id=machine.id,
          details={"kind": body.kind, "count": n, "fs": body.fs, "samples": len(body.windows[0])})
    db.commit()
    return RawWindowsOut(stored=n)
