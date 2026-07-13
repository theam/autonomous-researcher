"""Database lifecycle and backend-specific safety configuration."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DEFAULT_DATABASE_PATH = Path(".limina/runtime.db")


def default_database_url() -> str:
    configured = os.environ.get("LIMINA_DATABASE_URL")
    if configured:
        return configured
    return f"sqlite:///{DEFAULT_DATABASE_PATH}"


def create_runtime_engine(database_url: str | None = None) -> Engine:
    url = database_url or default_database_url()
    if url.startswith("sqlite:///"):
        path_text = url.removeprefix("sqlite:///")
        if path_text and path_text != ":memory:":
            Path(path_text).expanduser().parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        url,
        future=True,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False, "timeout": 30}
        if url.startswith("sqlite")
        else {},
    )
    if engine.dialect.name == "sqlite":
        _configure_sqlite(engine)
    return engine


def _configure_sqlite(engine: Engine) -> None:
    # Python 3.12 deprecated sqlite3's implicit datetime adapter. Registering
    # the representation keeps round-trips explicit and warning-free.
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


class Database:
    def __init__(self, database_url: str | None = None) -> None:
        self.engine = create_runtime_engine(database_url)
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def initialize(self) -> None:
        if self.engine.dialect.name == "sqlite":
            Base.metadata.create_all(self.engine)
            return
        if not inspect(self.engine).has_table("alembic_version"):
            raise RuntimeError(
                "The shared database is not migrated. Run `limina --database <url> db upgrade`."
            )

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self._sessions()
        try:
            yield session
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()
