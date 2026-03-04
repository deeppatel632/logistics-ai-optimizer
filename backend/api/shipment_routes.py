from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_user
from backend.core.limiter import limiter
from backend.schemas import ShipmentCreate
from backend.services.shipment_service import create_shipment_atomic, update_shipment_status
from database.connection import get_db


router = APIRouter(prefix="/shipments", tags=["Shipments"])


@router.put("/{shipment_id}/status")
def change_status(
    shipment_id: int,
    new_status: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user)
):
    return update_shipment_status(db, shipment_id, new_status, user)


@router.post("/")
@limiter.limit("20/minute")
def create_shipment(
    shipment_data: ShipmentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return create_shipment_atomic(db, shipment_data, idempotency_key)

