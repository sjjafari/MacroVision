"""Code-reviewed private indicator curation for the Phase 3A reader contracts."""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import parse_qsl, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from macrovision.indicator_schemas import (
    IndicatorCurationStatus,
    IndicatorRelationCode,
    IndicatorSeasonalAdjustmentStatus,
)

PersianShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=240),
]
PersianLongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2000),
]


class RelatedDerivedSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    definition_code: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Z][A-Z0-9_.-]*$",
    )
    relation_code: IndicatorRelationCode
    relation_label_fa: PersianShortText
    description_fa: PersianLongText
    relation_order: int = Field(ge=1, le=100)


_CREDENTIAL_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "key",
    "password",
    "secret",
    "token",
}


def is_credential_free_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
        and not query_keys.intersection(_CREDENTIAL_QUERY_KEYS)
    )


class IndicatorCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    series_code: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[A-Z][A-Z0-9_.-]*$",
    )
    catalog_order: int = Field(ge=1, le=1000)
    curation_status: IndicatorCurationStatus
    display_name_fa: PersianShortText
    description_fa: PersianLongText
    methodology_summary_fa: PersianLongText
    localized_unit_label: PersianShortText | None = None
    source_attribution_fa: PersianShortText
    editorial_updated_at: datetime
    seasonal_adjustment_status: IndicatorSeasonalAdjustmentStatus
    source_methodology_url: str | None = Field(default=None, max_length=500)
    related_derived: tuple[RelatedDerivedSpecification, ...] = Field(
        default=(),
        max_length=10,
    )

    @field_validator("editorial_updated_at")
    @classmethod
    def aware_editorial_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("editorial_updated_at must include a UTC offset")
        return value.astimezone(UTC)

    @field_validator("source_methodology_url")
    @classmethod
    def safe_methodology_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not is_credential_free_http_url(value):
            raise ValueError("source_methodology_url must be a credential-free HTTP(S) URL")
        return value

    @model_validator(mode="after")
    def unique_related_definitions(self) -> "IndicatorCatalogEntry":
        definition_codes = [item.definition_code for item in self.related_derived]
        relation_codes = [item.relation_code for item in self.related_derived]
        relation_orders = [item.relation_order for item in self.related_derived]
        if len(definition_codes) != len(set(definition_codes)):
            raise ValueError("related derived definition codes must be unique")
        if len(relation_codes) != len(set(relation_codes)):
            raise ValueError("related derived relation codes must be unique")
        if len(relation_orders) != len(set(relation_orders)):
            raise ValueError("related derived relation_order values must be unique")
        return self


def validate_indicator_catalog(
    entries: Iterable[IndicatorCatalogEntry],
) -> tuple[IndicatorCatalogEntry, ...]:
    catalog = tuple(entries)
    series_codes = [entry.series_code for entry in catalog]
    catalog_orders = [entry.catalog_order for entry in catalog]
    if len(series_codes) != len(set(series_codes)):
        raise ValueError("indicator catalog series codes must be unique")
    if len(catalog_orders) != len(set(catalog_orders)):
        raise ValueError("indicator catalog_order values must be unique")
    return tuple(sorted(catalog, key=lambda entry: entry.catalog_order))


_EDITORIAL_TIMESTAMP = datetime(2026, 7, 30, 0, 0, tzinfo=UTC)

INDICATOR_CATALOG = (
    IndicatorCatalogEntry(
        series_code="FRED.CPIAUCSL",
        catalog_order=10,
        curation_status=IndicatorCurationStatus.reviewed_private,
        display_name_fa="شاخص قیمت مصرف‌کننده",
        description_fa="سطح شاخص قیمت مصرف‌کننده شهری در ایالات متحده.",
        methodology_summary_fa=(
            "مقدار خام و بازنگری‌های ثبت‌شده بدون اجرای محاسبهٔ جدید نمایش داده می‌شوند."
        ),
        localized_unit_label="واحد شاخص",
        source_attribution_fa="دادهٔ اقتصادی فدرال رزرو (FRED)",
        editorial_updated_at=_EDITORIAL_TIMESTAMP,
        seasonal_adjustment_status=(IndicatorSeasonalAdjustmentStatus.seasonally_adjusted),
        source_methodology_url="https://fred.stlouisfed.org/series/CPIAUCSL",
        related_derived=(
            RelatedDerivedSpecification(
                definition_code="ANALYTICS.CPI.YOY",
                relation_code=IndicatorRelationCode.year_over_year,
                relation_label_fa="تغییر سالانه",
                description_fa="آخرین نتیجهٔ ماندگار محاسبهٔ تغییر سالانهٔ شاخص.",
                relation_order=10,
            ),
        ),
    ),
    IndicatorCatalogEntry(
        series_code="FRED.FEDFUNDS",
        catalog_order=20,
        curation_status=IndicatorCurationStatus.reviewed_private,
        display_name_fa="نرخ وجوه فدرال",
        description_fa="نرخ مؤثر وجوه فدرال ایالات متحده.",
        methodology_summary_fa="مشاهدات خام و بازنگری‌های ثبت‌شده منبع نمایش داده می‌شوند.",
        localized_unit_label="درصد",
        source_attribution_fa="دادهٔ اقتصادی فدرال رزرو (FRED)",
        editorial_updated_at=_EDITORIAL_TIMESTAMP,
        seasonal_adjustment_status=(IndicatorSeasonalAdjustmentStatus.not_seasonally_adjusted),
        source_methodology_url="https://fred.stlouisfed.org/series/FEDFUNDS",
    ),
    IndicatorCatalogEntry(
        series_code="FRED.UNRATE",
        catalog_order=30,
        curation_status=IndicatorCurationStatus.reviewed_private,
        display_name_fa="نرخ بیکاری",
        description_fa="نرخ بیکاری نیروی کار غیرنظامی ایالات متحده.",
        methodology_summary_fa="وضعیت بازار کار بر پایهٔ مشاهدات خام منبع گزارش می‌شود.",
        localized_unit_label="درصد",
        source_attribution_fa="دادهٔ اقتصادی فدرال رزرو (FRED)",
        editorial_updated_at=_EDITORIAL_TIMESTAMP,
        seasonal_adjustment_status=(IndicatorSeasonalAdjustmentStatus.seasonally_adjusted),
        source_methodology_url="https://fred.stlouisfed.org/series/UNRATE",
    ),
    IndicatorCatalogEntry(
        series_code="FRED.M2SL",
        catalog_order=40,
        curation_status=IndicatorCurationStatus.reviewed_private,
        display_name_fa="حجم پول M2",
        description_fa="برآورد عرضهٔ پول M2 در ایالات متحده.",
        methodology_summary_fa="سطح نقدینگی از دادهٔ خام و تاریخچهٔ بازنگری منبع خوانده می‌شود.",
        localized_unit_label="میلیارد دلار",
        source_attribution_fa="دادهٔ اقتصادی فدرال رزرو (FRED)",
        editorial_updated_at=_EDITORIAL_TIMESTAMP,
        seasonal_adjustment_status=(IndicatorSeasonalAdjustmentStatus.seasonally_adjusted),
        source_methodology_url="https://fred.stlouisfed.org/series/M2SL",
    ),
    IndicatorCatalogEntry(
        series_code="FRED.DCOILWTICO",
        catalog_order=50,
        curation_status=IndicatorCurationStatus.reviewed_private,
        display_name_fa="نفت خام WTI",
        description_fa="قیمت نقدی نفت خام وست تگزاس اینترمدیت.",
        methodology_summary_fa="آخرین قیمت خام ثبت‌شده بدون تبدیل ارزی نمایش داده می‌شود.",
        localized_unit_label="دلار برای هر بشکه",
        source_attribution_fa="دادهٔ اقتصادی فدرال رزرو (FRED)",
        editorial_updated_at=_EDITORIAL_TIMESTAMP,
        seasonal_adjustment_status=IndicatorSeasonalAdjustmentStatus.not_applicable,
        source_methodology_url="https://fred.stlouisfed.org/series/DCOILWTICO",
    ),
    IndicatorCatalogEntry(
        series_code="FRED.GEPUCURRENT",
        catalog_order=60,
        curation_status=IndicatorCurationStatus.reviewed_private,
        display_name_fa="عدم‌قطعیت سیاستی جهان",
        description_fa="شاخص عدم‌قطعیت سیاست اقتصادی در سطح جهان.",
        methodology_summary_fa="ورودی فقط پس از وجود سری canonical قابل مشاهده و پیوند است.",
        localized_unit_label="واحد شاخص",
        source_attribution_fa="دادهٔ اقتصادی فدرال رزرو (FRED)",
        editorial_updated_at=_EDITORIAL_TIMESTAMP,
        seasonal_adjustment_status=IndicatorSeasonalAdjustmentStatus.unknown,
        source_methodology_url="https://fred.stlouisfed.org/series/GEPUCURRENT",
    ),
    IndicatorCatalogEntry(
        series_code="FRED.NFCI",
        catalog_order=70,
        curation_status=IndicatorCurationStatus.withheld,
        display_name_fa="شاخص شرایط مالی",
        description_fa="این ورودی در Phase 3A برای نمایش خواننده نگه داشته نشده است.",
        methodology_summary_fa="وضعیت withheld از endpointهای خواننده پنهان می‌ماند.",  # noqa: RUF001
        localized_unit_label="واحد شاخص",
        source_attribution_fa="دادهٔ اقتصادی فدرال رزرو (FRED)",
        editorial_updated_at=_EDITORIAL_TIMESTAMP,
        seasonal_adjustment_status=IndicatorSeasonalAdjustmentStatus.unknown,
        source_methodology_url="https://fred.stlouisfed.org/series/NFCI",
    ),
)

VALIDATED_INDICATOR_CATALOG = validate_indicator_catalog(INDICATOR_CATALOG)
REVIEWED_INDICATOR_CATALOG = tuple(
    entry
    for entry in VALIDATED_INDICATOR_CATALOG
    if entry.curation_status == IndicatorCurationStatus.reviewed_private
)
REVIEWED_INDICATORS_BY_CODE = {entry.series_code: entry for entry in REVIEWED_INDICATOR_CATALOG}
