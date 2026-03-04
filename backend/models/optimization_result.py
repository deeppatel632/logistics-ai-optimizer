from sqlalchemy import Column, Integer, Float, DateTime
from datetime import datetime

from database.base import Base


class OptimizationResult(Base):
    __tablename__ = "optimization_results"

    id = Column(Integer, primary_key=True)

    tenant_id = Column(Integer, index=True)

    total_distance = Column(Float)

    total_cost = Column(Float)

    computed_at = Column(DateTime, default=datetime.utcnow)