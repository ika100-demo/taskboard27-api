---
spec_id: 001-create-and-list-tasks-in-memory
title: Create and list tasks in memory
status: approved
priority: P1
shape: service-python
---

# 001 — Create and list tasks in memory

## Problem

The Task API offers only health, readiness and metrics endpoints today, so no client of taskboard27 can record or show a single task. Users who want to note what they have to do, and by when, have nowhere to put it. A first create-and-list capability, kept in the service's memory, makes the board usable end to end and gives later features (editing, completing, persistence) something to build on.

## Stories

As a taskboard user, I want to create a task with a title and, if I like, a due date, so that I can write down what I have to do.

As a taskboard user, I want to list all tasks I created, so that I can see what is open and when it is due.

## Acceptance criteria

- **AC-001.1** Given a running service, when a client sends `POST /tasks` with `{"title": "Buy milk", "due_date": "2026-12-01"}`, then the response is `201` with a JSON object holding a non-empty string `id`, `title` `"Buy milk"` and `due_date` `"2026-12-01"`. (smoke)
- **AC-001.2** Given a running service, when a client sends `POST /tasks` with only `{"title": "Call Anna"}` (or with `"due_date": null`), then the response is `201` and the returned task has `due_date` `null`.
- **AC-001.3** Given tasks created in the order A, B, C, when a client sends `GET /tasks`, then the response is `200` with a JSON array of exactly those three tasks, oldest first, each with `id`, `title` and `due_date` as returned at creation; with no tasks the array is `[]`. (smoke)
- **AC-001.4** Given a running service, when a client sends `POST /tasks` with the title missing, not a string, empty or only whitespace after trimming, or longer than 200 characters after trimming, then the response is `422` with an error naming the field `title`, and `GET /tasks` shows no new task; a title with surrounding spaces is stored trimmed (`"  Buy milk  "` becomes `"Buy milk"`).
- **AC-001.5** Given a running service, when a client sends `POST /tasks` with a `due_date` that is not a calendar date in `YYYY-MM-DD` form (for example `"tomorrow"`, `"2026-02-30"` or `"2026-12-01T10:00:00Z"`), then the response is `422` with an error naming the field `due_date`, and no task is created; a date in the past is accepted.
- **AC-001.6** Given 1000 tasks already held, when a client sends another valid `POST /tasks`, then the response is `409` with the message `"task limit of 1000 reached"` and the list still holds 1000 tasks.
- **AC-001.7** Given tasks were created, when the service process is restarted, then `GET /tasks` returns `[]`, because tasks live only in the service's memory.

## Non-goals

- Editing, completing or deleting tasks.
- Persistent storage of any kind; tasks are lost on restart or redeploy.
- Sharing tasks across several running instances of the service.
- Filtering, sorting options, search or pagination of the list.
- Users, ownership or per-user task lists.
- Authentication or authorization: the endpoints are open to anyone who can reach the service until a users/auth spec exists.

## Assumptions

- **A1** The endpoints are `POST /tasks` and `GET /tasks`, with JSON fields `id`, `title`, `due_date` (other option: `/api/tasks`, camelCase `dueDate`; affects AC-001.1, AC-001.2, AC-001.3).
- **A2** `id` is a server-generated opaque string (a UUID), unique per task (other option: increasing integers starting at 1, which repeat after a restart; affects AC-001.1).
- **A3** The due date is a calendar date `YYYY-MM-DD` without time or time zone, and past dates are allowed (other option: a full timestamp, or rejecting past dates; affects AC-001.5).
- **A4** The title is trimmed and must be 1 to 200 characters (other option: no upper limit, or 100 characters; affects AC-001.4).
- **A5** The list is returned oldest first, unpaginated (other option: newest first, or ordered by due date; affects AC-001.3).
- **A6** The service holds at most 1000 tasks and refuses more with `409`, so that memory cannot grow without bound (other option: no limit, or evict the oldest; affects AC-001.6).
- **A7** Invalid input answers `422` in the service's standard validation error format (other option: `400` with a custom body; affects AC-001.4, AC-001.5).
- **A8** `POST /tasks` and `GET /tasks` require no authentication; anyone who can reach the service may create and list all tasks, until a users/auth spec exists (other option: require a token now; affects AC-001.1, AC-001.3) (decided by the user 2026-11-22).

## Open questions

- ~~Anyone who can reach the service may create and list all tasks; there is no authentication. Is that acceptable for now? (suggested: yes, no authentication until a users spec exists; affects AC-001.1, AC-001.3)~~ Answered 2026-11-22: yes, open endpoints without authentication until a users/auth spec exists; folded into A8 and the Non-goals.

## Changelog

- 2026-11-22 created
- 2026-11-22 priority P1 proposed: P1: normal bug or feature
- 2026-11-22 amended: access question answered (no authentication for now), recorded as A8 and a non-goal
- 2026-11-22 approved
