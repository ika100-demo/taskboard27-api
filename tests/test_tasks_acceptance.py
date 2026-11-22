"""Acceptance tests for spec 001: create and list tasks in memory."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard27_api.main import app


def _store_module() -> Any:
    try:
        from taskboard27_api.tasks import store
    except ImportError:
        pytest.fail("taskboard27_api.tasks.store is missing")
    return store


def _install_store(store: Any) -> None:
    mod = _store_module()
    app.dependency_overrides[mod.get_task_store] = lambda: store


@pytest.fixture(autouse=True)
def fresh_store(database_url: str) -> Iterator[None]:
    try:
        from taskboard27_api.tasks import store as mod
    except ImportError:
        yield  # tests fail on the missing endpoint / module
        return
    _install_store(mod.TaskStore(database_url))
    yield
    app.dependency_overrides.clear()


def _post(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post("/tasks", json=body)


def _listed(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/tasks")
    assert response.status_code == 200
    return response.json()


def _locs(response: Any) -> list[Any]:
    return [e["loc"][-1] for e in response.json()["detail"]]


def test_create_task_returns_201_with_fields(client: TestClient) -> None:  # AC-001.1
    response = _post(client, {"title": "Buy milk", "due_date": "2026-12-01"})
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == "Buy milk"
    assert body["due_date"] == "2026-12-01"
    assert set(body) == {"id", "title", "due_date"}


def test_create_without_due_date_gives_null(client: TestClient) -> None:  # AC-001.2
    response = _post(client, {"title": "Buy milk"})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_create_with_null_due_date(client: TestClient) -> None:  # AC-001.2
    response = _post(client, {"title": "Buy milk", "due_date": None})
    assert response.status_code == 201
    assert response.json()["due_date"] is None


def test_list_returns_created_tasks_oldest_first(client: TestClient) -> None:  # AC-001.3
    responses = [
        _post(client, {"title": t, "due_date": d})
        for t, d in [("A", "2026-01-01"), ("B", None), ("C", "2027-05-06")]
    ]
    assert [r.status_code for r in responses] == [201, 201, 201]
    created = [r.json() for r in responses]
    assert [c["title"] for c in created] == ["A", "B", "C"]
    assert _listed(client) == created


def test_list_empty_is_empty_array(client: TestClient) -> None:  # AC-001.3
    assert _listed(client) == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": 5},
        {"title": None},
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": " " + "x" * 201 + " "},
    ],
)
def test_invalid_title_rejected(client: TestClient, body: dict[str, Any]) -> None:  # AC-001.4
    response = _post(client, body)
    assert response.status_code == 422
    assert "title" in _locs(response)
    assert _listed(client) == []


def test_title_is_trimmed(client: TestClient) -> None:  # AC-001.4
    response = _post(client, {"title": "  Buy milk  "})
    assert response.status_code == 201
    assert response.json()["title"] == "Buy milk"
    assert _listed(client)[0]["title"] == "Buy milk"


def test_title_of_200_chars_after_trim_accepted(client: TestClient) -> None:  # AC-001.4
    response = _post(client, {"title": " " + "x" * 200 + " "})
    assert response.status_code == 201


@pytest.mark.parametrize("value", ["tomorrow", "2026-02-30", "2026-12-01T10:00:00Z"])
def test_invalid_due_date_rejected(client: TestClient, value: str) -> None:  # AC-001.5
    response = _post(client, {"title": "Buy milk", "due_date": value})
    assert response.status_code == 422
    assert "due_date" in _locs(response)
    assert _listed(client) == []


def test_past_due_date_accepted(client: TestClient) -> None:  # AC-001.5
    response = _post(client, {"title": "Old", "due_date": "2000-01-01"})
    assert response.status_code == 201
    assert response.json()["due_date"] == "2000-01-01"


def test_task_limit_returns_409(
    client: TestClient, fill_tasks: Callable[[int], None]
) -> None:  # AC-001.6
    fill_tasks(1000)
    response = _post(client, {"title": "one too many"})
    assert response.status_code == 409
    assert response.json() == {"detail": "task limit of 1000 reached"}
    assert len(_listed(client)) == 1000
