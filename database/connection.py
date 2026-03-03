# database/connection.py

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.exc import OperationalError
import logging
import time
from database.connection import SessionLocal
from sqlalchemy import event
from sqlalchemy.orm import with_loader_criteria
from backend.core.tenant_context import get_current_tenant
from database.models import Warehouse, Shipment, Product, Vehicle, Inventory
from backend.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

Base = declarative_base()


# -------------------------------
# CONNECTION STRING BUILDER
# -------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def build_connection_string(database_name: str) -> str:
    return (
        f"mssql+pyodbc://{settings.db_user}:{settings.db_password}"
        f"@{settings.db_server}:{settings.db_port}/{database_name}"
        f"?driver={settings.db_driver.replace(' ', '+')}"
        "&TrustServerCertificate=yes"
    )


# -------------------------------
# ENGINE FACTORY
# -------------------------------

def create_engine_with_pool(database_name: str):
    return create_engine(
        build_connection_string(database_name),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
        echo=False,
        future=True,
    )


# -------------------------------
# DATABASE PROVISIONING
# -------------------------------

def ensure_database_exists():
    master_engine = create_engine_with_pool("master")

    try:
        with master_engine.connect() as connection:
            result = connection.execute(
                text("SELECT name FROM sys.databases WHERE name = :db_name"),
                {"db_name": settings.db_name},
            )

            if not result.fetchone():
                connection.execute(
                    text(f"CREATE DATABASE {settings.db_name}")
                )
                logger.info(f"Database {settings.db_name} created.")
            else:
                logger.info(f"Database {settings.db_name} already exists.")

    finally:
        master_engine.dispose()


# -------------------------------
# CONNECTION VALIDATION
# -------------------------------

def validate_database_connection(engine, retries=5, delay=3):
    for attempt in range(retries):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("Database connection validated successfully.")
            return
        except OperationalError:
            logger.warning(
                f"DB connection failed (attempt {attempt + 1}/{retries}). Retrying..."
            )
            time.sleep(delay)

    raise RuntimeError("Database not available after retries.")

@event.listens_for(SessionLocal, "do_orm_execute")
def _add_tenant_criteria(execute_state):

    if not execute_state.is_select:
        return

    tenant_id = get_current_tenant()

    if not tenant_id:
        return

    for model in [Warehouse, Shipment, Product, Vehicle, Inventory]:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                model,
                lambda cls: (cls.tenant_id == tenant_id) & (cls.is_deleted == False),
                include_aliases=True,
            )
        )


# -------------------------------
# INITIALIZATION ORDER
# -------------------------------



engine = create_engine_with_pool(settings.db_name)



SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)