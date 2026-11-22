# ADR-001: Postgres task storage

**Status:** Proposed (2026-11-22)

## Context

Spec 002 makes tasks persistent: they must survive restarts and be the same on every replica (two in dev). The template ships no database stack, and ADR-000 asks for an ADR for any departure from it. The system already provides `DATABASE_URL` through the gitops `uses: postgres`. The spec bounds failure answers to 6 s and caps storage at 1000 tasks across all instances.

## Decision

Tasks are stored in Postgres via psycopg 3; the service creates its own schema at startup.

- One table `tasks`, read through `DATABASE_URL` only. Driver: `psycopg[binary]`; endpoints stay synchronous.
- One connection per operation, no pool, with a 3 s connect timeout and a 3 s statement timeout, so failures end within the spec's 6 s and the service reconnects by itself.
- The 1000-task limit is enforced in the database (advisory lock plus conditional insert), so it holds across instances and restarts.
- The schema is created with `CREATE TABLE IF NOT EXISTS` under an advisory lock, at startup and lazily on first use. No migration tool yet.

## Consequences

- Easier: tasks persist and are shared across replicas; no extra infrastructure beyond what gitops provides.
- Harder: tests need a Postgres server (devbox `postgresql` plus `pytest-postgresql`; `TEST_DATABASE_URL` for runners that run as root).
- A connect per request costs a few ms. A pool can be added later behind the `TaskStore` interface.
- The first spec that changes the schema must introduce a migration tool.
