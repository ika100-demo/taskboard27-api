---
spec_id: 001-create-and-list-tasks-in-memory
shape: service-python
spec_hash: e3a124be750e
summary: In-memory task store plus POST /tasks and GET /tasks with validation and a 1000-task limit
tasks:
  - id: t1
    title: Add the in-memory TaskStore with capacity limit
    files: [src/taskboard27_api/tasks/__init__.py, src/taskboard27_api/tasks/store.py, tests/test_task_store.py]
    covers: [AC-001.3, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Add POST /tasks and GET /tasks and wire them into the app
    files: [src/taskboard27_api/tasks/__init__.py, src/taskboard27_api/tasks/api.py, src/taskboard27_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: [t1]
    done: true
---

# Plan — 001 Create and list tasks in memory

Contract and module signatures: [design.md](design.md).

## t1 — Add the in-memory TaskStore with capacity limit

**Files:** src/taskboard27_api/tasks/__init__.py, src/taskboard27_api/tasks/store.py, tests/test_task_store.py
**Covers:** AC-001.3, AC-001.6, AC-001.7
**Goal:** a thread-safe, process-local store that keeps tasks in creation order and refuses the 1001st task, exposed through a FastAPI-overridable dependency.

**Implementation notes:**
- `store.py` exactly as in design.md "Modules": `MAX_TASKS = 1000`, frozen `Task(id, title, due_date)`, `TaskLimitReached`, `TaskStore(max_tasks=MAX_TASKS)` with `add`, `list`, `__len__`.
- `add` generates `str(uuid.uuid4())`; the length check and the append happen under one `threading.Lock`.
- `list` returns a copy in insertion order, so callers cannot mutate the store.
- `get_task_store()` returns one module-level `TaskStore()`.
- `__init__.py` re-exports `Task`, `TaskStore`, `TaskLimitReached`, `MAX_TASKS`, `get_task_store`.
- The store does no validation; it trusts the API layer (t2).
- `tests/test_task_store.py`: unit tests for order, copy semantics, limit (with `max_tasks=3`), a fresh store being empty, unique ids.

**Done when:** `tests/test_task_store.py` passes and `devbox run quality` is green. The HTTP acceptance tests need t2.

## t2 — Add POST /tasks and GET /tasks and wire them into the app

**Files:** src/taskboard27_api/tasks/__init__.py, src/taskboard27_api/tasks/api.py, src/taskboard27_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** the HTTP contract of design.md: create with validation, list oldest first, 409 at the limit.

**Implementation notes:**
- `TaskCreate` pydantic model: `title: StrictStr`, `due_date: str | None = None`; unknown fields ignored.
- `title` `field_validator`: strip, then reject length 0 or > 200 with a `ValueError` (yields 422 on `loc[-1] == "title"`).
- `due_date` `field_validator`: when not None, require `^\d{4}-\d{2}-\d{2}$` (`re.fullmatch`) and `date.fromisoformat` to succeed; otherwise `ValueError` (422 on `due_date`). Past dates pass.
- `TaskOut` model `id: str, title: str, due_date: str | None`.
- `router = APIRouter()`; `POST /tasks` (`status_code=201`, `response_model=TaskOut`) and `GET /tasks` (`response_model=list[TaskOut]`), both sync, both take `store: TaskStore = Depends(get_task_store)`.
- Catch `TaskLimitReached` and raise `HTTPException(409, detail="task limit of 1000 reached")`.
- Add `router` to `tasks/__init__.py` exports; `main.py` calls `app.include_router(tasks.router)`.
- Log `task_created` (structlog, field `task_id`, never the title) on success.

**Done when:** the acceptance tests for AC-001.1 to AC-001.7 pass, `devbox run test` and `devbox run quality` are green.
