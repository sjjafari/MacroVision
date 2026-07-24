import re
from collections.abc import Generator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from macrovision.config import get_settings
from macrovision.contracts import ErrorResponse
from macrovision.database import get_db
from macrovision.fred_provider import FREDProvider
from macrovision.macro_data_services import DataConflictError
from macrovision.provider_contracts import ExternalDataProvider
from macrovision.provider_schemas import FREDSeriesSyncRequest, ProviderSyncResult
from macrovision.provider_services import synchronize_provider_series

router = APIRouter(prefix="/providers", tags=["providers"])
DbSession = Annotated[Session, Depends(get_db)]


def get_fred_provider() -> Generator[ExternalDataProvider, None, None]:
    provider = FREDProvider(get_settings())
    try:
        yield provider
    finally:
        provider.close()


FredProvider = Annotated[ExternalDataProvider, Depends(get_fred_provider)]


@router.post(
    "/fred/series/{fred_series_id}/sync",
    response_model=ProviderSyncResult,
    responses={
        404: {"model": ErrorResponse, "description": "FRED series not found"},
        409: {"model": ErrorResponse, "description": "Synchronization conflict"},
        422: {"model": ErrorResponse, "description": "Invalid request or unsupported metadata"},
        429: {"model": ErrorResponse, "description": "FRED rate limit exhausted"},
        502: {"model": ErrorResponse, "description": "Invalid FRED response"},
        503: {"model": ErrorResponse, "description": "Provider unavailable or unconfigured"},
        504: {"model": ErrorResponse, "description": "Provider timeout"},
    },
)
def synchronize_fred(
    fred_series_id: str,
    payload: FREDSeriesSyncRequest,
    session: DbSession,
    provider: FredProvider,
) -> ProviderSyncResult:
    if (
        not fred_series_id
        or len(fred_series_id) > 120
        or re.fullmatch(r"[A-Za-z0-9_.-]+", fred_series_id) is None
    ):
        raise HTTPException(status_code=422, detail="Invalid FRED series ID")
    try:
        return synchronize_provider_series(session, provider, fred_series_id, payload)
    except DataConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
