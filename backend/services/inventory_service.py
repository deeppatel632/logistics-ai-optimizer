from sqlalchemy.orm import Session
from sqlalchemy import select
from database.models import Inventory
from fastapi import HTTPException
from backend.core.redis_client import redis_client
import json
from sqlalchemy.exc import NoResultFound


def get_inventory(db: Session, warehouse_id: int, product_id: int):

    cache_key = f"inventory:{warehouse_id}:{product_id}"

    cached = redis_client.get(cache_key)
    if cached:
        return json.loads(cached)

    inventory = (
        db.query(Inventory)
        .filter(
            Inventory.warehouse_id == warehouse_id,
            Inventory.product_id == product_id
        )
        .first()
    )

    if not inventory:
        return None

    data = {
        "warehouse_id": warehouse_id,
        "product_id": product_id,
        "quantity": inventory.quantity
    }

    redis_client.set(cache_key, json.dumps(data), ex=60)

    return data

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
    redis_client.delete(f"inventory:{warehouse_id}:{product_id}")
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

def reserve_inventory(
    db: Session,
    warehouse_id: int,
    product_id: int,
    quantity: int,
):
    """
    Lock inventory row and deduct stock safely.
    """

    stmt = (
        select(Inventory)
        .where(
            Inventory.warehouse_id == warehouse_id,
            Inventory.product_id == product_id,
        )
        .with_for_update()
    )

    inventory = db.execute(stmt).scalar_one_or_none()

    if not inventory:
        raise Exception("Inventory record not found.")

    if inventory.quantity < quantity:
        raise Exception("Insufficient stock.")

    inventory.quantity -= quantity

    return inventory