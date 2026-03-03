from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session
from database.connection import SessionLocal, engine
from database.connection import Base

app = FastAPI(title="Global Logistics Optimizer API")


# ---------------------------
# Database Dependency
# ---------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------
# Startup Event
# ---------------------------
@app.on_event("startup")
def startup_event():
    # Ensure tables exist (dev only)
    Base.metadata.create_all(bind=engine)


# ---------------------------
# Test Route
# ---------------------------
@app.get("/health")
def health_check():
    return {"status": "API running"}