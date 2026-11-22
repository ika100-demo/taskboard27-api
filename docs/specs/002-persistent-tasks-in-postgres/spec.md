---
spec_id: 002-persistent-tasks-in-postgres
title: Persistent tasks in Postgres
status: done
priority: P1
shape: service-python
parent: ika100-demo/taskboard27-gitops:001-persistent-tasks-and-web-task-list
---

# 002 — Persistent tasks in Postgres

## Problem

The Task API keeps tasks only in its process memory today, so every restart or redeploy empties the board, and two running instances would each show different tasks. On top of that, the only way to see or add a task is to call the API by hand; the website shows no tasks at all. People who want to use taskboard27 to note what they have to do lose their tasks and have no screen to work on. Keeping tasks in a Postgres database and giving the website a task list with a create form makes the board usable by people, not only by API clients.

## System context

Slice of the system plan `001-persistent-tasks-and-web-task-list` in `ika100-demo/taskboard27-gitops` for `taskboard27-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given tasks A, B and C were created through `POST /tasks`, when the API is restarted or redeployed with a new version, then `GET /tasks` returns `200` with exactly A, B and C, oldest first, each with the same `id`, `title` and `due_date` as returned at creation.
- **AC-001.2** Given the API runs with 2 instances, when a task is created through `POST /tasks`, then each of 10 consecutive `GET /tasks` requests that follow includes that task, whichever instance answers.
- **AC-001.3** Given the task database is unreachable, when a client sends `POST /tasks` or `GET /tasks`, then the response is `503` with the message `"task storage unavailable"`, no task is created, and `/ready` answers a non-`200` status; given the database is reachable again, then `GET /tasks` returns every task stored before the outage.
- **AC-001.4** Given 1000 tasks are stored, when a client sends another valid `POST /tasks`, including after a restart of the API, then the response is `409` with the message `"task limit of 1000 reached"` and the list still holds 1000 tasks.
- **AC-001.7** Given the website's start page is open, when a person submits the form with an empty title, a title of only spaces, or a title longer than 200 characters after trimming, then the text `Enter a title of 1 to 200 characters` appears at the title field, the entered values stay in the form, and no task is created.

### Contract

No authentication (A8). JSON in and out, `Content-Type: application/json`. Provider: `taskboard27-api`; consumer: `taskboard27-web`, which calls it server-side at `${TASKBOARD27_API_URL}` (`http://taskboard27-api` in the cluster).

**Task object** (every task in a response): `{"id": string (UUID), "title": string (trimmed, 1..200 characters), "due_date": "YYYY-MM-DD" | null}`. No other fields.

**`POST /tasks`**

Request body (object; unknown fields ignored):

| Field | Type | Rules |
|---|---|---|
| `title` | string, required | trimmed; after trimming 1..200 characters; stored trimmed |
| `due_date` | string or null, optional (default `null`) | exactly `YYYY-MM-DD` and a real calendar date; past dates accepted |

Responses:

- `201` → the created Task object; it is stored and every instance lists it from then on.
- `422` → validation failed, nothing stored. FastAPI's standard body: `{"detail": [{"type": string, "loc": ["body", "<field>"], "msg": string, "input": any}]}`. For the title rules below, `type` is the rule id (`title-required`, `title-min`, `title-max`) and `msg` is `"Enter a title of 1 to 200 characters"`. A title that is not a string, and every `due_date` failure, keep pydantic's own `type`/`msg`. Validation runs before the limit and storage checks.
- `409` → `{"detail": "task limit of 1000 reached"}`: 1000 tasks are already stored; nothing stored. The limit holds across instances (the count and the insert are serialised in the database).
- `503` → `{"detail": "task storage unavailable"}`: the database cannot be reached or does not answer in time; nothing stored.

**`GET /tasks`**

- `200` → JSON array of every stored Task object, oldest first (creation order, stable across instances and restarts); `[]` when none. Unpaginated, at most 1000 entries.
- `503` → `{"detail": "task storage unavailable"}`.

**`GET /ready`** → `200` when the database answers a trivial query, else `503` (the pod leaves the Service until it is reachable again). **`GET /health`** stays `200` while the process runs, independent of the database, so an outage does not restart pods.

**Website start page** (`GET /` on taskboard27-web): form above the list; title field, date input (`type="date"`, sends `YYYY-MM-DD` or `null`), button `Add task`; texts exactly as in A9.

### Rules

```yaml
rules:
  - id: title-required
    endpoint: POST /tasks
    field: title
    kind: required
    value: true
    provider: taskboard27-api
    consumers: [taskboard27-web]
  - id: title-min
    endpoint: POST /tasks
    field: title
    kind: min_length
    value: 1
    provider: taskboard27-api
    consumers: [taskboard27-web]
  - id: title-max
    endpoint: POST /tasks
    field: title
    kind: max_length
    value: 200
    provider: taskboard27-api
    consumers: [taskboard27-web]
```

Prose rules no tool checks: lengths count characters after trimming surrounding whitespace, so a title of only spaces violates `title-min`; `due_date` is a calendar date `YYYY-MM-DD` or `null`, which the website guarantees by its date input (A7), and the API keeps rejecting anything else with `422` on `due_date`.

### Errors

```yaml
errors:
  status: 422
  body:
    list: detail
    field: loc
    rule: type
    message: msg
  unlisted:
    message: "The task could not be saved. Try again."
```

`loc` is a path (`["body", "title"]`); a caller matches it by its last element. The website treats responses as follows: `422` with a `detail` item whose `loc` ends in `title` shows that item's `msg` at the title field; `409` shows `Task limit of 1000 reached.` on the form; every other answer of `POST /tasks` (`503`, `500`, a `422` without a title item, a body that is not JSON, any unlisted status) shows `The task could not be saved. Try again.` on the form. For `GET /tasks`, anything but `200` with a JSON array shows `Tasks could not be loaded. Try again later.` in the list area. In every failure case the entered form values stay.

### Timeouts

- Website → `GET /tasks` and `POST /tasks`: 5 seconds per call (connect plus response), no retry. On timeout or connection failure the website shows the load message (list) or the save message (form), as for any unlisted answer. A `POST` that timed out may still have been stored; the person sees it after a reload (no retry, so no duplicate is created by the website).
- API → Postgres: connect timeout 3 seconds, statement timeout 3 seconds; on either the request is answered `503 "task storage unavailable"`, so the API answers well inside the website's 5 seconds (within 6 seconds in the worst case of connect plus statement). `/ready` uses the same limits. When the database comes back, the next request reconnects; no restart of the API is needed.
- Website when the API is down or slow: the start page still renders (form plus load message) within about 5 seconds; `/api/ready` of the website does not depend on the API.

### Contract rules

Copy: `contract/001-persistent-tasks-and-web-task-list.json`, from plan `001-persistent-tasks-and-web-task-list` at `ika100-demo/taskboard27-gitops@805e05a`. The repo's contract check reads it.

| Rule | Endpoint | Field | Kind | Value | Status | Role |
|---|---|---|---|---|---|---|
| title-max | POST /tasks | title | max_length | 200 | 422 | provider |
| title-min | POST /tasks | title | min_length | 1 | 422 | provider |
| title-required | POST /tasks | title | required | True | 422 | provider |

Errors: status 422; body `detail[]` of objects with `loc`, `type`, `msg`; responses the contract does not list: show "The task could not be saved. Try again.".

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`
- replicas `2` in `dev`

### Notes for this repo

Keep POST/GET /tasks, the task fields, the due_date validation and its 422 exactly as spec 001 built them (A1);
only where tasks are kept and the title errors' `type`/`msg` values change (see the plan's Contract).
Connection settings come from DATABASE_URL (injected by the gitops `uses: postgres`); no new env var.

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given tasks A, B and C were created through `POST /tasks`, when the service is restarted (or a new version started) against the same database, then `GET /tasks` returns `200` with exactly A, B and C, oldest first, each with the same `id`, `title` and `due_date` as returned at creation (system AC-001.1) (replaces AC-001.7)
- **AC-002.2** Given an empty database reached through `DATABASE_URL`, when the service starts, then it creates its own schema without a manual step and `GET /tasks` returns `200` with `[]`; starting again against an existing schema keeps every stored task (system AC-001.1)
- **AC-002.3** Given two service processes connected to the same database, when a task is created through `POST /tasks` on one, then each following `GET /tasks` on either process includes that task (system AC-001.2)
- **AC-002.4** Given 1000 tasks are stored, when a client sends another valid `POST /tasks`, also after a restart and also when two processes receive valid `POST /tasks` at the same time while 999 are stored, then every request beyond the 1000th is answered `409` with `{"detail": "task limit of 1000 reached"}` and `GET /tasks` returns exactly 1000 tasks (system AC-001.4)
- **AC-002.5** Given the database is unreachable, when a client sends `POST /tasks` or `GET /tasks`, then the response arrives within 6 seconds as `503` with `{"detail": "task storage unavailable"}`, no task is stored, and `GET /ready` answers `503`; given the database is reachable again, then `GET /ready` answers `200` and `GET /tasks` returns every task stored before the outage (system AC-001.3)
- **AC-002.6** Given a running service, when a client sends `POST /tasks` with the title missing, empty or only whitespace after trimming, or longer than 200 characters after trimming, then the response is `422` in the standard body `{"detail": [{"type", "loc", "msg", "input"}]}` with an item whose `loc` ends in `"title"`, whose `type` is the contract rule id (`title-required`, `title-min` or `title-max`) and whose `msg` is non-empty, and no task is stored (system AC-001.7)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

<!-- Priority levels (spec 196) for the product-manager's PRIORITY line: P0 an outage, data loss, a security problem, or something that blocks all other work; P1 a normal bug or feature; the fallback when nothing signals urgency; P2 cosmetic, a convenience, or something with an easy workaround. A reason is "P<n>: <phrase>", one of: P0: outage, data loss, security problem, blocks all other work; P1: normal bug or feature; P2: cosmetic, convenience, easy workaround. -->

## Changelog

- 2026-11-22 created from the system plan, with its criteria (spec 147)
- 2026-11-22 approved
- 2026-11-22 building
- 2026-11-22 done
