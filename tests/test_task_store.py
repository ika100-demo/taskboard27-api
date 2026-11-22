import socket

import pytest

from taskboard27_api.tasks import MAX_TASKS, StorageUnavailable, TaskLimitReached, TaskStore


def _closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"postgresql://u@127.0.0.1:{port}/db"


def test_fresh_store_is_empty(database_url: str) -> None:
    assert TaskStore(database_url).list() == []


def test_default_capacity() -> None:
    assert MAX_TASKS == 1000


def test_list_oldest_first(database_url: str) -> None:
    store = TaskStore(database_url)
    a = store.add("a", None)
    b = store.add("b", "2030-01-02")
    assert store.list() == [a, b]
    assert b.due_date == "2030-01-02"


def test_second_store_sees_tasks(database_url: str) -> None:
    a = TaskStore(database_url).add("a", None)
    assert TaskStore(database_url).list() == [a]


def test_limit_refuses_extra_task(database_url: str) -> None:
    store = TaskStore(database_url, max_tasks=3)
    for i in range(3):
        store.add(str(i), None)
    with pytest.raises(TaskLimitReached):
        store.add("extra", None)
    assert len(store.list()) == 3


def test_ids_unique(database_url: str) -> None:
    store = TaskStore(database_url)
    ids = {store.add("t", None).id for _ in range(20)}
    assert len(ids) == 20


def test_ensure_schema_idempotent(database_url: str) -> None:
    store = TaskStore(database_url)
    store.ensure_schema()
    a = store.add("a", None)
    store.ensure_schema()
    assert store.list() == [a]


def test_closed_port_is_unavailable() -> None:
    store = TaskStore(_closed_port_url())
    with pytest.raises(StorageUnavailable):
        store.list()
    with pytest.raises(StorageUnavailable):
        store.add("a", None)
    with pytest.raises(StorageUnavailable):
        store.ping()


def test_unset_url_is_unavailable() -> None:
    with pytest.raises(StorageUnavailable):
        TaskStore(None).list()
