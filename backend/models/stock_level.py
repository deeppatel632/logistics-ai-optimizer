from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship

from database.base import Base


class StockLevel(Base):
    __tablename__ = "stock_levels"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, index=True)

    warehouse_id = Column(Integer, ForeignKey("warehouses.id"))
    item_id = Column(Integer, ForeignKey("inventory_items.id"))

    quantity = Column(Integer, default=0)

    warehouse = relationship("Warehouse")
    item = relationship("InventoryItem", back_populates="stock_levels")