import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import audit
from app.db import get_db
from app.models import Owner
from app.schemas import OwnerCreate, OwnerOut

router = APIRouter(prefix="/owners", tags=["owners"])


@router.post("", response_model=OwnerOut, status_code=status.HTTP_201_CREATED)
def create_owner(body: OwnerCreate, db: Session = Depends(get_db)) -> Owner:
    owner = Owner(**body.model_dump(mode="json"))
    db.add(owner)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "An owner with this phone already exists")
    audit(db, actor="operator", action="owner_created", entity="owner", entity_id=owner.id,
          details={"language": owner.language, "spending_limit_inr": owner.spending_limit_inr})
    db.commit()
    return owner


@router.get("/{owner_id}", response_model=OwnerOut)
def get_owner(owner_id: uuid.UUID, db: Session = Depends(get_db)) -> Owner:
    owner = db.get(Owner, owner_id)
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Owner not found")
    return owner
