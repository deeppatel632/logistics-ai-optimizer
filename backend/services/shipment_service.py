from sqlalchemy.orm import Session
from fastapi import HTTPException
from database.models import IdempotencyKey, Shipment
from backend.services.inventory_service import reserve_inventory
from backend.core.db_retry import retry_on_deadlock
from backend.core.logger import logger
import json
from backend.services.audit_service import log_action

# ---------------------------------------------------
# Shipment State Machine (Single Source of Truth)
# ---------------------------------------------------

ALLOWED_TRANSITIONS = {
    "CREATED": ["IN_TRANSIT", "CANCELLED"],
    "IN_TRANSIT": ["DELIVERED", "CANCELLED"],
    "DELIVERED": [],
    "CANCELLED": [],
}


# ---------------------------------------------------
# Create Shipment (Idempotent + Atomic)
# ---------------------------------------------------

@retry_on_deadlock(max_retries=3)
def create_shipment_atomic(db: Session, shipment_data, idem_key: str):
    """
    Creates shipment with:
    - Idempotency protection
    - Inventory reservation
    - Atomic transaction
    """

    # 1️⃣ Check idempotency key
    existing = db.query(IdempotencyKey).filter(
        IdempotencyKey.key == idem_key
    ).first()

    if existing:
        logger.info(f"Duplicate idempotency key detected: {idem_key}")
        return json.loads(existing.response_payload)

    logger.info(
        f"Creating shipment | warehouse={shipment_data.warehouse_id} "
        f"| product={shipment_data.product_id} "
        f"| quantity={shipment_data.quantity}"
    )

    try:
        # 2️⃣ Reserve inventory (row-level locked inside service)
        reserve_inventory(
            db,
            shipment_data.warehouse_id,
            shipment_data.product_id,
            shipment_data.quantity,
        )

        # 3️⃣ Create shipment
        shipment = Shipment(
            warehouse_id=shipment_data.warehouse_id,
            product_id=shipment_data.product_id,
            vehicle_id=shipment_data.vehicle_id,
            quantity=shipment_data.quantity,
            status="CREATED",
        )

        db.add(shipment)
        db.flush()  # generate shipment.id without committing

        response_data = {
            "id": shipment.id,
            "status": shipment.status,
        }

        # 4️⃣ Store idempotency key record
        db.add(
            IdempotencyKey(
                key=idem_key,
                response_payload=json.dumps(response_data),
            )
        )

        db.commit()
        db.refresh(shipment)

        logger.info(f"Shipment {shipment.id} created successfully")

        return response_data

    except Exception as e:
        db.rollback()
        logger.error(f"Shipment creation failed: {str(e)}")
        raise


# ---------------------------------------------------
# Update Shipment Status (State Machine Enforced)
# ---------------------------------------------------
def update_shipment_status(db: Session, shipment_id: int, new_status: str, user):

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

    old_data = {"status": shipment.status}

    shipment.status = new_status

    new_data = {"status": shipment.status}

    log_action(
        db=db,
        user_id=user.id,
        action="UPDATE_STATUS",
        entity_type="Shipment",
        entity_id=shipment.id,
        old_value=old_data,
        new_value=new_data,
    )

    db.commit()
    db.refresh(shipment)

    return shipment