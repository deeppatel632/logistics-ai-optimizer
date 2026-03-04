from sqlalchemy import Column, Integer, String, Float
from sqlalchemy.orm import relationship

from database.base import Base


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, index=True)

    name = Column(String(255), nullable=False)

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)

    city = Column(String(100))
    country = Column(String(100))

    shipments = relationship("Shipment", back_populates="warehouse")