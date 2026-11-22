"""Process-local, thread-safe in-memory task store."""

import threading
import uuid
from dataclasses import dataclass
from typing import Final

MAX_TASKS: Final = 1000


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    due_date: str | None  # "YYYY-MM-DD" or None


class TaskLimitReached(Exception):  # noqa: N818 - name fixed by design.md
    """Raised when the store already holds its maximum number of tasks."""


class TaskStore:
    def __init__(self, max_tasks: int = MAX_TASKS) -> None:
        self._max_tasks = max_tasks
        self._tasks: list[Task] = []
        self._lock = threading.Lock()

    def add(self, title: str, due_date: str | None) -> Task:
        task = Task(id=str(uuid.uuid4()), title=title, due_date=due_date)
        with self._lock:
            if len(self._tasks) >= self._max_tasks:
                raise TaskLimitReached
            self._tasks.append(task)
        return task

    def list(self) -> list[Task]:
        with self._lock:
            return list(self._tasks)

    def __len__(self) -> int:
        with self._lock:
            return len(self._tasks)


_store = TaskStore()


def get_task_store() -> TaskStore:
    return _store
