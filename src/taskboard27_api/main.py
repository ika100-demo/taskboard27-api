"""FastAPI entry point for taskboard27-api."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from . import __version__
from .logging_config import configure_logging
from .metrics import MetricsMiddleware
from .tasks import StorageUnavailable, TaskStore, get_task_store
from .tasks import router as tasks_router
from .tasks.api import title_required_handler
from .tracing import configure_tracing, tracing_enabled

configure_logging(level=os.environ.get("LOG_LEVEL", "INFO"))
if tracing_enabled():
    configure_tracing()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Create the schema at startup; an unreachable database must not stop the service."""
    try:
        await run_in_threadpool(get_task_store().ensure_schema)
    except StorageUnavailable:
        pass  # the store logged it; /ready reports 503 until the database is back
    yield


app = FastAPI(title="taskboard27-api", version=__version__, lifespan=lifespan)
app.add_middleware(MetricsMiddleware)
if tracing_enabled():
    FastAPIInstrumentor.instrument_app(app)
app.include_router(tasks_router)
app.add_exception_handler(RequestValidationError, title_required_handler)  # type: ignore[arg-type]


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — returns 200 as long as the process is responding."""
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
def ready(store: Annotated[TaskStore, Depends(get_task_store)]) -> HealthResponse | JSONResponse:
    """Readiness probe — 200 when the database answers, 503 otherwise."""
    try:
        store.ping()
    except StorageUnavailable:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return HealthResponse(status="ready")


@app.get("/ping")
def ping() -> dict[str, str]:
    """Simple ping endpoint."""
    return {"pong": "taskboard27-api"}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus scrape endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
