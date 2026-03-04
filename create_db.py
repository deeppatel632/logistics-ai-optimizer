from sqlalchemy import create_engine, text
from backend.core.config import get_settings

settings = get_settings()

master_connection_string = (
    f"mssql+pyodbc://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_server}:{settings.db_port}/master"
    f"?driver={settings.db_driver.replace(' ', '+')}"
    "&TrustServerCertificate=yes"
)

engine = create_engine(master_connection_string)

with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
    connection.execute(
        text(f"IF DB_ID('{settings.db_name}') IS NULL CREATE DATABASE {settings.db_name}")
    )
    print("Database ensured successfully.")

engine.dispose()