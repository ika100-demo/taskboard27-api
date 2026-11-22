# Design — 002 Persistent tasks in Postgres

## Decisions

- **Tasks live in one Postgres table `tasks`, read through `DATABASE_URL` only** (spec note "no new env var"). The driver is psycopg 3 (`psycopg[binary]`, which ships its own libpq, so the Dockerfile does not change). The endpoints stay synchronous as in 001, and FastAPI runs them in its thread pool. This outlives the feature, and ADR-000 asks for an ADR for any departure from the template stack. ADR to add with `cplat adr add postgres-task-storage --decision "Tasks are stored in Postgres via psycopg 3; the service creates its own schema at startup"` (see the report).
- **One new connection per operation, no pool.** The spec's timeouts and recovery (AC-002.5) are then exactly libpq's: `connect_timeout=3`, server-side `statement_timeout=3000`, and `tcp_user_timeout=3000` so a silent network drop also ends within 3 s. The next request reconnects with nothing to reset. A pool would add its own wait and reconnect states that would have to be tuned to the same 6 s bound. At this load (2 replicas, at most 1000 rows) the connect cost of a few ms is acceptable. A pool is a later optimisation behind the same `TaskStore` interface.
- **The service creates its own schema (AC-002.2):** `CREATE TABLE IF NOT EXISTS` inside a transaction that first takes `pg_advisory_xact_lock(SCHEMA_LOCK)`, so two replicas starting together do not race on the catalog. It runs once at startup (best effort in the FastAPI lifespan, logged on failure, never crashing the process) and lazily before the first operation of a `TaskStore` instance that has not yet confirmed the schema. A store that starts while the database is down therefore still sets the schema up once the database returns. No migration tool: one table with no history. The first spec that changes the schema introduces one.
- **The limit is serialised in the database (AC-002.4):** `POST` runs in one transaction: `SELECT pg_advisory_xact_lock(INSERT_LOCK)`, then `INSERT ... SELECT ... WHERE (SELECT count(*) FROM tasks) < 1000 RETURNING seq`. No returned row means `TaskLimitReached`. This holds across processes and restarts.
- **Order is a `seq` identity column (AC-002.1):** `GET` uses `ORDER BY seq`. Inserts are serialised by the lock, so seq order equals commit order. Ids stay `str(uuid.uuid4())` from Python, as in 001.
- **`due_date` is a `DATE` column.** The API keeps validating the string exactly as in 001 (spec note A1) and returns `due_date.isoformat()`.
- **Storage failures map to `StorageUnavailable` → `503 {"detail": "task storage unavailable"}` (AC-002.5).** The mapped failures are `psycopg.OperationalError` (connect failure, `QueryCanceled` from the statement timeout, lost connection), `psycopg.InterfaceError`, an unset `DATABASE_URL`, and any `psycopg.Error` during schema setup (e.g. missing CREATE privilege), which is logged as an error. Other errors stay a 500: they are bugs.
- **`get_task_store()` does no I/O and never raises.** FastAPI resolves it next to body validation, so an invalid body with the database down is still a `422` ("validation runs before the limit and storage checks"). It is `functools.cache`d and reads `DATABASE_URL` on first call. Tests reset it with `get_task_store.cache_clear()`.
- **Title errors carry the contract rule ids (AC-002.6).** The `title` after-validator raises `PydanticCustomError("title-min" | "title-max", "Enter a title of 1 to 200 characters")`. A missing `title` key is pydantic's `missing` error before any validator runs. A `RequestValidationError` handler rewrites exactly the items with `type == "missing"` and `loc == ["body", "title"]` into `type: "title-required"` with the same `msg`, and leaves every other item and the body shape unchanged. A non-string title (including `null`) and every `due_date` failure keep pydantic's own `type`/`msg`, as the contract demands.
- **`/ready` asks the store (`store.ping()` = `SELECT 1` under the same timeouts) through the same `get_task_store` dependency,** so tests that override the store also steer readiness. `/health` stays independent of the database.
- **Test database: devbox package `postgresql` plus the `pytest-postgresql` dev dependency.** pytest starts a throwaway server from `pg_ctl` on PATH, so the same setup works locally, on GitHub-hosted runners and on self-hosted runners, with no Docker and no change to the platform-owned `ci.yml`. A `TEST_DATABASE_URL` environment variable lets a runner point the tests at an existing server instead. Limitation: `initdb` refuses to run as root, so a runner that runs as root must set `TEST_DATABASE_URL`.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard27_api/tasks/store.py` | `Task`, `TaskLimitReached`, `StorageUnavailable`, `MAX_TASKS`, Postgres-backed `TaskStore`, schema SQL, `get_task_store()` | changed (in-memory list replaced) |
| `src/taskboard27_api/tasks/__init__.py` | re-exports, adds `StorageUnavailable` | changed |
| `src/taskboard27_api/tasks/api.py` | title errors with rule ids, the `missing`→`title-required` handler, 503 mapping | changed |
| `src/taskboard27_api/main.py` | registers the validation handler, lifespan schema setup, `/ready` via the store | changed |

```python
# store.py
MAX_TASKS: Final = 1000
CONNECT_TIMEOUT_S: Final = 3
STATEMENT_TIMEOUT_MS: Final = 3000

@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: str | None            # "YYYY-MM-DD" or None

class TaskLimitReached(Exception): ...
class StorageUnavailable(Exception): ...

class TaskStore:
    def __init__(self, database_url: str | None, max_tasks: int = MAX_TASKS) -> None: ...   # no I/O
    def add(self, title: str, due_date: str | None) -> Task: ...     # TaskLimitReached | StorageUnavailable
    def list(self) -> list[Task]: ...                                # oldest first; StorageUnavailable
    def ping(self) -> None: ...                                      # SELECT 1; StorageUnavailable
    def ensure_schema(self) -> None: ...                             # idempotent; StorageUnavailable

@functools.cache
def get_task_store() -> TaskStore:   # TaskStore(os.environ.get("DATABASE_URL"))
    ...

# connection, per operation:
psycopg.connect(database_url, connect_timeout=3,
                options="-c statement_timeout=3000", tcp_user_timeout=3000, autocommit=False)
```

```python
# api.py
TITLE_MESSAGE: Final = "Enter a title of 1 to 200 characters"

async def title_required_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # 422 {"detail": jsonable_encoder(errors)} where each error with type "missing" and
    # loc ("body", "title") becomes type "title-required", msg TITLE_MESSAGE; all else unchanged
```

## Contract

No authentication. JSON in and out, `Content-Type: application/json`. Consumer: `taskboard27-web`, server-side.

**Task object** (every task in a response): `{"id": string (UUID), "title": string (trimmed, 1..200 characters), "due_date": "YYYY-MM-DD" | null}`. No other fields.

**`POST /tasks`**: request body is an object, and unknown fields are ignored.

| Field | Type | Rules |
|---|---|---|
| `title` | string, required | trimmed; after trimming 1..200 characters; stored trimmed |
| `due_date` | string or null, optional (default `null`) | exactly `YYYY-MM-DD` and a real calendar date; past dates accepted |

Validation runs first, then the limit, then storage:

- `201` → the created Task object. It is stored, and every instance lists it from then on (AC-002.1, AC-002.3).
- `422` → FastAPI's standard body, nothing stored (AC-002.6):
  ```json
  {"detail": [{"type": "title-min", "loc": ["body", "title"], "msg": "Enter a title of 1 to 200 characters", "input": "   "}]}
  ```
  | Title input | `type` | `msg` |
  |---|---|---|
  | key absent | `title-required` | `Enter a title of 1 to 200 characters` |
  | `""` or only whitespace | `title-min` | same |
  | longer than 200 characters after trimming | `title-max` | same |
  | not a string (number, `null`, ...) | pydantic's (`string_type`) | pydantic's |
  | any `due_date` failure (`loc` ends in `"due_date"`) | pydantic's (`value_error`) | pydantic's |
  Items may carry pydantic's extra keys (`ctx`, `url`). Callers match `loc[-1]`.
- `409` → `{"detail": "task limit of 1000 reached"}` when 1000 tasks are stored, across all instances and restarts. Nothing is stored (AC-002.4).
- `503` → `{"detail": "task storage unavailable"}` when the database cannot be reached or does not answer within the timeouts. Nothing is stored. The answer comes within 6 s (AC-002.5).

**`GET /tasks`**

- `200` → JSON array of every stored Task object, oldest first; `[]` when none; at most 1000 entries.
- `503` → `{"detail": "task storage unavailable"}`, within 6 s.

**`GET /ready`** → `200 {"status": "ready"}` when `SELECT 1` succeeds within the timeouts, else `503 {"status": "unavailable"}` (AC-002.5). **`GET /health`** → `200 {"status": "ok"}` regardless of the database.

**Configuration:** `DATABASE_URL` (libpq URI, `postgresql://` or `postgres://`, injected by the gitops `uses: postgres`). When it is unset, task endpoints and `/ready` answer `503` and the error is logged. The URL is never logged.

## Data

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    id       UUID NOT NULL UNIQUE,
    title    TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
    due_date DATE NULL
);
```

The two advisory lock keys are fixed `BIGINT` constants in `store.py` (`SCHEMA_LOCK`, `INSERT_LOCK`), distinct from each other. At most 1000 rows. Nothing is migrated from 001, because the in-memory tasks are lost at every restart anyway.

## Observability

structlog events: `task_created` (`task_id`) as in 001; `task_storage_unavailable` (warning, `operation`, `error` = exception class name, never the URL or the title); `schema_ready` (info, once per store); `schema_setup_failed` (error, `error`).

## Testing notes

- **Server:** a session fixture `database_url` yields `TEST_DATABASE_URL` when set, otherwise a URL to pytest-postgresql's `postgresql_proc` (`postgresql://{user}:{password}@{host}:{port}/{dbname}`, with the database created via `DatabaseJanitor`). Put it in `tests/conftest.py` as an **autouse** fixture for every test, because `/ready` (tests/test_health.py), the contract check and the 001 acceptance tests all need it now. Before each test it sets `DATABASE_URL` (monkeypatch), runs `DROP TABLE IF EXISTS tasks` and calls `get_task_store.cache_clear()`. Every test therefore starts with an empty database without a schema (AC-002.2's precondition).
- **Restart (AC-002.1, AC-002.2):** `get_task_store.cache_clear()` or a new `TaskStore(database_url)` via `app.dependency_overrides[get_task_store]`. Startup schema creation runs with `with TestClient(app):` (the lifespan).
- **Two processes (AC-002.3, AC-002.4):** two `TaskStore(database_url)` instances or two `TestClient`s with different overrides. For the race: 999 rows bulk-inserted with SQL (`INSERT ... SELECT gen_random_uuid(), 't' || g, NULL FROM generate_series(1, 999) g`), then two or more concurrent `POST`s from threads. Exactly one gets `201`, the rest `409`, and the count is 1000. Fill 1000 rows by SQL, not 1000 API calls.
- **Outage (AC-002.5):** override the store with `TaskStore("postgresql://u@127.0.0.1:<closed port>/db")` for refused connections, and with a URL to a local TCP listener that accepts and never answers to exercise `connect_timeout` (expect `503` in under 6 s). Swap the real URL back for the recovery half.
- **001 tests:** `tests/test_tasks_acceptance.py` installs `TaskStore()` with no arguments, and its AC-001.7 test (restart empties the list) is replaced by AC-002.1. The testers adapt that file to the Postgres fixture and remove the AC-001.7 test. The coders do not touch it.
- **Smoke:** an AC-002.3 writes-smoke creates `smoke-<uuid>` and checks it in 10 consecutive `GET /tasks`. The read-only `GET /tasks` and `/ready` checks run in staging and prod.
