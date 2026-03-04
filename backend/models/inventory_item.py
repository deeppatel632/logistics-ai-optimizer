from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

from database.base import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, index=True)

    sku = Column(String(100), unique=True)
    name = Column(String(255))

    description = Column(String(500))

    stock_levels = relationship("StockLevel", back_populates="item")