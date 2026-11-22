"""Shared pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard27_api.main import app


@pytest.fixture()
def client() -> TestClient:
    """A TestClient for the FastAPI application."""
    return TestClient(app)


@pytest.fixture(scope="session")
def _server_url(request: pytest.FixtureRequest) -> Iterator[str]:
    """URL of a Postgres server: TEST_DATABASE_URL, else a throwaway pytest-postgresql server."""
    external = os.environ.get("TEST_DATABASE_URL")
    if external:
        yield external
        return
    try:
        from pytest_postgresql.janitor import DatabaseJanitor
    except ImportError:
        # pytest-postgresql is not installed yet: tests then fail on the missing behaviour.
        yield "postgresql://postgres@127.0.0.1:1/missing"
        return
    proc: Any = request.getfixturevalue("postgresql_proc")
    host, port, user = proc.host, proc.port, proc.user
    password = getattr(proc, "password", None)
    dbname = "taskboard_test"
    with DatabaseJanitor(
        user=user, host=host, port=port, dbname=dbname, version=proc.version, password=password
    ):
        auth = f"{user}:{password}" if password else user
        yield f"postgresql://{auth}@{host}:{port}/{dbname}"


@pytest.fixture(autouse=True)
def database_url(_server_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Empty database without schema for every test; DATABASE_URL points to it."""
    monkeypatch.setenv("DATABASE_URL", _server_url)
    try:
        import psycopg
    except ImportError:
        psycopg = None  # type: ignore[assignment]
    if psycopg is not None:
        conn = psycopg.connect(_server_url, autocommit=True)
        try:
            conn.execute("DROP TABLE IF EXISTS tasks")
        finally:
            conn.close()
    try:
        from taskboard27_api.tasks.store import get_task_store
    except ImportError:
        get_task_store = None  # type: ignore[assignment]
    clear = getattr(get_task_store, "cache_clear", None)
    if clear is not None:
        clear()
    yield _server_url
    app.dependency_overrides.clear()
    clear = getattr(get_task_store, "cache_clear", None)
    if clear is not None:
        clear()


@pytest.fixture()
def fill_tasks(database_url: str) -> Callable[[int], None]:
    """Insert n tasks straight into the database by SQL (creating the schema first)."""

    def _fill(n: int) -> None:
        import psycopg

        with psycopg.connect(database_url) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tasks ("
                "seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "id UUID NOT NULL UNIQUE, "
                "title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200), "
                "due_date DATE NULL)"
            )
            conn.execute(
                "INSERT INTO tasks (id, title, due_date) "
                "SELECT gen_random_uuid(), 't' || g, NULL FROM generate_series(1, %s) g",
                (n,),
            )

    return _fill


@pytest.fixture()
def count_tasks(database_url: str) -> Callable[[], int]:
    """Number of rows in the tasks table, read by SQL."""

    def _count() -> int:
        import psycopg

        with psycopg.connect(database_url) as conn:
            row = conn.execute("SELECT count(*) FROM tasks").fetchone()
        assert row is not None
        return int(row[0])

    return _count
