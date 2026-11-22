"""Smoke tests for spec 001 (AC-001.1, AC-001.3): reach the service by its base URL only."""

from __future__ import annotations

import uuid

import httpx
import pytest


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_create_task(smoke_base_url: str) -> None:  # AC-001.1
    title = f"smoke-{uuid.uuid4()}"
    response = httpx.post(
        smoke_base_url + "/tasks",
        json={"title": title, "due_date": "2026-12-01"},
        timeout=10,
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["id"], str) and body["id"]
    assert body["title"] == title
    assert body["due_date"] == "2026-12-01"


@pytest.mark.smoke
@pytest.mark.writes
def test_smoke_created_task_is_listed_every_time(smoke_base_url: str) -> None:  # AC-002.3
    title = f"smoke-{uuid.uuid4()}"
    created = httpx.post(smoke_base_url + "/tasks", json={"title": title}, timeout=10)
    assert created.status_code == 201
    task_id = created.json()["id"]
    for _ in range(10):  # consecutive GETs may reach different instances
        listed = httpx.get(smoke_base_url + "/tasks", timeout=10)
        assert listed.status_code == 200
        assert task_id in [t["id"] for t in listed.json()]


@pytest.mark.smoke
def test_smoke_list_is_a_stable_array(smoke_base_url: str) -> None:  # read-only check
    for _ in range(3):
        response = httpx.get(smoke_base_url + "/tasks", timeout=10)
        assert response.status_code == 200
        assert isinstance(response.json(), list)


@pytest.mark.smoke
def test_smoke_ready_reflects_database(smoke_base_url: str) -> None:  # read-only check
    response = httpx.get(smoke_base_url + "/ready", timeout=10)
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.smoke
def test_smoke_list_tasks(smoke_base_url: str) -> None:  # AC-001.3
    response = httpx.get(smoke_base_url + "/tasks", timeout=10)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
