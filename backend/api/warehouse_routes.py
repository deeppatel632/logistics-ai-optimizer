from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from database.connection import get_db
from backend.schemas import ShipmentCreate, WarehouseCreate, WarehouseResponse
from backend.services import warehouse_service
from backend.services.shipment_service import (
    create_shipment_atomic,
    update_shipment_status,
)
from backend.core.limiter import limiter  # ← FIXED location


router = APIRouter(prefix="/warehouses", tags=["Warehouses"])


# ---------------------------------------------------
# Shipment Creation (Rate Limited + Idempotent)
# ---------------------------------------------------

@router.post("/shipments")
@limiter.limit("20/minute")
def create_shipment(
    shipment_data: ShipmentCreate,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    return create_shipment_atomic(db, shipment_data, idempotency_key)


# ---------------------------------------------------
# Shipment Status Update
# ---------------------------------------------------

@router.put("/shipments/{shipment_id}/status")
def change_status(
    shipment_id: int,
    new_status: str,
    db: Session = Depends(get_db),
):
    return update_shipment_status(db, shipment_id, new_status)


# ---------------------------------------------------
# Warehouse CRUD
# ---------------------------------------------------

@router.post("/", response_model=WarehouseResponse)
def create(data: WarehouseCreate, db: Session = Depends(get_db)):
    return warehouse_service.create_warehouse(db, data)


@router.get("/", response_model=list[WarehouseResponse])
def list_all(db: Session = Depends(get_db)):
    return warehouse_service.list_warehouses(db)


@router.get("/{warehouse_id}", response_model=WarehouseResponse)
def get_one(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = warehouse_service.get_warehouse(db, warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return warehouse


@router.delete("/{warehouse_id}")
def delete(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = warehouse_service.delete_warehouse(db, warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return {"message": "Deleted successfully"}