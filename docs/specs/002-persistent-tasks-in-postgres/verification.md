# Verification — 002 Persistent tasks in Postgres

**Commit:** d5f0c87 · **Base:** df1b641 · **Trace:** 6/6 criteria named by tests

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_persistence_acceptance.py::test_tasks_survive_restart_oldest_first`, `::test_tasks_visible_to_a_new_store_instance` | `src/taskboard27_api/tasks/store.py:88` (insert), `store.py:112` (`ORDER BY seq`), `store.py:145` (cached store rebuilt on restart) | A, B, C with mixed `due_date` compared in full (`id`, `title`, `due_date`, order) after the cached store is dropped |
| AC-002.2 | met | `::test_startup_creates_schema_on_empty_database`, `::test_empty_database_lists_empty_without_startup`, `::test_starting_again_keeps_stored_tasks` | `src/taskboard27_api/main.py:31` (lifespan calls `ensure_schema`), `store.py:64` (advisory lock + `CREATE TABLE IF NOT EXISTS`), `store.py:80` (lazy schema) | conftest drops the table before every test, so the empty-database precondition holds; table counted by SQL after startup |
| AC-002.3 | met | `::test_task_created_on_one_process_is_listed_on_the_other`, `tests/test_smoke_tasks.py::test_smoke_created_task_is_listed_every_time` | `store.py:53` (no in-process state; each operation reads the database) | two processes are modelled as two independent `TaskStore` instances on one DB; the smoke test covers real replicas (10 consecutive GETs) |
| AC-002.4 | met | `::test_limit_after_restart`, `::test_last_slot_then_409`, `::test_concurrent_posts_at_999_stored_give_one_201` | `store.py:96` (`pg_advisory_xact_lock(INSERT_LOCK)` + conditional insert), `src/taskboard27_api/tasks/api.py:80` (409 body) | concurrency test: 6 parallel POSTs over 2 stores at 999 give exactly one 201, five 409 with the exact body, 1000 rows by SQL and by `GET /tasks` |
| AC-002.5 | met | `::test_unreachable_database_answers_503_and_stores_nothing`, `::test_silent_database_answers_503_within_6_seconds`, `::test_invalid_body_during_outage_is_still_422` | `store.py:56` (connect/statement/tcp timeouts 3 s), `store.py:105`/`:123`/`:141` (error mapping), `api.py:82`, `api.py:93` (503 body), `main.py:59` (`/ready` via `ping`) | proxy outage: POST/GET 503 with exact body, `/ready` 503, each under 6 s, row count stays 1; after recovery `/ready` 200 and the pre-outage task is listed; silent listener covers the hanging case |
| AC-002.6 | met | `::test_title_errors_carry_rule_ids` (6 cases) | `api.py:31` (`title-min`/`title-max`), `api.py:61` (`missing` → `title-required`), `main.py:46` (handler registered) | asserts 422, `loc == ["body","title"]`, `input` present, `type` = rule id, `msg` = contract text, `GET /tasks == []` |

## Non-goals

The spec lists none. No website code and no new environment variable were added (`DATABASE_URL` only, as the spec requires). No template-owned layout touched. ✔

## Deviations from the plan

- `tests/conftest.py`, `tests/test_persistence_acceptance.py`, `tests/test_smoke_tasks.py`, `tests/test_tasks_acceptance.py` are in no task's `files`: the red-phase acceptance tests and the shared DB fixture design.md prescribes; acceptable.
- `tests/test_tasks_acceptance.py` dropped `test_restart_empties_list` (AC-001.7), and `docs/specs/001-.../spec.md` strikes AC-001.7 as superseded by AC-002.1 with a changelog line; acceptable, because the spec records the replacement (AC-002.1 "replaces AC-001.7"). The AC-001.6 test now fills via SQL; it asserts the same outcome.
- `contract/001-persistent-tasks-and-web-task-list.json`, `docs/adr/001-postgres-task-storage.md`, `docs/adr/README.md`, `docs/backlog.md`, `.secrets.baseline.json`: spec, contract copy and generated or housekeeping files; acceptable. `docs/backlog.md` still shows 002 as `approved` (generated index, stale); cosmetic.
- All tasks t1 to t3 are `done: true`. Contract matches `design.md` (`/ready` 200 `{"status":"ready"}` / 503 `{"status":"unavailable"}`, 503/409/422 bodies). ✔

## Smoke

- `tests/test_smoke_tasks.py::test_smoke_ready_reflects_database` also passes against the base code (`/ready` returned `{"status": "ready"}` unconditionally before), so it does not show that readiness depends on the database.

**Result:** pass

## Mutation check (report only)

10 of 20 mutants tested in 90 s (time budget of 90 s, `--budget`); the score covers the tested ones.

8 of 10 mutants of the changed code were caught by the acceptance tests (80 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard27_api/tasks/store.py:14 3 → 4`
- `src/taskboard27_api/tasks/store.py:15 3000 → 3001`
