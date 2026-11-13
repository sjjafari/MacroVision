from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from macrovision.content_schemas import (
    ArticleCreate,
    ArticlePublish,
    ArticleRead,
    PublicArticlePage,
    PublicArticleRead,
    SubscriptionCreate,
    SubscriptionReceipt,
    UnsubscribeReceipt,
    UnsubscribeRequest,
)
from macrovision.content_services import (
    ContentConflictError,
    ContentNotFoundError,
    InvalidSubscriptionError,
    create_article,
    get_public_article,
    list_public_articles,
    publish_article,
    subscribe,
    unsubscribe,
)
from macrovision.contracts import PageLimit, PageOffset
from macrovision.database import get_db

router = APIRouter(tags=["content platform"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("/public/content/articles", response_model=PublicArticlePage)
def public_articles(
    session: DbSession,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
    category: str | None = None,
) -> PublicArticlePage:
    if category is not None and not 1 <= len(category.strip()) <= 80:
        raise HTTPException(status_code=422, detail="category is invalid")
    return list_public_articles(session, limit=limit, offset=offset, category=category)


@router.get("/public/content/articles/{slug}", response_model=PublicArticleRead)
def public_article(slug: str, session: DbSession) -> PublicArticleRead:
    try:
        return get_public_article(session, slug)
    except ContentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/content/articles", response_model=ArticleRead, status_code=201)
def admin_create_article(payload: ArticleCreate, session: DbSession) -> ArticleRead:
    try:
        return create_article(session, payload)
    except ContentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/content/articles/{article_id}/publish", response_model=ArticleRead)
def admin_publish_article(
    article_id: int, payload: ArticlePublish, session: DbSession
) -> ArticleRead:
    try:
        return publish_article(session, article_id, payload.published_at)
    except ContentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/public/subscriptions", response_model=SubscriptionReceipt, status_code=201)
def create_subscription(payload: SubscriptionCreate, session: DbSession) -> SubscriptionReceipt:
    try:
        return subscribe(session, payload.email)
    except InvalidSubscriptionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/public/subscriptions/unsubscribe", response_model=UnsubscribeReceipt)
def cancel_subscription(payload: UnsubscribeRequest, session: DbSession) -> UnsubscribeReceipt:
    return unsubscribe(session, payload.token)
