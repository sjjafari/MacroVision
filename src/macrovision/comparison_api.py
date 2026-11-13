"""Private read-only comparison API for Web MVP Phase 4."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from macrovision import analytics_management_services as analytics
from macrovision import macro_data_services as macro
from macrovision.comparison_schemas import ComparisonRead
from macrovision.comparison_services import ComparisonError, parse_selections, read_comparison
from macrovision.database import get_db

router = APIRouter(tags=["comparison"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/comparison", response_model=ComparisonRead)
def comparison(
    session: DbSession,
    items: Annotated[str, Query(min_length=5, max_length=200)],
    start: datetime,
    end: datetime,
    as_of: datetime | None = None,
) -> ComparisonRead:
    try:
        return read_comparison(
            session,
            selections=parse_selections(items),
            start=start,
            end=end,
            as_of=as_of,
        )
    except (ComparisonError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (macro.DataNotFoundError, analytics.AnalyticsNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="comparison resource was not found") from exc
