from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.dependencies import get_current_tenant_id
from backend.schemas import WarehouseCreate, WarehouseResponse
from backend.services import warehouse_service
from database.connection import get_read_db, get_write_db

router = APIRouter(prefix="/warehouses", tags=["Warehouses"])


# ---------------------------------------------------
# Create Warehouse
# ---------------------------------------------------

@router.post("/", response_model=WarehouseResponse)
def create(data: WarehouseCreate, db: Session = Depends(get_write_db)):
    return warehouse_service.create_warehouse(db, data)


# ---------------------------------------------------
# List Warehouses
# ---------------------------------------------------

@router.get("/")
def list_all(
    db: Session = Depends(get_read_db),
    tenant_id: int = Depends(get_current_tenant_id),
):
    return warehouse_service.list_warehouses(db, tenant_id)


# ---------------------------------------------------
# Get Warehouse
# ---------------------------------------------------

@router.get("/{warehouse_id}", response_model=WarehouseResponse)
def get_one(warehouse_id: int, db: Session = Depends(get_read_db)):
    warehouse = warehouse_service.get_warehouse(db, warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return warehouse


# ---------------------------------------------------
# Delete Warehouse
# ---------------------------------------------------

@router.delete("/{warehouse_id}")
def delete(warehouse_id: int, db: Session = Depends(get_write_db)):
    warehouse = warehouse_service.delete_warehouse(db, warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return {"message": "Deleted successfully"}