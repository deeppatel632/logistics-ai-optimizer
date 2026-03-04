from sqlalchemy import Column, Integer, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

from database.base import Base


class Shipment(Base):
    __tablename__ = "shipments"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, index=True)

    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))

    destination_lat = Column(Float)
    destination_lon = Column(Float)

    status = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    warehouse = relationship("Warehouse", back_populates="shipments")