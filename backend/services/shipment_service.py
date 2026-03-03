from flask import app
from sqlalchemy.orm import Session
from fastapi import HTTPException, Request
from database.models import Shipment
from backend.services.inventory_service import deduct_stock, reserve_inventory
from backend.services.dispatch_service import get_available_vehicle_for_update
from backend.core.db_retry import retry_on_deadlock
from fastapi import HTTPException
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
import time
import logging



logger = logging.getLogger(__name__)

def update_shipment_status(db: Session, shipment_id: int, new_status: str):

    shipment = db.query(Shipment).filter(
        Shipment.id == shipment_id
    ).with_for_update().first()

    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")

    current_status = shipment.status

    if new_status not in ALLOWED_TRANSITIONS.get(current_status, []):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transition from {current_status} to {new_status}"
        )

    shipment.status = new_status

    return shipment

class RequestLoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        request_id = str(uuid.uuid4())
        start_time = time.time()

        logger.info(f"[{request_id}] Incoming request: {request.method} {request.url}")

        response = await call_next(request)

        duration = round((time.time() - start_time) * 1000, 2)

        logger.info(f"[{request_id}] Completed in {duration}ms | Status {response.status_code}")

        return response


app.add_middleware(RequestLoggingMiddleware)

ALLOWED_TRANSITIONS = {
    "Pending": ["Assigned", "Cancelled"],
    "Assigned": ["In Transit", "Cancelled"],
    "In Transit": ["Delivered"],
    "Delivered": [],
    "Cancelled": []
}

@retry_on_deadlock(max_retries=3)
def create_shipment(db: Session, data):

    # Step 1: Deduct inventory (already row-locked)
    deduct_stock(
        db=db,
        warehouse_id=data.warehouse_id,
        product_id=data.product_id,
        quantity=data.quantity,
    )

    # Step 2: Lock and get available vehicle
    vehicle = get_available_vehicle_for_update(db)

    # Step 3: Assign vehicle
    vehicle.status = "Assigned"

    shipment = Shipment(
        warehouse_id=data.warehouse_id,
        product_id=data.product_id,
        quantity=data.quantity,
        status="Assigned",
        vehicle_id=vehicle.id
    )

    db.add(shipment)
    db.flush()

    return shipment


def create_shipment_atomic(db: Session, shipment_data):
    """
    Atomically:
    - Lock inventory
    - Deduct stock
    - Create shipment
    - Commit
    """

    try:
        reserve_inventory(
            db=db,
            warehouse_id=shipment_data.warehouse_id,
            product_id=shipment_data.product_id,
            quantity=shipment_data.quantity,
        )

        shipment = Shipment(
            warehouse_id=shipment_data.warehouse_id,
            product_id=shipment_data.product_id,
            vehicle_id=shipment_data.vehicle_id,
            quantity=shipment_data.quantity,
            status="CREATED",
        )

        db.add(shipment)

        db.commit()
        db.refresh(shipment)

        return shipment

    except Exception:
        db.rollback()
        raise