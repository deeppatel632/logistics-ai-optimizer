from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Float, Boolean
from datetime import datetime
from database.connection import Base
from sqlalchemy.orm import relationship
from passlib.context import CryptContext


class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String(50), nullable=False)
    status = Column(String(50), default="Available")

    current_latitude = Column(Float, nullable=False)
    current_longitude = Column(Float, nullable=False)

    shipments = relationship("Shipment", back_populates="vehicle")

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    sku = Column(String(50), unique=True, nullable=False)
    weight = Column(Float, nullable=False)

    inventories = relationship("Inventory", back_populates="product")
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True, index=True)

    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)

    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)

    quantity = Column(Integer, nullable=False)
    status = Column(String(50), default="Pending")

    warehouse = relationship("Warehouse")
    product = relationship("Product")
    vehicle = relationship("Vehicle", back_populates="shipments")

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), unique=True, nullable=False, index=True)
    response_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    capacity = Column(Integer, nullable=False)
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="viewer")  # admin, manager, viewer
    is_active = Column(Boolean, default=True)
class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    warehouse_id = Column(Integer, ForeignKey("warehouses.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)

    warehouse = relationship("Warehouse")
    product = relationship("Product", back_populates="inventories")

# class Vehicle(Base):
#     __tablename__ = "vehicles"

#     id = Column(Integer, primary_key=True, index=True)
#     type = Column(String(50), nullable=False)
#     status = Column(String(50), default="Available")
#     current_latitude = Column(Float, nullable=False)
#     current_longitude = Column(Float, nullable=False)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(100), nullable=False)

    entity_type = Column(String(100), nullable=False)  # e.g. Shipment
    entity_id = Column(Integer, nullable=False)

    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)