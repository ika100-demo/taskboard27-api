---
spec_id: 002-persistent-tasks-in-postgres
shape: service-python
spec_hash: c153058e2e1a
summary: Postgres-backed TaskStore with DB-serialised 1000 limit, 503 on storage outage, DB-aware /ready, contract rule ids for title errors
tasks:
  - id: t1
    title: Replace the in-memory TaskStore with a Postgres-backed one
    files: [pyproject.toml, uv.lock, devbox.json, devbox.lock, src/taskboard27_api/tasks/store.py, src/taskboard27_api/tasks/__init__.py, tests/test_task_store.py, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5]
    parallel_safe: true
    depends_on: []
  - id: t2
    title: Title validation errors carry the contract rule ids
    files: [src/taskboard27_api/tasks/api.py, src/taskboard27_api/main.py]
    covers: [AC-002.6]
    parallel_safe: true
    depends_on: []
  - id: t3
    title: 503 on storage outage, DB-aware /ready, schema setup at startup
    files: [src/taskboard27_api/tasks/api.py, src/taskboard27_api/main.py]
    covers: [AC-002.2, AC-002.5]
    parallel_safe: true
    depends_on: [t1, t2]
---

# Plan — 002 Persistent tasks in Postgres

Contract, schema, timeouts and module signatures: [design.md](design.md).

## t1 — Replace the in-memory TaskStore with a Postgres-backed one

**Files:** pyproject.toml, uv.lock, devbox.json, devbox.lock, src/taskboard27_api/tasks/store.py, src/taskboard27_api/tasks/__init__.py, tests/test_task_store.py, docs/env-vars.md
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5
**Goal:** `TaskStore` keeps tasks in the Postgres table of design.md "Data", creates that table itself, serialises the 1000-task limit in the database and raises `StorageUnavailable` within the timeouts when the database is unreachable. Its `add`/`list` signatures stay as in 001, so the existing endpoints persist tasks without change.

**Implementation notes:**
- Dependencies: add `psycopg[binary]>=3.2` to `dependencies` and `pytest-postgresql>=6` to the `dev` extra in `pyproject.toml`. Regenerate `uv.lock` through devbox (the init hook's `uv sync`), never with `uv add`. Add the `postgresql` package to `devbox.json` `packages` and let devbox update `devbox.lock`. Set `postgresql_exec = "pg_ctl"` in `[tool.pytest.ini_options]` so pytest-postgresql uses the devbox binary on PATH.
- `store.py` as in design.md "Modules": `TaskStore(database_url: str | None, max_tasks=MAX_TASKS)` does no I/O in `__init__`. Each operation opens its own connection with `connect_timeout=3`, `options="-c statement_timeout=3000"`, `tcp_user_timeout=3000` and closes it.
- `ensure_schema()`: in one transaction, `pg_advisory_xact_lock(SCHEMA_LOCK)` then the `CREATE TABLE IF NOT EXISTS`. Set an instance flag so that `add`/`list` call it lazily only until it has succeeded once. Log `schema_ready` once.
- `add`: one transaction, `pg_advisory_xact_lock(INSERT_LOCK)`, then `INSERT INTO tasks (id, title, due_date) SELECT %s, %s, %s WHERE (SELECT count(*) FROM tasks) < %s RETURNING seq`. No row means `TaskLimitReached`. Pass `due_date` as `datetime.date` or `None`.
- `list`: `SELECT id, title, due_date FROM tasks ORDER BY seq`, mapped to `Task(str(id), title, due_date.isoformat() if due_date else None)`.
- `ping`: `SELECT 1`.
- Error mapping exactly as in design.md "Decisions": `OperationalError`/`InterfaceError`/unset URL, and any `psycopg.Error` in schema setup, become `StorageUnavailable`. Log `task_storage_unavailable` or `schema_setup_failed` with the exception class name only, never the URL.
- `get_task_store()` is `@functools.cache`, returns `TaskStore(os.environ.get("DATABASE_URL"))` and never raises. Remove `__len__`.
- `__init__.py` also exports `StorageUnavailable`.
- `tests/test_task_store.py`: rewrite the 001 unit tests against the `database_url` fixture (order, limit with `max_tasks=3`, unique ids, schema idempotence on a second `ensure_schema()`, `StorageUnavailable` for a closed port and for `None`).
- `docs/env-vars.md`: add a "Storage" section for `DATABASE_URL` (required, no default, libpq URI, injected by the gitops `uses: postgres`, never logged).

**Done when:** `tests/test_task_store.py` passes; the acceptance tests for AC-002.1, AC-002.3 and AC-002.4 pass, as do the store-level parts of AC-002.2 (lazy schema creation, kept tasks); `devbox run quality` is green. The HTTP 503 and `/ready` parts of AC-002.5 and the startup part of AC-002.2 need t3.

## t2 — Title validation errors carry the contract rule ids

**Files:** src/taskboard27_api/tasks/api.py, src/taskboard27_api/main.py
**Covers:** AC-002.6
**Goal:** every title failure in the contract is a `422` item on `["body", "title"]` whose `type` is `title-required`, `title-min` or `title-max` and whose `msg` is `Enter a title of 1 to 200 characters`. Every other validation error stays unchanged.

**Implementation notes:**
- `api.py`: `TITLE_MESSAGE` constant. The `title` after-validator strips, then raises `PydanticCustomError("title-min", TITLE_MESSAGE)` for length 0 and `PydanticCustomError("title-max", TITLE_MESSAGE)` for length over 200. Keep `StrictStr`, so non-strings keep `string_type`.
- `api.py`: `title_required_handler(request, exc: RequestValidationError)` returns `JSONResponse(422, {"detail": jsonable_encoder(errors)})`. In it, each item with `type == "missing"` and `tuple(loc) == ("body", "title")` gets `type="title-required"`, `msg=TITLE_MESSAGE`. All other items pass through untouched.
- `main.py`: `app.add_exception_handler(RequestValidationError, title_required_handler)`.
- `due_date` validation is unchanged (spec note A1).

**Done when:** the acceptance tests for AC-002.6 and the contract check (`tests/test_contract.py`, all `title-*` cases) pass; the 001 title and due_date tests still pass; `devbox run quality` is green.

## t3 — 503 on storage outage, DB-aware /ready, schema setup at startup

**Files:** src/taskboard27_api/tasks/api.py, src/taskboard27_api/main.py
**Covers:** AC-002.2, AC-002.5
**Goal:** when the database is unreachable, `POST`/`GET /tasks` answer `503 {"detail": "task storage unavailable"}` and `/ready` answers `503`; they recover by themselves when it returns. Startup creates the schema without blocking or crashing.

**Implementation notes:**
- `api.py`: in both endpoints, catch `StorageUnavailable` and raise `HTTPException(503, detail="task storage unavailable")` (in `create_task` next to the existing `TaskLimitReached` → 409).
- `main.py`: `/ready` takes `store: TaskStore = Depends(get_task_store)` and calls `store.ping()`. It returns `200 {"status": "ready"}`, or on `StorageUnavailable` a `JSONResponse(503, {"status": "unavailable"})`. `/health` is unchanged.
- `main.py`: add a `lifespan` to `FastAPI(...)` that calls `get_task_store().ensure_schema()` and swallows `StorageUnavailable`, which the store has already logged. Startup does not wait for the database.
- Depends on t2 only because both edit `api.py` and `main.py`; it builds on t2's version of those files.

**Done when:** the acceptance tests for AC-002.5 (refused and hanging database, each answered within 6 s; recovery) and the startup part of AC-002.2 (`with TestClient(app):` against an empty database creates the table) pass; `devbox run test` and `devbox run quality` are green.
