# database/connection.py

import logging
import time
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker, with_loader_criteria
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

from backend.core.config import get_settings
from backend.core.tenant_context import get_current_tenant
from backend.core.circuit_breaker import db_breaker

settings = get_settings()
logger = logging.getLogger(__name__)

Base = declarative_base()

primary_engine = create_engine(settings.primary_db_url, future=True)
replica_engine = create_engine(settings.replica_db_url, future=True)


# Write session (Primary DB)
PrimarySessionLocal = sessionmaker(
    bind=primary_engine,
    autocommit=False,
    autoflush=False,
)

# Read session (Replica DB)
ReplicaSessionLocal = sessionmaker(
    bind=replica_engine,
    autocommit=False,
    autoflush=False,
)
# -------------------------------
# CONNECTION STRING BUILDER
# -------------------------------

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


# -------------------------------
# DB HEALTH CHECK
# -------------------------------

@db_breaker
def safe_db_check() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


# -------------------------------
# ENGINE + SESSION FACTORY
# -------------------------------

engine = create_engine_with_pool(settings.db_name)

SQLAlchemyInstrumentor().instrument(engine=engine)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# -------------------------------
# SESSION DEPENDENCY
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


# -------------------------------
# TENANT ENFORCEMENT HOOKS
# -------------------------------

@event.listens_for(SessionLocal, "after_begin")
def _set_tenant_session_context(
    session, transaction, connection
) -> None:
    tenant_id = get_current_tenant()
    if tenant_id is not None:
        connection.exec_driver_sql(
            "EXEC sp_set_session_context @key=N'tenant_id', @value=?",
            (tenant_id,),
        )


@event.listens_for(SessionLocal, "do_orm_execute")
def _add_tenant_filter_criteria(execute_state) -> None:
    if not execute_state.is_select:
        return

    tenant_id = get_current_tenant()
    if tenant_id is None:
        return

    from database.models import Inventory, Product, Shipment, Vehicle, Warehouse

    for model in (Warehouse, Shipment, Product, Vehicle, Inventory):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                model,
                lambda cls, tid=tenant_id: (
                    (cls.tenant_id == tid) & (cls.is_deleted == False)
                ),
                include_aliases=True,
            )
        )


def get_write_db():
    db = PrimarySessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_read_db():
    db = ReplicaSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()