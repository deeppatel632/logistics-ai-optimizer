from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_tenant_id, get_current_user
from backend.core.limiter import limiter
from backend.schemas import ShipmentCreate, ShipmentResponse
from backend.services.shipment_service import create_shipment_atomic, update_shipment_status
from database.connection import get_db, get_read_db
from database.models import Shipment


router = APIRouter(prefix="/shipments", tags=["Shipments"])


# ---------------------------------------------------
# List Shipments
# ---------------------------------------------------

@router.get("/", response_model=List[ShipmentResponse])
def list_shipments(
    status: Optional[str] = Query(default=None, description="Filter by status: Pending, InTransit, Delivered, Cancelled"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_read_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    """Return all shipments for the current tenant, optionally filtered by status."""
    q = db.query(Shipment).filter(
        Shipment.tenant_id == tenant_id,
        Shipment.is_deleted.is_(False),
    )
    if status:
        q = q.filter(Shipment.status == status)
    return q.order_by(Shipment.id.desc()).offset(skip).limit(limit).all()


# ---------------------------------------------------
# Get single Shipment
# ---------------------------------------------------

@router.get("/{shipment_id}", response_model=ShipmentResponse)
def get_shipment(
    shipment_id: int,
    db: Session = Depends(get_read_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    shipment = db.query(Shipment).filter(
        Shipment.id == shipment_id,
        Shipment.tenant_id == tenant_id,
        Shipment.is_deleted.is_(False),
    ).first()
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


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
    request: Request,
    shipment_data: ShipmentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return create_shipment_atomic(db, shipment_data, idempotency_key)

