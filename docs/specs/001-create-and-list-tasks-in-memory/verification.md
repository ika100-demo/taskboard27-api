# Verification — 001 Create and list tasks in memory

**Result:** pass
**Commit:** 381d1c8 · **Base:** 4168fcd · **Trace:** 7/7 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks_acceptance.py::test_create_task_returns_201_with_fields`, smoke `tests/test_smoke_tasks.py::test_smoke_create_task` | `src/taskboard27_api/tasks/api.py:57-65`, `src/taskboard27_api/tasks/store.py:28-34`, `src/taskboard27_api/main.py:27` | asserts 201, non-empty string `id`, `title` "Buy milk", `due_date` "2026-12-01", and exactly those three fields (design contract); id is `uuid4` |
| AC-001.2 | met | `tests/test_tasks_acceptance.py::test_create_without_due_date_gives_null`, `::test_create_with_null_due_date` | `src/taskboard27_api/tasks/api.py:23`, `:36-37` | both the omitted and the explicit `null` case assert 201 and `due_date is None` |
| AC-001.3 | met | `tests/test_tasks_acceptance.py::test_list_returns_created_tasks_oldest_first`, `::test_list_empty_is_empty_array`, smoke `tests/test_smoke_tasks.py::test_smoke_list_tasks` | `src/taskboard27_api/tasks/api.py:68-71`, `src/taskboard27_api/tasks/store.py:36-38` | list compared by equality with the three creation responses in order A, B, C, so exactly three, oldest first, same fields; empty store gives `[]` |
| AC-001.4 | met | `tests/test_tasks_acceptance.py::test_invalid_title_rejected` (7 cases), `::test_title_is_trimmed`, `::test_title_of_200_chars_after_trim_accepted` | `src/taskboard27_api/tasks/api.py:22`, `:25-31` | missing, int, null, empty, whitespace, 201 chars, 201 chars after trim: 422 with `loc[-1] == "title"` and empty list afterwards; trimming asserted on response and list; 200-char boundary accepted |
| AC-001.5 | met | `tests/test_tasks_acceptance.py::test_invalid_due_date_rejected` (`tomorrow`, `2026-02-30`, `2026-12-01T10:00:00Z`), `::test_past_due_date_accepted` | `src/taskboard27_api/tasks/api.py:18`, `:33-44` | 422 with `loc[-1] == "due_date"`, no task listed; `2000-01-01` accepted and echoed |
| AC-001.6 | met | `tests/test_tasks_acceptance.py::test_task_limit_returns_409` | `src/taskboard27_api/tasks/store.py:8`, `:30-33`; `src/taskboard27_api/tasks/api.py:60-63` | store pre-filled to 1000; asserts 409, body `{"detail": "task limit of 1000 reached"}`, list length still 1000; check and append under one lock |
| AC-001.7 | met | `tests/test_tasks_acceptance.py::test_restart_empties_list` | `src/taskboard27_api/tasks/store.py:22-26`, `:45-49` | restart simulated by a fresh `TaskStore()` as design.md specifies; the store is a process-local list with no persistence, so a new process starts empty |

## Non-goals

No edit, complete or delete endpoints; no persistence (store is a module-level in-memory list); no cross-instance sharing; no filtering, sorting options, search or pagination on `GET /tasks`; no users or ownership; no authentication added (as A8 requires). The diff touches no template-owned files beyond the one `include_router` line in `main.py`, which plan t2 asks for. ✔

## Deviations from the plan

- `tests/test_tasks_acceptance.py` and `tests/test_smoke_tasks.py` are in no task's `files`: they are the red-phase acceptance tests written before the tasks; acceptable.
- `docs/specs/001-create-and-list-tasks-in-memory/{spec,plan,design}.md` changed: pipeline artefacts (status `building`, plan, design); acceptable.
- Tasks t1 and t2 both `done: true`. No `ux.md` (API-only service). ✔

## Contract

Matches `design.md`: Task object `{id, title, due_date}` with no other fields (`TaskOut`, `api.py:47-50`), FastAPI's standard 422 body, 409 `{"detail": "task limit of 1000 reached"}`, `GET /tasks` unpaginated in creation order, `due_date` validated as a string by regex plus `date.fromisoformat`. No `contract/` directory, so no shared contract rules apply. ✔

## Notes

- `tests/test_smoke_tasks.py::test_smoke_list_tasks` (read-only) asserts only `200` and a JSON array, per design.md's smoke plan; it fails without the feature (404), so it is not a smoke-only pass. The full AC-001.3 behaviour is proven in-process.
- `store.py:18` carries `# noqa: N818` (exception name fixed by design.md); production code, not an acceptance test, so no suppressions section.

## Mutation check (report only)

15 of 18 mutants of the changed code were caught by the acceptance tests (83 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard27_api/tasks/store.py:49 return value → None`
- `src/taskboard27_api/tasks/store.py:11 True → False`
- `src/taskboard27_api/tasks/store.py:42 return value → None`
