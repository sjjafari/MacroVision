from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from macrovision import schemas, services
from macrovision.database import get_db
from macrovision.integrity import IntegrityConflictError

router = APIRouter()
system_router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


@system_router.get("/health", tags=["system"])
@router.get("/health", include_in_schema=False)
def health(session: DbSession) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}


@router.post(
    "/investors",
    response_model=schemas.InvestorProfileRead,
    status_code=status.HTTP_201_CREATED,
    tags=["investor profiles"],
)
def create_investor(
    payload: schemas.InvestorProfileCreate, session: DbSession
) -> schemas.InvestorProfileRead:
    return schemas.InvestorProfileRead.model_validate(
        services.create_investor_profile(session, payload)
    )


@router.get(
    "/investors/{profile_id}",
    response_model=schemas.InvestorProfileRead,
    tags=["investor profiles"],
)
def get_investor(profile_id: int, session: DbSession) -> schemas.InvestorProfileRead:
    try:
        return schemas.InvestorProfileRead.model_validate(
            services.get_investor_profile(session, profile_id)
        )
    except services.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/journals",
    response_model=schemas.JournalRead,
    status_code=status.HTTP_201_CREATED,
    tags=["research journals"],
    deprecated=True,
)
def create_journal(payload: schemas.JournalCreate, session: DbSession) -> schemas.JournalRead:
    try:
        return schemas.JournalRead.model_validate(services.create_journal(session, payload))
    except services.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/journals/{journal_id}",
    response_model=schemas.JournalRead,
    tags=["research journals"],
    deprecated=True,
)
def get_journal(journal_id: int, session: DbSession) -> schemas.JournalRead:
    try:
        return schemas.JournalRead.model_validate(services.get_journal(session, journal_id))
    except services.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/journals/{journal_id}/close",
    response_model=schemas.JournalRead,
    tags=["research journals"],
    deprecated=True,
)
def close_journal(
    journal_id: int, payload: schemas.JournalClose, session: DbSession
) -> schemas.JournalRead:
    try:
        return schemas.JournalRead.model_validate(
            services.close_journal(session, journal_id, payload)
        )
    except services.NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (services.JournalConflictError, IntegrityConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
