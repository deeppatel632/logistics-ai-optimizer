from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from database.connection import SessionLocal, engine
from database.connection import Base
from sqlalchemy import text
from database.connection import engine, validate_database_connection
from database.connection import get_db
from backend.api import warehouse_routes




app = FastAPI(title="Global Logistics Optimizer API")

app.include_router(warehouse_routes.router)

# ---------------------------
# Database Dependency
# ---------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health/db")
def db_health(db: Session = Depends(get_db)):
    return {"db": "connected"}


# ---------------------------
# Startup Event
# ---------------------------

@app.on_event("startup")
def startup_event():
    validate_database_connection(engine)
    Base.metadata.create_all(bind=engine)
# ---------------------------
# Test Route
# ---------------------------
@app.get("/health")
def health_check():
    return {"status": "API running"}


@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except:
        return {"status": "unhealthy"}