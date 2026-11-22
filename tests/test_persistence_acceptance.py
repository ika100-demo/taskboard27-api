"""Acceptance tests for spec 002: persistent tasks in Postgres."""

from __future__ import annotations

import itertools
import socket
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from typing import Any

import pytest
from fastapi.testclient import TestClient

from taskboard27_api.main import app

UNAVAILABLE = {"detail": "task storage unavailable"}


def _store_module() -> Any:
    try:
        from taskboard27_api.tasks import store
    except ImportError:
        pytest.fail("taskboard27_api.tasks.store is missing")
    return store


def _restart() -> None:
    """A service restart: the cached store is dropped, the next request builds a new one."""
    app.dependency_overrides.clear()
    clear = getattr(_store_module().get_task_store, "cache_clear", None)
    assert clear is not None, "get_task_store must be functools.cache'd"
    clear()


def _override(store: Any) -> None:
    app.dependency_overrides[_store_module().get_task_store] = lambda: store


def _new_store(url: str) -> Any:
    return _store_module().TaskStore(url)


def _post(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post("/tasks", json=body)


def _closed_port_url() -> str:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"postgresql://u@127.0.0.1:{port}/db"


@pytest.fixture()
def silent_listener() -> Iterator[str]:
    """A TCP listener that accepts connections and never answers."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(16)
    port = server.getsockname()[1]
    held: list[socket.socket] = []
    stop = threading.Event()

    def _accept() -> None:
        server.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            held.append(conn)

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    try:
        yield f"postgresql://u@127.0.0.1:{port}/db"
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in held:
            conn.close()
        server.close()


class _Proxy:
    """A TCP forwarder in front of the test database that can be switched off and on."""

    def __init__(self, target_host: str, target_port: int) -> None:
        self._target = (target_host, target_port)
        self._lock = threading.Lock()
        self._socks: list[socket.socket] = []
        self._server: socket.socket | None = None
        self.port = 0

    def start(self) -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", self.port))
        server.listen(16)
        self.port = server.getsockname()[1]
        self._server = server
        threading.Thread(target=self._accept, args=(server,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            socks, self._socks = self._socks, []
        if self._server is not None:
            self._server.close()
            self._server = None
        for sock in socks:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _accept(self, server: socket.socket) -> None:
        while True:
            try:
                client, _ = server.accept()
                upstream = socket.create_connection(self._target, timeout=5)
            except OSError:
                if self._server is not server:
                    return
                continue
            with self._lock:
                self._socks += [client, upstream]
            for src, dst in ((client, upstream), (upstream, client)):
                threading.Thread(target=self._pipe, args=(src, dst), daemon=True).start()

    @staticmethod
    def _pipe(src: socket.socket, dst: socket.socket) -> None:
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for sock in (src, dst):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass


@pytest.fixture()
def db_proxy(database_url: str) -> Iterator[tuple[_Proxy, str]]:
    """(proxy, URL of the test database through the proxy)."""
    from urllib.parse import urlsplit

    parts = urlsplit(database_url)
    proxy = _Proxy(parts.hostname or "127.0.0.1", parts.port or 5432)
    proxy.start()
    try:
        old = f"{parts.hostname}:{parts.port}"
        yield proxy, database_url.replace(old, f"127.0.0.1:{proxy.port}")
    finally:
        proxy.stop()


# AC-002.1


def test_tasks_survive_restart_oldest_first(client: TestClient) -> None:  # AC-002.1
    created = [
        _post(client, {"title": t, "due_date": d}).json()
        for t, d in [("A", "2026-01-01"), ("B", None), ("C", "2027-05-06")]
    ]
    assert [c["title"] for c in created] == ["A", "B", "C"]
    _restart()
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == created


def test_tasks_visible_to_a_new_store_instance(
    client: TestClient, database_url: str
) -> None:  # AC-002.1
    created = _post(client, {"title": "A", "due_date": "2026-03-04"}).json()
    listed = _new_store(database_url).list()
    assert [(t.id, t.title, t.due_date) for t in listed] == [(created["id"], "A", "2026-03-04")]


# AC-002.2


def test_startup_creates_schema_on_empty_database(
    database_url: str, count_tasks: Callable[[], int]
) -> None:  # AC-002.2
    with TestClient(app) as started:  # runs the lifespan
        assert count_tasks() == 0  # the table exists without a manual step
        response = started.get("/tasks")
        assert response.status_code == 200
        assert response.json() == []


def test_empty_database_lists_empty_without_startup(client: TestClient) -> None:  # AC-002.2
    response = client.get("/tasks")
    assert response.status_code == 200
    assert response.json() == []


def test_starting_again_keeps_stored_tasks(database_url: str) -> None:  # AC-002.2
    with TestClient(app) as first:
        created = _post(first, {"title": "keep me"}).json()
    _restart()
    with TestClient(app) as second:
        response = second.get("/tasks")
        assert response.status_code == 200
        assert response.json() == [created]


# AC-002.3


def test_task_created_on_one_process_is_listed_on_the_other(
    client: TestClient, database_url: str
) -> None:  # AC-002.3
    a, b = _new_store(database_url), _new_store(database_url)
    ids: list[str] = []
    for i in range(5):
        _override(a)
        created = _post(client, {"title": f"t{i}"})
        assert created.status_code == 201
        ids.append(created.json()["id"])
        for store in (a, b):
            _override(store)
            listed = client.get("/tasks")
            assert listed.status_code == 200
            assert [t["id"] for t in listed.json()] == ids


# AC-002.4


def test_limit_after_restart(
    client: TestClient, fill_tasks: Callable[[int], None], count_tasks: Callable[[], int]
) -> None:  # AC-002.4
    fill_tasks(1000)
    _restart()
    response = _post(client, {"title": "too many"})
    assert response.status_code == 409
    assert response.json() == {"detail": "task limit of 1000 reached"}
    assert len(client.get("/tasks").json()) == 1000
    assert count_tasks() == 1000


def test_last_slot_then_409(
    client: TestClient, fill_tasks: Callable[[int], None], count_tasks: Callable[[], int]
) -> None:  # AC-002.4
    fill_tasks(999)
    assert _post(client, {"title": "the 1000th"}).status_code == 201
    response = _post(client, {"title": "the 1001st"})
    assert response.status_code == 409
    assert response.json() == {"detail": "task limit of 1000 reached"}
    assert count_tasks() == 1000


def test_concurrent_posts_at_999_stored_give_one_201(
    client: TestClient,
    database_url: str,
    fill_tasks: Callable[[int], None],
    count_tasks: Callable[[], int],
) -> None:  # AC-002.4
    fill_tasks(999)
    stores = [_new_store(database_url) for _ in range(2)]
    turn = itertools.count()
    app.dependency_overrides[_store_module().get_task_store] = lambda: stores[next(turn) % 2]

    def _send(i: int) -> Any:
        return client.post("/tasks", json={"title": f"race{i}"})

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(_send, range(6)))
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409, 409, 409, 409, 409]
    for r in responses:
        if r.status_code == 409:
            assert r.json() == {"detail": "task limit of 1000 reached"}
    assert count_tasks() == 1000
    assert len(client.get("/tasks").json()) == 1000


# AC-002.5


def test_unreachable_database_answers_503_and_stores_nothing(
    client: TestClient, db_proxy: tuple[_Proxy, str], count_tasks: Callable[[], int]
) -> None:  # AC-002.5
    proxy, url = db_proxy
    _override(_new_store(url))  # the same store for the whole test: no restart
    before = _post(client, {"title": "before"})
    assert before.status_code == 201

    proxy.stop()  # the database becomes unreachable
    timed: list[tuple[Any, float]] = []
    for send in (
        lambda: _post(client, {"title": "during"}),
        lambda: client.get("/tasks"),
        lambda: client.get("/ready"),
    ):
        start = time.monotonic()
        response = send()
        timed.append((response, time.monotonic() - start))
    posted, listed, ready = (r for r, _ in timed)
    assert all(elapsed < 6 for _, elapsed in timed)
    assert posted.status_code == 503
    assert posted.json() == UNAVAILABLE
    assert listed.status_code == 503
    assert listed.json() == UNAVAILABLE
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable"}
    assert client.get("/health").status_code == 200

    proxy.start()  # the database is back; the next requests reconnect by themselves
    assert client.get("/ready").status_code == 200
    assert client.get("/ready").json() == {"status": "ready"}
    assert client.get("/tasks").json() == [before.json()]
    assert count_tasks() == 1


def test_silent_database_answers_503_within_6_seconds(
    client: TestClient, silent_listener: str
) -> None:  # AC-002.5
    _override(_new_store(silent_listener))
    for send in (
        lambda: _post(client, {"title": "x"}),
        lambda: client.get("/tasks"),
    ):
        start = time.monotonic()
        response = send()
        assert time.monotonic() - start < 6
        assert response.status_code == 503
        assert response.json() == UNAVAILABLE
    start = time.monotonic()
    ready = client.get("/ready")
    assert time.monotonic() - start < 6
    assert ready.status_code == 503


def test_invalid_body_during_outage_is_still_422(client: TestClient) -> None:  # AC-002.5
    _override(_new_store(_closed_port_url()))
    assert _post(client, {"title": "  "}).status_code == 422
    valid = _post(client, {"title": "valid"})
    assert valid.status_code == 503
    assert valid.json() == UNAVAILABLE
    listed = client.get("/tasks")
    assert listed.status_code == 503
    assert listed.json() == UNAVAILABLE


# AC-002.6


@pytest.mark.parametrize(
    ("body", "error_type"),
    [
        ({}, "title-required"),
        ({"due_date": "2026-01-01"}, "title-required"),
        ({"title": ""}, "title-min"),
        ({"title": "   "}, "title-min"),
        ({"title": "x" * 201}, "title-max"),
        ({"title": " " + "x" * 201 + " "}, "title-max"),
    ],
)
def test_title_errors_carry_rule_ids(
    client: TestClient,
    body: dict[str, Any],
    error_type: str,
    count_tasks: Callable[[], int],
) -> None:  # AC-002.6
    response = _post(client, body)
    assert response.status_code == 422
    items = [e for e in response.json()["detail"] if e["loc"][-1] == "title"]
    assert len(items) == 1
    assert items[0]["loc"] == ["body", "title"]
    assert "input" in items[0]
    assert items[0]["type"] == error_type
    assert items[0]["msg"] == "Enter a title of 1 to 200 characters"
    assert client.get("/tasks").json() == []
