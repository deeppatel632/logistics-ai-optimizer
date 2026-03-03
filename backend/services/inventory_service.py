from sqlalchemy.orm import Session
from sqlalchemy import select
from database.models import Inventory
from fastapi import HTTPException

def deduct_stock(db: Session, warehouse_id: int, product_id: int, quantity: int):
    inventory = (
        db.query(Inventory)
        .filter(
            Inventory.warehouse_id == warehouse_id,
            Inventory.product_id == product_id
        )
        .with_for_update()
        .first()
    )

    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory not found")

    if inventory.quantity < quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    inventory.quantity -= quantity
    db.flush()
def create_inventory(db: Session, warehouse_id: int, product_id: int, quantity: int):
    inventory = Inventory(
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity=quantity
    )
    db.add(inventory)
    db.flush()
    return inventory