"""Add editorial content and newsletter subscriptions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261113_0010"
down_revision: str | None = "20260726_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "editorial_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title_fa", sa.String(length=240), nullable=False),
        sa.Column("dek_fa", sa.String(length=500), nullable=False),
        sa.Column("body_fa", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("author_display_name", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("LENGTH(slug) BETWEEN 1 AND 160", name="ck_editorial_article_slug"),
        sa.CheckConstraint("LENGTH(title_fa) BETWEEN 1 AND 240", name="ck_editorial_article_title"),
        sa.CheckConstraint("LENGTH(dek_fa) BETWEEN 1 AND 500", name="ck_editorial_article_dek"),
        sa.CheckConstraint("LENGTH(body_fa) BETWEEN 1 AND 50000", name="ck_editorial_article_body"),
        sa.CheckConstraint(
            "LENGTH(category) BETWEEN 1 AND 80", name="ck_editorial_article_category"
        ),
        sa.CheckConstraint(
            "LENGTH(author_display_name) BETWEEN 1 AND 120", name="ck_editorial_article_author"
        ),
        sa.CheckConstraint(
            "status IN ('draft','published','archived')", name="ck_editorial_article_status"
        ),
        sa.CheckConstraint(
            "(status = 'published' AND published_at IS NOT NULL) OR status <> 'published'",
            name="ck_editorial_article_publication",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        "ix_editorial_article_status_published",
        "editorial_articles",
        ["status", "published_at", "id"],
    )
    op.create_table(
        "newsletter_subscribers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("unsubscribe_token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "consented_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("LENGTH(email) BETWEEN 3 AND 320", name="ck_newsletter_email"),
        sa.CheckConstraint("status IN ('active','unsubscribed')", name="ck_newsletter_status"),
        sa.CheckConstraint("LENGTH(unsubscribe_token_hash) = 64", name="ck_newsletter_token_hash"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("unsubscribe_token_hash"),
    )
    op.create_index(
        "ix_newsletter_status_created", "newsletter_subscribers", ["status", "created_at", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_newsletter_status_created", table_name="newsletter_subscribers")
    op.drop_table("newsletter_subscribers")
    op.drop_index("ix_editorial_article_status_published", table_name="editorial_articles")
    op.drop_table("editorial_articles")
