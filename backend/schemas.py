from pydantic import BaseModel, Field
from datetime import datetime


class ShipmentStatusUpdate(BaseModel):
    new_status: str

class WarehouseCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    latitude: float
    longitude: float
    capacity: int = Field(..., gt=0)

class WarehouseResponse(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    capacity: int

    class Config:
        orm_mode = True
class ShipmentCreate(BaseModel):
    warehouse_id: int
    product_id: int
    quantity: int = Field(..., gt=0)

class ShipmentResponse(BaseModel):
    id: int
    warehouse_id: int
    product_id: int
    quantity: int
    status: str

    class Config:
        orm_mode = True

class AuditLogResponse(BaseModel):
    id: int
    user_id: int
    action: str
    entity_type: str
    entity_id: int
    old_value: str | None
    new_value: str | None
    created_at: datetime

    model_config = {
        "from_attributes": True
    }