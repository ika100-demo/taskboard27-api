"""Postgres-backed task store (one short-lived connection per operation)."""

import datetime
import functools
import os
import uuid
from dataclasses import dataclass
from typing import Final

import psycopg
import structlog

MAX_TASKS: Final = 1000
CONNECT_TIMEOUT_S: Final = 3
STATEMENT_TIMEOUT_MS: Final = 3000

SCHEMA_LOCK: Final = 7_002_001
INSERT_LOCK: Final = 7_002_002

_SCHEMA_SQL: Final = """
CREATE TABLE IF NOT EXISTS tasks (
    seq      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       UUID NOT NULL UNIQUE,
    title    TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date DATE NULL
)
"""

log = structlog.get_logger()


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: str | None  # "YYYY-MM-DD" or None


class TaskLimitReached(Exception):  # noqa: N818 - name fixed by design.md
    """Raised when the store already holds its maximum number of tasks."""


class StorageUnavailable(Exception):  # noqa: N818 - name fixed by design.md
    """Raised when the database cannot be reached or does not answer in time."""


class TaskStore:
    def __init__(self, database_url: str | None, max_tasks: int = MAX_TASKS) -> None:
        self._database_url = database_url
        self._max_tasks = max_tasks
        self._schema_ready = False

    def _connect(self) -> psycopg.Connection[tuple[object, ...]]:
        if not self._database_url:
            raise psycopg.OperationalError("database url not set")
        return psycopg.connect(
            self._database_url,
            connect_timeout=CONNECT_TIMEOUT_S,
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
            tcp_user_timeout=STATEMENT_TIMEOUT_MS,
            autocommit=False,
        )

    def ensure_schema(self) -> None:
        try:
            conn = self._connect()
            try:
                with conn.transaction():
                    conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK,))
                    conn.execute(_SCHEMA_SQL)
            finally:
                conn.close()
        except psycopg.Error as exc:
            log.error("schema_setup_failed", error=type(exc).__name__)
            raise StorageUnavailable from exc
        if not self._schema_ready:
            self._schema_ready = True
            log.info("schema_ready")

    def _lazy_schema(self) -> None:
        if not self._schema_ready:
            self.ensure_schema()

    def _unavailable(self, operation: str, exc: Exception) -> StorageUnavailable:
        log.warning("task_storage_unavailable", operation=operation, error=type(exc).__name__)
        return StorageUnavailable()

    def add(self, title: str, due_date: str | None) -> Task:
        self._lazy_schema()
        task_id = str(uuid.uuid4())
        due = datetime.date.fromisoformat(due_date) if due_date else None
        try:
            conn = self._connect()
            try:
                with conn.transaction():
                    conn.execute("SELECT pg_advisory_xact_lock(%s)", (INSERT_LOCK,))
                    cur = conn.execute(
                        "INSERT INTO tasks (id, title, due_date) SELECT %s, %s, %s "
                        "WHERE (SELECT count(*) FROM tasks) < %s RETURNING seq",
                        (task_id, title, due, self._max_tasks),
                    )
                    row = cur.fetchone()
            finally:
                conn.close()
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise self._unavailable("add", exc) from exc
        if row is None:
            raise TaskLimitReached
        log.info("task_created", task_id=task_id)
        return Task(id=task_id, title=title, due_date=due_date)

    def list(self) -> list[Task]:
        self._lazy_schema()
        try:
            conn = self._connect()
            try:
                with conn.transaction():
                    rows = conn.execute(
                        "SELECT id, title, due_date FROM tasks ORDER BY seq"
                    ).fetchall()
            finally:
                conn.close()
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise self._unavailable("list", exc) from exc
        return [
            Task(
                str(r[0]),
                str(r[1]),
                r[2].isoformat() if isinstance(r[2], datetime.date) else None,
            )
            for r in rows
        ]

    def ping(self) -> None:
        try:
            conn = self._connect()
            try:
                conn.execute("SELECT 1")
            finally:
                conn.close()
        except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
            raise self._unavailable("ping", exc) from exc


@functools.cache
def get_task_store() -> TaskStore:
    return TaskStore(os.environ.get("DATABASE_URL"))
