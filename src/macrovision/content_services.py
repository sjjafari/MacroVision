import hashlib
import re
import secrets
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from macrovision.content_models import EditorialArticle, NewsletterSubscriber
from macrovision.content_schemas import (
    ArticleCreate,
    ArticleRead,
    PublicArticlePage,
    PublicArticleRead,
    SubscriptionReceipt,
    UnsubscribeReceipt,
)

_EMAIL = re.compile(r"^[^\s@]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}$")


class ContentConflictError(Exception):
    pass


class ContentNotFoundError(Exception):
    pass


class InvalidSubscriptionError(Exception):
    pass


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(UTC)


def create_article(session: Session, payload: ArticleCreate) -> ArticleRead:
    article = EditorialArticle(**payload.model_dump(), status="draft")
    session.add(article)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ContentConflictError("article slug already exists") from exc
    session.refresh(article)
    return ArticleRead.model_validate(article, from_attributes=True)


def publish_article(session: Session, article_id: int, published_at: datetime) -> ArticleRead:
    article = session.get(EditorialArticle, article_id)
    if article is None:
        raise ContentNotFoundError("article was not found")
    article.status = "published"
    article.published_at = _aware(published_at)
    session.commit()
    session.refresh(article)
    return ArticleRead.model_validate(article, from_attributes=True)


def list_public_articles(
    session: Session, *, limit: int, offset: int, category: str | None = None
) -> PublicArticlePage:
    now = datetime.now(UTC)
    filters = [
        EditorialArticle.status == "published",
        EditorialArticle.published_at.is_not(None),
        EditorialArticle.published_at <= now,
    ]
    if category is not None:
        filters.append(EditorialArticle.category == category.strip())
    total = session.scalar(select(func.count(EditorialArticle.id)).where(*filters)) or 0
    rows = list(
        session.scalars(
            select(EditorialArticle)
            .where(*filters)
            .order_by(EditorialArticle.published_at.desc(), EditorialArticle.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return PublicArticlePage(
        limit=limit,
        offset=offset,
        total=total,
        items=[
            PublicArticleRead(
                slug=item.slug,
                title_fa=item.title_fa,
                dek_fa=item.dek_fa,
                body_fa=item.body_fa,
                category=item.category,
                author_display_name=item.author_display_name,
                published_at=item.published_at,
            )
            for item in rows
            if item.published_at is not None
        ],
    )


def get_public_article(session: Session, slug: str) -> PublicArticleRead:
    now = datetime.now(UTC)
    article = session.scalar(
        select(EditorialArticle).where(
            EditorialArticle.slug == slug,
            EditorialArticle.status == "published",
            EditorialArticle.published_at.is_not(None),
            EditorialArticle.published_at <= now,
        )
    )
    if article is None or article.published_at is None:
        raise ContentNotFoundError("article was not found")
    return PublicArticleRead(
        slug=article.slug,
        title_fa=article.title_fa,
        dek_fa=article.dek_fa,
        body_fa=article.body_fa,
        category=article.category,
        author_display_name=article.author_display_name,
        published_at=article.published_at,
    )


def _normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if not _EMAIL.fullmatch(normalized):
        raise InvalidSubscriptionError("email address is invalid")
    return normalized


def subscribe(session: Session, email: str) -> SubscriptionReceipt:
    normalized = _normalize_email(email)
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    existing = session.scalar(
        select(NewsletterSubscriber).where(NewsletterSubscriber.email == normalized)
    )
    if existing is None:
        session.add(
            NewsletterSubscriber(
                email=normalized,
                status="active",
                unsubscribe_token_hash=digest,
                consented_at=datetime.now(UTC),
            )
        )
    else:
        existing.status = "active"
        existing.unsubscribe_token_hash = digest
        existing.consented_at = datetime.now(UTC)
        existing.unsubscribed_at = None
    session.commit()
    return SubscriptionReceipt(status="active", unsubscribe_token=token)


def unsubscribe(session: Session, token: str) -> UnsubscribeReceipt:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    subscriber = session.scalar(
        select(NewsletterSubscriber).where(NewsletterSubscriber.unsubscribe_token_hash == digest)
    )
    if subscriber is not None:
        subscriber.status = "unsubscribed"
        subscriber.unsubscribed_at = datetime.now(UTC)
        session.commit()
    return UnsubscribeReceipt(status="unsubscribed")
