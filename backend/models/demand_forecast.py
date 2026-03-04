from sqlalchemy import Column, Integer, Float, ForeignKey, DateTime
from datetime import datetime

from database.base import Base


class DemandForecast(Base):
    __tablename__ = "demand_forecasts"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, index=True)

    item_id = Column(Integer, ForeignKey("inventory_items.id"))

    predicted_demand = Column(Float)

    forecast_date = Column(DateTime, default=datetime.utcnow)