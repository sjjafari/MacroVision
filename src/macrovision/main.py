from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from macrovision.api import router, system_router
from macrovision.decision_api import router as decision_router
from macrovision.macro_data_api import router as macro_data_router
from macrovision.portfolio_api import router as portfolio_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Schema creation is intentionally migration-owned; run `alembic upgrade head`.
    yield


app = FastAPI(
    title="MacroVision API",
    version="0.4.0",
    description=(
        "Investment Decision Intelligence Platform for hypothesis-driven research, "
        "risk budgeting, and evidence-based learning. It does not provide trading signals."
    ),
    lifespan=lifespan,
)
app.include_router(system_router)
app.include_router(router, prefix="/api/v1")
app.include_router(portfolio_router, prefix="/api/v1")
app.include_router(decision_router, prefix="/api/v1")
app.include_router(macro_data_router, prefix="/api/v1")
