from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from macrovision.analytics_schemas import (
    DerivedSeriesDefinitionCreate,
    RebaseIndexParameters,
)


def _definition(
    *,
    code: str = "cpi.yoy",
    parameters: dict[str, object] | None = None,
    inputs: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "code": code,
        "title": "CPI year-over-year",
        "inputs": inputs or [{"position": 0, "alias": "value", "source_series_id": 1}],
        "parameters": parameters or {"transformation_type": "year_over_year_percent_change"},
    }


def test_definition_normalizes_ascii_code_and_validates_registry() -> None:
    payload = DerivedSeriesDefinitionCreate.model_validate(_definition())
    assert payload.code == "CPI.YOY"
    assert payload.inputs[0].alias == "value"


@pytest.mark.parametrize("code", ["ÉCONOMY", "_INVALID", "HAS SPACE", ""])
def test_definition_rejects_noncanonical_code(code: str) -> None:
    with pytest.raises(ValidationError):
        DerivedSeriesDefinitionCreate.model_validate(_definition(code=code))


def test_strict_contract_rejects_extra_and_arbitrary_formula() -> None:
    payload = _definition()
    payload["formula"] = "eval('unsafe')"
    with pytest.raises(ValidationError):
        DerivedSeriesDefinitionCreate.model_validate(payload)

    parameters: dict[str, object] = {
        "transformation_type": "difference",
        "sql": "SELECT 1",
    }
    with pytest.raises(ValidationError):
        DerivedSeriesDefinitionCreate.model_validate(_definition(parameters=parameters))


def test_unknown_transformation_and_wrong_alias_order_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DerivedSeriesDefinitionCreate.model_validate(
            _definition(parameters={"transformation_type": "arbitrary"})
        )
    with pytest.raises(ValidationError, match="ordered aliases"):
        DerivedSeriesDefinitionCreate.model_validate(
            _definition(
                parameters={"transformation_type": "ratio"},
                inputs=[
                    {"position": 0, "alias": "denominator", "source_series_id": 1},
                    {"position": 1, "alias": "numerator", "source_series_id": 2},
                ],
            )
        )


def test_input_positions_must_be_contiguous_and_arity_is_exact() -> None:
    with pytest.raises(ValidationError, match="positions"):
        DerivedSeriesDefinitionCreate.model_validate(
            _definition(inputs=[{"position": 1, "alias": "value", "source_series_id": 1}])
        )
    with pytest.raises(ValidationError, match="ordered aliases"):
        DerivedSeriesDefinitionCreate.model_validate(
            _definition(
                inputs=[
                    {"position": 0, "alias": "value", "source_series_id": 1},
                    {"position": 1, "alias": "value", "source_series_id": 2},
                ]
            )
        )


@pytest.mark.parametrize(
    "transformation",
    ["moving_average", "rolling_standard_deviation", "rolling_z_score"],
)
def test_window_contract_is_bounded(transformation: str) -> None:
    for invalid in (1, 1001):
        with pytest.raises(ValidationError):
            DerivedSeriesDefinitionCreate.model_validate(
                _definition(parameters={"transformation_type": transformation, "window": invalid})
            )


def test_decimal_rejects_float_and_serializes_canonically() -> None:
    with pytest.raises(ValidationError, match="Floating-point"):
        RebaseIndexParameters(
            transformation_type="rebase_index",
            base_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            base_value=100.0,
        )
    parameters = RebaseIndexParameters(
        transformation_type="rebase_index",
        base_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        base_value="100.00000000",
    )
    assert parameters.base_value == Decimal("100.00000000")
    assert parameters.model_dump(mode="json")["base_value"] == "100.00000000"


def test_rebase_requires_aware_timestamp_and_positive_value() -> None:
    with pytest.raises(ValidationError):
        RebaseIndexParameters(
            transformation_type="rebase_index",
            base_timestamp=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        RebaseIndexParameters(
            transformation_type="rebase_index",
            base_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            base_value=Decimal("0"),
        )
