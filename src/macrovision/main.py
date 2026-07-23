from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from macrovision.api import router, system_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Schema creation is intentionally migration-owned; run `alembic upgrade head`.
    yield


app = FastAPI(
    title="MacroVision API",
    version="0.1.0",
    description=(
        "Investment Decision Intelligence Platform for hypothesis-driven research, "
        "risk budgeting, and evidence-based learning. It does not provide trading signals."
    ),
    lifespan=lifespan,
)
app.include_router(system_router)
app.include_router(router, prefix="/api/v1")
