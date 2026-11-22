"""HTTP endpoints for creating and listing tasks."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StrictStr, field_validator

from .store import MAX_TASKS, TaskLimitReached, TaskStore, get_task_store

logger = structlog.get_logger()

MAX_TITLE_LENGTH = 200
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class TaskCreate(BaseModel):
    title: StrictStr
    due_date: str | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= MAX_TITLE_LENGTH:
            raise ValueError(f"title must be 1 to {MAX_TITLE_LENGTH} characters")
        return value

    @field_validator("due_date")
    @classmethod
    def _check_due_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _DATE_PATTERN.fullmatch(value):
            raise ValueError("due_date must be YYYY-MM-DD")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("due_date must be a real calendar date") from exc
        return value


class TaskOut(BaseModel):
    id: str
    title: str
    due_date: str | None


router = APIRouter()
StoreDep = Annotated[TaskStore, Depends(get_task_store)]


@router.post("/tasks", status_code=201, response_model=TaskOut)
def create_task(body: TaskCreate, store: StoreDep) -> TaskOut:
    """Create a task; 409 once the store holds the maximum."""
    try:
        task = store.add(body.title, body.due_date)
    except TaskLimitReached:
        raise HTTPException(status_code=409, detail=f"task limit of {MAX_TASKS} reached") from None
    logger.info("task_created", task_id=task.id)
    return TaskOut(id=task.id, title=task.title, due_date=task.due_date)


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(store: StoreDep) -> list[TaskOut]:
    """List all tasks, oldest first."""
    return [TaskOut(id=t.id, title=t.title, due_date=t.due_date) for t in store.list()]
