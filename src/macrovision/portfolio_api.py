from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from macrovision import portfolio_schemas as schemas
from macrovision import portfolio_services as services
from macrovision.contracts import PageLimit, PageOffset
from macrovision.database import get_db
from macrovision.integrity import IntegrityConflictError

router = APIRouter(prefix="/portfolios", tags=["portfolios"])
DbSession = Annotated[Session, Depends(get_db)]


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, services.PortfolioNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.post("", response_model=schemas.PortfolioRead, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: schemas.PortfolioCreate, session: DbSession) -> schemas.PortfolioRead:
    try:
        return services.portfolio_to_read(services.create_portfolio(session, payload))
    except services.PortfolioNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("", response_model=list[schemas.PortfolioRead])
def list_portfolios(
    session: DbSession, limit: PageLimit = 100, offset: PageOffset = 0
) -> list[schemas.PortfolioRead]:
    return [
        services.portfolio_to_read(portfolio)
        for portfolio in services.list_portfolios(session, limit=limit, offset=offset)
    ]


@router.get("/{portfolio_id}", response_model=schemas.PortfolioRead)
def get_portfolio(portfolio_id: int, session: DbSession) -> schemas.PortfolioRead:
    try:
        return services.portfolio_to_read(services.get_portfolio(session, portfolio_id))
    except services.PortfolioNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{portfolio_id}/transactions",
    response_model=schemas.TransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def record_transaction(
    portfolio_id: int, payload: schemas.TransactionCreate, session: DbSession
) -> schemas.TransactionRead:
    try:
        return schemas.TransactionRead.model_validate(
            services.record_transaction(session, portfolio_id, payload)
        )
    except (
        services.PortfolioNotFoundError,
        services.PortfolioDomainError,
        IntegrityConflictError,
    ) as exc:
        raise _http_error(exc) from exc


@router.get("/{portfolio_id}/transactions", response_model=list[schemas.TransactionRead])
def list_transactions(
    portfolio_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> list[schemas.TransactionRead]:
    try:
        return [
            schemas.TransactionRead.model_validate(transaction)
            for transaction in services.list_transactions(
                session, portfolio_id, limit=limit, offset=offset
            )
        ]
    except (services.PortfolioNotFoundError, IntegrityConflictError) as exc:
        raise _http_error(exc) from exc


@router.put(
    "/{portfolio_id}/positions/{position_id}/price",
    response_model=schemas.PortfolioRead,
)
def update_position_price(
    portfolio_id: int,
    position_id: int,
    payload: schemas.PositionPriceUpdate,
    session: DbSession,
) -> schemas.PortfolioRead:
    try:
        return services.portfolio_to_read(
            services.update_position_price(
                session, portfolio_id, position_id, payload.current_price
            )
        )
    except services.PortfolioNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/{portfolio_id}/summary", response_model=schemas.PortfolioSummary)
def get_summary(portfolio_id: int, session: DbSession) -> schemas.PortfolioSummary:
    try:
        return services.portfolio_summary(services.get_portfolio(session, portfolio_id))
    except services.PortfolioNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post(
    "/{portfolio_id}/snapshots",
    response_model=schemas.SnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_snapshot(portfolio_id: int, session: DbSession) -> schemas.SnapshotRead:
    try:
        return services.snapshot_to_read(services.create_snapshot(session, portfolio_id))
    except services.PortfolioNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/{portfolio_id}/snapshots", response_model=list[schemas.SnapshotRead])
def list_snapshots(
    portfolio_id: int,
    session: DbSession,
    limit: PageLimit = 100,
    offset: PageOffset = 0,
) -> list[schemas.SnapshotRead]:
    try:
        return [
            services.snapshot_to_read(snapshot)
            for snapshot in services.list_snapshots(
                session, portfolio_id, limit=limit, offset=offset
            )
        ]
    except services.PortfolioNotFoundError as exc:
        raise _http_error(exc) from exc
