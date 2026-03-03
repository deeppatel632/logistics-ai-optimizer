from pydantic import BaseModel, Field

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