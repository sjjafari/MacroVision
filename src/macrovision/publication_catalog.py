"""Explicit reviewed publication eligibility for public Web reads.

This allowlist is deliberately independent from operational is_active and private curation.
Adding a code is a publication decision and requires code review.
"""

PUBLIC_INDICATOR_CODES = frozenset(
    {
        "FRED.CPIAUCSL",
        "FRED.FEDFUNDS",
        "FRED.UNRATE",
        "FRED.M2SL",
        "FRED.DCOILWTICO",
        "FRED.GEPUCURRENT",
    }
)


def is_public_indicator(code: str) -> bool:
    return code in PUBLIC_INDICATOR_CODES
