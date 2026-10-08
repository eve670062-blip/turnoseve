from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_URL = f"sqlite:///{(BACKEND_DIR / 'turnoseve.db').as_posix()}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if IS_SQLITE else {},
    pool_pre_ping=True,
)

if IS_SQLITE:
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


class Base(DeclarativeBase):
    pass


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def write_session() -> Iterator[Session]:
    """Open a serialized write transaction, including on SQLite deployments."""
    connection = engine.connect()
    if IS_SQLITE:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
        session.flush()
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        session.close()
        connection.close()
