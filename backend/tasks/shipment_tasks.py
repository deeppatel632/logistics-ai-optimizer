import time
from database.connection import SessionLocal
from database.models import Shipment


def process_shipment_dispatch(shipment_id: int):
    """
    Background dispatch processor.
    Runs outside request lifecycle.
    """

    db = SessionLocal()

    try:
        shipment = db.query(Shipment).filter(
            Shipment.id == shipment_id
        ).first()

        if not shipment:
            print("Shipment not found.")
            return

        print(f"Dispatching shipment {shipment_id}")

        # Simulate heavy processing
        time.sleep(5)

        shipment.status = "IN_TRANSIT"
        db.commit()

        print(f"Shipment {shipment_id} is now IN_TRANSIT")

    except Exception as e:
        db.rollback()
        print(f"Error processing shipment: {e}")

    finally:
        db.close()