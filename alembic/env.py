# =============================================================================
# alembic/env.py — Production-ready Alembic environment for FastAPI +
# SQLAlchemy on Azure SQL Edge / SQL Server, running inside Docker.
#
# Design choices:
#   • URL is always built from pydantic Settings (no hardcoded credentials,
#     no sqlalchemy.url in alembic.ini — that key is left blank intentionally).
#   • primary_engine is imported and reused for online migrations so the pool
#     settings configured in database/connection.py are respected.
#   • NullPool is NOT forced here because primary_engine already owns the pool;
#     forcing NullPool would create a second, poolless engine for every alembic
#     run, which is wasteful.  If you run alembic from a one-shot container
#     (e.g. k8s Job) add `poolclass=NullPool` to the engine kwargs below.
#   • compare_type=True lets autogenerate detect column type changes.
#   • include_object() filters out SQL Server system objects (##, spt_, etc.)
#     that appear in INFORMATION_SCHEMA but should never be managed by Alembic.
# =============================================================================

# ---------------------------------------------------------------------------
# sys.path manipulation MUST be the very first thing so that all subsequent
# local imports (database/*, backend/*) can be resolved when alembic is run
# from any working directory (e.g. `alembic -c alembic.ini upgrade head`).
# ---------------------------------------------------------------------------
import os
import sys

# Insert the project root (one level above this file's parent) so that
# `import database.connection` and `import backend.core.config` both resolve.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# ---------------------------------------------------------------------------
# Standard library / third-party imports
# ---------------------------------------------------------------------------
from logging.config import fileConfig  # noqa: E402
from typing import Optional  # noqa: E402

from alembic import context  # noqa: E402

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------
# Load the pydantic settings object.  All values come from environment
# variables (or .env / .env.prod) — never from alembic.ini.
from backend.core.config import get_settings  # noqa: E402

# Import the *shared* primary engine so Alembic reuses the same connection
# pool that the FastAPI application uses.  This engine is already configured
# with pool_size, pool_recycle, pool_pre_ping, etc.
from database.connection import primary_engine  # noqa: E402

# Import Base.metadata — this is the single source of truth for all table
# definitions.  Every SQLAlchemy model must be imported (even if unused
# directly here) so that its table metadata is registered on Base.metadata
# before autogenerate compares against the live database schema.
from database.connection import Base  # noqa: E402, F401 — registers Base
import database.models  # noqa: E402, F401 — registers all ORM models on Base.metadata

# =============================================================================
# Alembic configuration object
# Provides access to values in alembic.ini (logging config, script location).
# =============================================================================
config = context.config

# ---------------------------------------------------------------------------
# Wire up Python's standard logging from the [loggers] section of alembic.ini.
# Skip when there is no .ini file (e.g. when env.py is imported in unit tests).
# ---------------------------------------------------------------------------
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---------------------------------------------------------------------------
# Override sqlalchemy.url at runtime from pydantic Settings.
#
# WHY: Keeping the URL out of alembic.ini avoids committing credentials to
# version control.  The alembic.ini key is intentionally left blank
# (`sqlalchemy.url = `).  All values are sourced from environment variables
# (loaded by pydantic-settings from .env or the process environment).
#
# The URL is built to match the pyodbc connection string format required by
# SQL Server / Azure SQL Edge:
#   mssql+pyodbc://<user>:<pass>@<host>:<port>/<db>?driver=...&TrustServerCertificate=yes
# ---------------------------------------------------------------------------
settings = get_settings()

_migration_url = (
    f"mssql+pyodbc://{settings.db_user}:{settings.db_password}"
    f"@{settings.db_server}:{settings.db_port}/{settings.db_name}"
    f"?driver={settings.db_driver.replace(' ', '+')}"
    "&TrustServerCertificate=yes"
)

# Inject the URL into the alembic config — used by offline mode and visible
# in `alembic current` / `alembic history` output.
config.set_main_option("sqlalchemy.url", _migration_url)

# ---------------------------------------------------------------------------
# target_metadata: passed to context.configure() so autogenerate can diff
# the ORM-declared schema against the live database.
# ---------------------------------------------------------------------------
target_metadata = Base.metadata


# =============================================================================
# include_object — autogenerate filter
#
# SQL Server / Azure SQL Edge exposes internal/system tables through
# INFORMATION_SCHEMA that Alembic would otherwise try to manage.
# This filter restricts autogenerate to tables that are explicitly declared
# in Base.metadata (i.e. your ORM models).
# =============================================================================
def include_object(
    obj,
    name: Optional[str],
    type_: str,
    reflected: bool,
    compare_to,
) -> bool:
    """Return True if Alembic should include this object in autogenerate output.

    Rules:
    - Tables that exist only in the database (reflected=True) and have no
      corresponding ORM model are silently excluded.  This prevents Alembic
      from generating spurious `drop_table` operations for SQL Server system
      tables, temporal history tables, or tables owned by other applications.
    - Everything else (indexes, constraints, sequences attached to known
      tables) is included normally.
    """
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    return True


# =============================================================================
# OFFLINE MODE
# `alembic upgrade head --sql`  →  outputs raw SQL to stdout.
# No live database connection is required.
# Useful for: generating a SQL script to review before applying, or running
# migrations in environments where pyodbc is not available.
# =============================================================================
def run_migrations_offline() -> None:
    """Configure Alembic context with the URL only (no engine / DBAPI).

    SQL statements are written to the script output rather than executed.
    The URL is already set on `config` via set_main_option() above.
    """
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        # render_as_batch=False: SQL Server supports ALTER TABLE natively;
        # batch mode is only needed for SQLite's limited ALTER support.
        render_as_batch=False,
        # compare_type detects column type changes (e.g. String(50) → String(100)).
        compare_type=True,
        # compare_server_default detects changes to DEFAULT constraints.
        compare_server_default=True,
        include_object=include_object,
        # SQL Server uses named parameters (:param) — not positional (?).
        dialect_opts={"paramstyle": "named"},
        # literal_binds renders bind parameters as inline literals in the
        # generated SQL.  This is safe for offline DDL statements.
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# =============================================================================
# ONLINE MODE
# `alembic upgrade head`  →  executes migrations against a live database.
# Uses the shared primary_engine so the pool is not duplicated.
# =============================================================================
def run_migrations_online() -> None:
    """Open a real database connection and run migrations transactionally.

    Using the shared primary_engine means:
    - Pool settings (pool_size, pool_recycle, pool_pre_ping) are respected.
    - SQLAlchemyInstrumentor tracing spans are emitted for migration DDL.

    If you want a fully isolated, one-shot connection (e.g. in a k8s init
    container) replace `primary_engine` with:
        from sqlalchemy import pool
        create_engine(_migration_url, poolclass=pool.NullPool)
    """
    with primary_engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Do NOT use batch mode for SQL Server (see offline note above).
            render_as_batch=False,
            # Detect column type and server-default drift during autogenerate.
            compare_type=True,
            compare_server_default=True,
            # Exclude SQL Server system / non-ORM tables from autogenerate diffs.
            include_object=include_object,
            # transaction_per_migration=True means each migration script runs
            # in its own transaction.  If one script fails, only that script
            # is rolled back, not the entire upgrade run.
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# =============================================================================
# Entry point — Alembic calls env.py as a script; this block dispatches to
# the appropriate migration mode based on the command-line flag.
# =============================================================================
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
