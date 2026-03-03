from sqlalchemy.orm import Session
from database.models import Warehouse
from backend.schemas import WarehouseCreate

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
        db.delete(warehouse)
    return warehouse