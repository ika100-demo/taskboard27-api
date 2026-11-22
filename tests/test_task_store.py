import pytest

from taskboard27_api.tasks import MAX_TASKS, TaskLimitReached, TaskStore


def test_fresh_store_is_empty() -> None:
    store = TaskStore()
    assert store.list() == []
    assert len(store) == 0


def test_default_capacity() -> None:
    assert MAX_TASKS == 1000


def test_list_oldest_first() -> None:
    store = TaskStore()
    a = store.add("a", None)
    b = store.add("b", "2030-01-02")
    assert store.list() == [a, b]
    assert b.due_date == "2030-01-02"


def test_list_returns_copy() -> None:
    store = TaskStore()
    store.add("a", None)
    store.list().clear()
    assert len(store) == 1


def test_limit_refuses_extra_task() -> None:
    store = TaskStore(max_tasks=3)
    for i in range(3):
        store.add(str(i), None)
    with pytest.raises(TaskLimitReached):
        store.add("extra", None)
    assert len(store) == 3


def test_ids_unique() -> None:
    store = TaskStore()
    ids = {store.add("t", None).id for _ in range(50)}
    assert len(ids) == 50
