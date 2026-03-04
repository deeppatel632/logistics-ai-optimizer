# tests/test_ml.py
#
# Pydantic schema validation tests.
# These are pure in-memory checks — no database, Redis, or ML runtime needed.

import pytest
from pydantic import ValidationError

from backend.schemas import (
    ShipmentCreate,
    ShipmentStatusUpdate,
    WarehouseCreate,
)


# ---------------------------------------------------------------------------
# WarehouseCreate
# ---------------------------------------------------------------------------

class TestWarehouseCreateSchema:
    def test_valid_warehouse(self):
        data = {"name": "HQ Warehouse", "latitude": 51.5, "longitude": -0.1, "capacity": 500}
        wh = WarehouseCreate(**data)
        assert wh.name == "HQ Warehouse"
        assert wh.capacity == 500

    def test_name_too_short_raises(self):
        with pytest.raises(ValidationError):
            WarehouseCreate(name="X", latitude=0.0, longitude=0.0, capacity=10)

    def test_name_too_long_raises(self):
        with pytest.raises(ValidationError):
            WarehouseCreate(name="A" * 101, latitude=0.0, longitude=0.0, capacity=10)

    def test_zero_capacity_raises(self):
        """capacity must be > 0."""
        with pytest.raises(ValidationError):
            WarehouseCreate(name="Valid Name", latitude=0.0, longitude=0.0, capacity=0)

    def test_negative_capacity_raises(self):
        with pytest.raises(ValidationError):
            WarehouseCreate(name="Valid Name", latitude=0.0, longitude=0.0, capacity=-1)

    def test_latitude_and_longitude_store_correctly(self):
        wh = WarehouseCreate(name="Test WH", latitude=40.7128, longitude=-74.006, capacity=100)
        assert wh.latitude == pytest.approx(40.7128)
        assert wh.longitude == pytest.approx(-74.006)


# ---------------------------------------------------------------------------
# ShipmentCreate
# ---------------------------------------------------------------------------

class TestShipmentCreateSchema:
    def test_valid_shipment(self):
        s = ShipmentCreate(warehouse_id=1, product_id=2, quantity=10)
        assert s.warehouse_id == 1
        assert s.quantity == 10

    def test_zero_quantity_raises(self):
        """quantity must be > 0."""
        with pytest.raises(ValidationError):
            ShipmentCreate(warehouse_id=1, product_id=1, quantity=0)

    def test_negative_quantity_raises(self):
        with pytest.raises(ValidationError):
            ShipmentCreate(warehouse_id=1, product_id=1, quantity=-5)

    def test_missing_warehouse_id_raises(self):
        with pytest.raises(ValidationError):
            ShipmentCreate(product_id=1, quantity=10)


# ---------------------------------------------------------------------------
# ShipmentStatusUpdate
# ---------------------------------------------------------------------------

class TestShipmentStatusUpdateSchema:
    def test_valid_status(self):
        update = ShipmentStatusUpdate(new_status="in_transit")
        assert update.new_status == "in_transit"

    def test_empty_status_is_accepted_by_model(self):
        """No length constraint on new_status — empty string is valid input."""
        update = ShipmentStatusUpdate(new_status="")
        assert update.new_status == ""

    def test_missing_new_status_raises(self):
        with pytest.raises(ValidationError):
            ShipmentStatusUpdate()
