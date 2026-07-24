from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError

from macrovision.api import router, system_router
from macrovision.contracts import ErrorResponse
from macrovision.decision_api import router as decision_router
from macrovision.errors import (
    http_error_handler,
    integrity_error_handler,
    provider_error_handler,
    validation_error_handler,
)
from macrovision.integrity import IntegrityConflictError
from macrovision.macro_data_api import router as macro_data_router
from macrovision.portfolio_api import router as portfolio_router
from macrovision.provider_api import router as provider_router
from macrovision.provider_contracts import ProviderError


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Schema creation is intentionally migration-owned; run `alembic upgrade head`.
    yield


app = FastAPI(
    title="MacroVision API",
    version="0.5.0",
    description=(
        "Investment Decision Intelligence Platform for hypothesis-driven research, "
        "risk budgeting, and evidence-based learning. It does not provide trading signals."
    ),
    lifespan=lifespan,
    responses={
        404: {"model": ErrorResponse, "description": "Resource not found"},
        409: {"model": ErrorResponse, "description": "Domain or concurrency conflict"},
        422: {"model": ErrorResponse, "description": "Request validation failed"},
    },
)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(IntegrityConflictError, integrity_error_handler)
app.add_exception_handler(ProviderError, provider_error_handler)
app.include_router(system_router)
app.include_router(router, prefix="/api/v1")
app.include_router(portfolio_router, prefix="/api/v1")
app.include_router(decision_router, prefix="/api/v1")
app.include_router(macro_data_router, prefix="/api/v1")
app.include_router(provider_router, prefix="/api/v1")
