from fastapi import APIRouter, Depends, HTTPException,Header
from sqlalchemy.orm import Session
from database.connection import get_db
from backend.schemas import ShipmentCreate, ShipmentResponse, ShipmentStatusUpdate
from backend.services import shipment_service
from fastapi import Path
from backend.services.shipment_service import (
    create_shipment_atomic,
    update_shipment_status,
)
from backend.core.limiter import limiter


router = APIRouter(prefix="/shipments", tags=["Shipments"])



@router.put("/{shipment_id}/status")
def change_status(
    shipment_id: int,
    new_status: str,
    db: Session = Depends(get_db),
):
    return update_shipment_status(db, shipment_id, new_status)

@router.post("/")
@limiter.limit("20/minute")
def create_shipment(
    shipment_data: ShipmentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return create_shipment_atomic(db, shipment_data, idempotency_key)

