from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from database.models import Vehicle
from fastapi import HTTPException


def get_available_vehicle_for_update(db: Session):
    """
    Selects one available vehicle and locks it using FOR UPDATE.
    This prevents concurrent assignment.
    """

    stmt = (
        select(Vehicle)
        .where(Vehicle.status == "Available")
        .with_for_update(skip_locked=True)
        .limit(1)
    )

    result = db.execute(stmt).scalars().first()

    if not result:
        raise HTTPException(status_code=400, detail="No available vehicles")

    return result