from sqlalchemy.orm import Session
from database.models import Warehouse
from backend.schemas import WarehouseCreate
from datetime import datetime


def create_warehouse(db: Session, tenant_id: int, data):
    warehouse = Warehouse(
        name=data.name,
        location=data.location,
        tenant_id=tenant_id
    )
    db.add(warehouse)
    db.commit()
    db.refresh(warehouse)
    return warehouse

def get_warehouse(db: Session, tenant_id: int, warehouse_id: int):
    return db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.tenant_id == tenant_id,
        Warehouse.is_deleted == False
    ).first()

def list_warehouses(db: Session, tenant_id: int):
    return db.query(Warehouse).filter(
        Warehouse.tenant_id == tenant_id,
        Warehouse.is_deleted == False
    ).all()

def delete_warehouse(db: Session, tenant_id: int, warehouse_id: int):
    warehouse = db.query(Warehouse).filter(
        Warehouse.id == warehouse_id,
        Warehouse.tenant_id == tenant_id,
        Warehouse.is_deleted == False
    ).first()

    if not warehouse:
        return None

    warehouse.is_deleted = True
    warehouse.deleted_at = datetime.utcnow()

    db.commit()
    return warehouse