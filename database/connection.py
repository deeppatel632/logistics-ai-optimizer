# database/connection.py

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from backend.core.config import get_settings

settings = get_settings()

connection_string = (
    f"mssql+pyodbc://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_server}:{settings.db_port}/{settings.db_name}"
    f"?driver={settings.db_driver.replace(' ', '+')}"
    "&TrustServerCertificate=yes"
)

engine = create_engine(
    connection_string,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    echo=False,  # True only for debugging
    future=True
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()