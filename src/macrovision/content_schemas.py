from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated


class ContentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


Slug = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
Email = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=320)]


class ArticleCreate(ContentModel):
    slug: Slug
    title_fa: str = Field(min_length=1, max_length=240)
    dek_fa: str = Field(min_length=1, max_length=500)
    body_fa: str = Field(min_length=1, max_length=50000)
    category: str = Field(min_length=1, max_length=80)
    author_display_name: str = Field(min_length=1, max_length=120)


class ArticlePublish(ContentModel):
    published_at: datetime


class ArticleRead(ContentModel):
    id: int
    slug: str
    title_fa: str
    dek_fa: str
    body_fa: str
    category: str
    author_display_name: str
    status: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PublicArticleRead(ContentModel):
    slug: str
    title_fa: str
    dek_fa: str
    body_fa: str
    category: str
    author_display_name: str
    published_at: datetime


class PublicArticlePage(ContentModel):
    limit: int
    offset: int
    total: int
    items: list[PublicArticleRead]


class SubscriptionCreate(ContentModel):
    email: Email
    consent: Literal[True]


class SubscriptionReceipt(ContentModel):
    status: Literal["active"]
    unsubscribe_token: str = Field(min_length=32, max_length=128)


class UnsubscribeRequest(ContentModel):
    token: str = Field(min_length=32, max_length=128)


class UnsubscribeReceipt(ContentModel):
    status: Literal["unsubscribed"]
