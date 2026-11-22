"""HTTP endpoints for creating and listing tasks."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Final

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, StrictStr, field_validator
from pydantic_core import PydanticCustomError

from .store import MAX_TASKS, TaskLimitReached, TaskStore, get_task_store

logger = structlog.get_logger()

MAX_TITLE_LENGTH = 200
TITLE_MESSAGE: Final = "Enter a title of 1 to 200 characters"
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


class TaskCreate(BaseModel):
    title: StrictStr
    due_date: str | None = None

    @field_validator("title")
    @classmethod
    def _check_title(cls, value: str) -> str:
        value = value.strip()
        if len(value) == 0:
            raise PydanticCustomError("title-min", TITLE_MESSAGE)
        if len(value) > MAX_TITLE_LENGTH:
            raise PydanticCustomError("title-max", TITLE_MESSAGE)
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


async def title_required_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 in the standard body; a missing title carries the contract rule id."""
    errors = []
    for error in exc.errors():
        if error.get("type") == "missing" and tuple(error.get("loc", ())) == ("body", "title"):
            error = {**error, "type": "title-required", "msg": TITLE_MESSAGE}
        errors.append(error)
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


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
