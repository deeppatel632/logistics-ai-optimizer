from sqlalchemy.orm import Session
from database.models import Warehouse
from backend.schemas import WarehouseCreate
from datetime import datetime


def create_warehouse(db: Session, data: WarehouseCreate):
    warehouse = Warehouse(**data.dict())
    db.add(warehouse)
    db.flush()  # Get ID before commit
    return warehouse

def get_warehouse(db: Session, warehouse_id: int):
    return db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()

def list_warehouses(db: Session):
    return db.query(Warehouse).all()

def delete_warehouse(db: Session, warehouse_id: int):
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if warehouse:
        warehouse.is_deleted = True
        warehouse.deleted_at = datetime.utcnow()

    return warehouse