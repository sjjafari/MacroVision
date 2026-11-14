from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from macrovision.indicator_schemas import (
    IndicatorCanonicalRead,
    IndicatorCatalogItem,
    IndicatorPresentationRead,
    IndicatorSourceRead,
)


class PublicIndicatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicIndicatorCatalogItem(IndicatorCatalogItem):
    private_preview: Literal[False] = False
    public_eligibility: Literal[True] = True


class PublicIndicatorCatalogPage(PublicIndicatorModel):
    limit: int
    offset: int
    total: int
    items: list[PublicIndicatorCatalogItem]


class PublicIndicatorCurationRead(PublicIndicatorModel):
    catalog_order: int
    editorial_updated_at: datetime
    private_preview: Literal[False] = False
    public_eligibility: Literal[True] = True


class PublicIndicatorDetail(PublicIndicatorModel):
    curation: PublicIndicatorCurationRead
    presentation: IndicatorPresentationRead
    canonical: IndicatorCanonicalRead
    source: IndicatorSourceRead
