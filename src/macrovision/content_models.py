from datetime import datetime

from sqlalchemy import CheckConstraint, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from macrovision.database import Base
from macrovision.persistence_types import UTCDateTime


class EditorialArticle(Base):
    __tablename__ = "editorial_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(160), unique=True)
    title_fa: Mapped[str] = mapped_column(String(240))
    dek_fa: Mapped[str] = mapped_column(String(500))
    body_fa: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80))
    author_display_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(16), default="draft")
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("LENGTH(slug) BETWEEN 1 AND 160", name="ck_editorial_article_slug"),
        CheckConstraint("LENGTH(title_fa) BETWEEN 1 AND 240", name="ck_editorial_article_title"),
        CheckConstraint("LENGTH(dek_fa) BETWEEN 1 AND 500", name="ck_editorial_article_dek"),
        CheckConstraint("LENGTH(body_fa) BETWEEN 1 AND 50000", name="ck_editorial_article_body"),
        CheckConstraint("LENGTH(category) BETWEEN 1 AND 80", name="ck_editorial_article_category"),
        CheckConstraint(
            "LENGTH(author_display_name) BETWEEN 1 AND 120",
            name="ck_editorial_article_author",
        ),
        CheckConstraint(
            "status IN ('draft','published','archived')",
            name="ck_editorial_article_status",
        ),
        CheckConstraint(
            "(status = 'published' AND published_at IS NOT NULL) OR status <> 'published'",
            name="ck_editorial_article_publication",
        ),
        Index("ix_editorial_article_status_published", "status", "published_at", "id"),
    )


class NewsletterSubscriber(Base):
    __tablename__ = "newsletter_subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    unsubscribe_token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    consented_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    unsubscribed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("LENGTH(email) BETWEEN 3 AND 320", name="ck_newsletter_email"),
        CheckConstraint(
            "status IN ('active','unsubscribed')",
            name="ck_newsletter_status",
        ),
        CheckConstraint(
            "LENGTH(unsubscribe_token_hash) = 64",
            name="ck_newsletter_token_hash",
        ),
        Index("ix_newsletter_status_created", "status", "created_at", "id"),
    )
