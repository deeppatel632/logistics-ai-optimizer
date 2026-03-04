from sqlalchemy import Column, Integer, Float, ForeignKey
from database.base import Base


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, index=True)

    shipment_id = Column(Integer, ForeignKey("shipments.id"))

    distance_km = Column(Float)

    estimated_time = Column(Float)