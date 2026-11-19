"""
SQLAlchemy engine/session setup.

Defaults to a local SQLite file for zero-setup development. For production,
set DATABASE_URL in .env to a real Postgres connection string, e.g.:

    DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/sih_dwta

SQLite is fine for a hackathon demo/single-analyst use; a multi-analyst
production deployment should move to Postgres for proper concurrent-write
support.
"""

import os

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

from src.utils.config import get_app_data_dir

DEFAULT_SQLITE_PATH = get_app_data_dir() / "app.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session and ensures it's closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Call once at startup or via scripts/init_db.py."""
    from src.db import models  # noqa: F401 (ensures models are registered)
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations():
    """
    Adds columns introduced after a table already existed, for databases
    created by an earlier version of this app — specifically, `users.email`
    (added when email-based login/password-reset/OTP were introduced).
    `Base.metadata.create_all()` only creates missing *tables*, it never
    alters an existing one, so without this, upgrading and starting the
    app against an old app.db would crash the moment any code touched
    `User.email`.

    This is NOT a real migration system — Alembic is already a dependency
    for that, and a Postgres production deployment should use it properly.
    This is deliberately narrow, SQLite-only insurance so early-stage/local
    development databases don't hard-crash on upgrade.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return  # fresh DB — create_all() above already built it correctly

    existing_columns = {c["name"] for c in inspector.get_columns("users")}
    with engine.begin() as conn:
        if "email" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
        if "oauth_provider" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN oauth_provider VARCHAR(32)"))
        if "oauth_subject" not in existing_columns:
            conn.execute(text("ALTER TABLE users ADD COLUMN oauth_subject VARCHAR(255)"))
