# Design — 001 Create and list tasks in memory

## Decisions

- Tasks live in a process-local `TaskStore` (a list guarded by a `threading.Lock`), not a database: the spec's non-goals rule out persistence and cross-instance sharing (AC-001.7). Sync FastAPI endpoints run in a thread pool, so the capacity check and the append happen under one lock, otherwise two concurrent requests at 999 tasks could both pass the check (AC-001.6). Feature-local and replaced by a later persistence spec, so no ADR.
- The store reaches the endpoints through a FastAPI dependency `get_task_store()` returning a module-level singleton. Tests isolate themselves and simulate a restart (AC-001.7) with `app.dependency_overrides[get_task_store] = lambda: TaskStore()`, no hidden reset hooks in production code.
- `due_date` is validated as a string against `^\d{4}-\d{2}-\d{2}$` and then `datetime.date.fromisoformat`, not as a pydantic `date`: pydantic's lax `date` parsing accepts integers (unix timestamps) and zero-time datetime strings, which AC-001.5 must reject. It is returned as the same `YYYY-MM-DD` string.
- `title` is a `StrictStr` (pydantic otherwise never coerces, but strict makes "not a string" explicit), trimmed in a `field_validator`, then checked for 1..200 characters, so every title failure is a 422 on `title` in the standard format (AC-001.4, A7).
- Validation errors use FastAPI's default 422 body unchanged (A7, "the service's standard validation error format"); the 409 uses `HTTPException(409, detail="task limit of 1000 reached")`.
- The limit is a module constant `MAX_TASKS = 1000`, passed into `TaskStore(max_tasks=...)` so tests can build a small store; no env var, because the spec fixes the number.
- Ids are `str(uuid.uuid4())` (A2). Order is insertion order (A5).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard27_api/tasks/__init__.py` | package marker, re-exports `router`, `TaskStore`, `get_task_store` | new |
| `src/taskboard27_api/tasks/store.py` | `Task` dataclass, `TaskStore`, `TaskLimitReached`, `MAX_TASKS`, `get_task_store()` | new |
| `src/taskboard27_api/tasks/api.py` | request/response models, `APIRouter` with `POST /tasks`, `GET /tasks` | new |
| `src/taskboard27_api/main.py` | `app.include_router(tasks.router)` | changed |

```python
# store.py
MAX_TASKS: Final = 1000

@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: str | None   # "YYYY-MM-DD" or None

class TaskLimitReached(Exception): ...

class TaskStore:
    def __init__(self, max_tasks: int = MAX_TASKS) -> None: ...
    def add(self, title: str, due_date: str | None) -> Task: ...   # raises TaskLimitReached when len == max_tasks
    def list(self) -> list[Task]: ...                              # copy, oldest first
    def __len__(self) -> int: ...

def get_task_store() -> TaskStore: ...   # module singleton
```

## Contract

No authentication (A8). JSON in and out, `Content-Type: application/json`.

**Task object** (every response): `{"id": string (UUID, non-empty), "title": string, "due_date": string "YYYY-MM-DD" | null}`. No other fields.

**`POST /tasks`**

Request body (object; unknown fields are ignored):

| Field | Type | Rules |
|---|---|---|
| `title` | string, required | trimmed of surrounding whitespace; after trimming 1..200 characters; stored trimmed |
| `due_date` | string or null, optional (default null) | exactly `YYYY-MM-DD` and a real calendar date; past dates accepted; no time part, no time zone |

Responses:

- `201` → the created Task object (AC-001.1, AC-001.2, AC-001.4 trimming).
- `422` → FastAPI's standard validation body, nothing stored (AC-001.4, AC-001.5):
  ```json
  {"detail": [{"type": "<pydantic error type>", "loc": ["body", "title"], "msg": "<text>", "input": "<value>"}]}
  ```
  The offending field name is the last element of `loc` (`"title"` or `"due_date"`). A missing body or a non-object body yields `loc: ["body"]`. Tests assert on `status == 422` and on some `detail[*].loc[-1] == "<field>"`, never on `msg` or `type` text.
- `409` → `{"detail": "task limit of 1000 reached"}` when the store already holds 1000 tasks; nothing stored (AC-001.6). Validation runs first: an invalid body at the limit is a `422`.

**`GET /tasks`**

- `200` → JSON array of Task objects in creation order, oldest first; `[]` when empty (AC-001.3). Unpaginated.

Restart semantics: a new process (or a fresh `TaskStore`) starts with `[]` (AC-001.7).

## Data

None persisted. In memory: an ordered `list[Task]` of at most 1000 entries per process (roughly 1000 x ~300 bytes). Each replica holds its own list; running more than one replica shows different lists per replica, which the spec accepts as a non-goal.

## Testing notes

- Isolation: an autouse fixture in the acceptance tests sets `app.dependency_overrides[get_task_store]` to a fresh `TaskStore()` and clears it afterwards.
- AC-001.6: override with a store pre-filled via `store.add(...)` 1000 times (fast, in-process), then POST.
- AC-001.7: create tasks, swap in a new `TaskStore()` (the restart), `GET /tasks` is `[]`.
- Smoke (AC-001.1 writes, AC-001.3 read-only part: `GET /tasks` is `200` and an array); AC-001.1 smoke is `@pytest.mark.writes` with title `smoke-<uuid>`.
