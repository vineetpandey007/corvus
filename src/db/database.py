"""
SQLAlchemy engine/session setup with SQLite WAL concurrency tuning,
foreign-key enforcement, and Postgres connection health checks.
"""

import os

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from src.utils.config import get_app_data_dir

DEFAULT_SQLITE_PATH = get_app_data_dir() / "app.db"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_SQLITE_PATH}")

is_sqlite = DATABASE_URL.startswith("sqlite")
connect_args = {"check_same_thread": False, "timeout": 15} if is_sqlite else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=10000;")
        cursor.close()

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
    """Create all tables and apply safe additive column upgrades."""
    from src.db import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


def _run_lightweight_migrations():
    """
    Additive column upgrades for local SQLite databases created by earlier
    versions of the app. Production Postgres deployments should use Alembic.
    """
    if not is_sqlite:
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        if "users" in tables:
            user_cols = {c["name"] for c in inspector.get_columns("users")}
            if "email" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR(255)"))
            if "oauth_provider" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN oauth_provider VARCHAR(32)"))
            if "oauth_subject" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN oauth_subject VARCHAR(255)"))

        if "case_posts" in tables:
            post_cols = {c["name"] for c in inspector.get_columns("case_posts")}
            if "evidence_sha256" not in post_cols:
                conn.execute(text("ALTER TABLE case_posts ADD COLUMN evidence_sha256 VARCHAR(64)"))