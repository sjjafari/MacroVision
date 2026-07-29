"""Private dashboard read endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from macrovision import dashboard_schemas as schemas
from macrovision import dashboard_services as services
from macrovision.database import get_db

router = APIRouter(tags=["private dashboards"])
DbSession = Annotated[Session, Depends(get_db)]


def _not_found(exc: services.DashboardNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


@router.get("/dashboards", response_model=list[schemas.DashboardDefinition])
def list_dashboards() -> tuple[schemas.DashboardDefinition, ...]:
    return services.list_dashboards()


@router.get(
    "/dashboards/{dashboard_code}/summary",
    response_model=schemas.DashboardSummary,
)
def dashboard_summary(dashboard_code: str, session: DbSession) -> schemas.DashboardSummary:
    try:
        return services.dashboard_summary(session, dashboard_code)
    except services.DashboardNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get(
    "/dashboards/{dashboard_code}",
    response_model=schemas.DashboardDefinition,
)
def get_dashboard(dashboard_code: str) -> schemas.DashboardDefinition:
    try:
        return services.get_dashboard(dashboard_code)
    except services.DashboardNotFoundError as exc:
        raise _not_found(exc) from exc
