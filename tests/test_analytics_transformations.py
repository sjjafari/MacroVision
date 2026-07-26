import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from macrovision.analytics_schemas import (
    InputMetadata,
    MovingAverageParameters,
    NoParameters,
    RebaseIndexParameters,
    RollingStandardDeviationParameters,
    RollingZScoreParameters,
    TransformationType,
)
from macrovision.analytics_transformations import (
    REGISTRY,
    AnalyticsContractError,
    InputState,
    MissingReason,
    PointValue,
    canonical_json,
    canonical_parameters,
    evaluate_transformation,
    get_transformation_spec,
    parameters_fingerprint,
    previous_period_anchor,
    year_over_year_anchor,
)
from macrovision.macro_data_models import DataFrequency, SeasonalAdjustment

P = InputState.present
M = InputState.missing
A = InputState.absent


def point(value: str) -> PointValue:
    return PointValue(P, Decimal(value))


def no_params(kind: TransformationType) -> NoParameters:
    return NoParameters(transformation_type=kind)


@pytest.mark.parametrize(
    ("kind", "inputs", "expected"),
    [
        ("difference", ((point("100"), point("105.25")),), "5.25000000"),
        ("difference", ((point("2"), point("-3")),), "-5.00000000"),
        ("percent_change", ((point("100"), point("110")),), "10.00000000"),
        (
            "year_over_year_percent_change",
            ((point("100"), point("120")),),
            "20.00000000",
        ),
        ("ratio", ((point("150"),), (point("200"),)), "0.75000000"),
        ("spread", ((point("5.25"),), (point("3.75"),)), "1.50000000"),
    ],
)
def test_basic_transformations(
    kind: str, inputs: tuple[tuple[PointValue, ...], ...], expected: str
) -> None:
    result = evaluate_transformation(no_params(TransformationType(kind)), inputs)
    assert result.is_present
    assert result.value == Decimal(expected)


def test_rolling_transformations_are_exact_and_population_based() -> None:
    average = evaluate_transformation(
        MovingAverageParameters(transformation_type="moving_average", window=3),
        ((point("10"), point("20"), point("30")),),
    )
    deviation = evaluate_transformation(
        RollingStandardDeviationParameters(
            transformation_type="rolling_standard_deviation", window=2
        ),
        ((point("2"), point("4")),),
    )
    score = evaluate_transformation(
        RollingZScoreParameters(transformation_type="rolling_z_score", window=2),
        ((point("2"), point("4")),),
    )
    assert average.value == Decimal("20.00000000")
    assert deviation.value == Decimal("1.00000000")
    assert score.value == Decimal("1.00000000")


def test_rebase_is_exact_and_base_failures_are_structural() -> None:
    parameters = RebaseIndexParameters(
        transformation_type="rebase_index",
        base_timestamp=datetime(2025, 1, 1, tzinfo=UTC),
    )
    assert evaluate_transformation(parameters, ((point("80"), point("100")),)).value == Decimal(
        "125.00000000"
    )
    for base in (PointValue(A), PointValue(M), point("0")):
        with pytest.raises(AnalyticsContractError):
            evaluate_transformation(parameters, ((base, point("100")),))
    with pytest.raises(AnalyticsContractError):
        evaluate_transformation(parameters, ((point("100"),),))


@pytest.mark.parametrize(
    ("inputs", "reason"),
    [
        (((point("1"), PointValue(A)),), MissingReason.timestamp_absent),
        (((point("1"), PointValue(M)),), MissingReason.source_missing),
        (((point("1"),),), MissingReason.insufficient_history),
    ],
)
def test_point_missingness_is_explicit(
    inputs: tuple[tuple[PointValue, ...], ...], reason: MissingReason
) -> None:
    result = evaluate_transformation(no_params(TransformationType.difference), inputs)
    assert result.value is None
    assert result.missing_reason is reason


def test_zero_denominators_and_constant_zscore_are_missing() -> None:
    ratio = evaluate_transformation(
        no_params(TransformationType.ratio), ((point("1"),), (point("0"),))
    )
    change = evaluate_transformation(
        no_params(TransformationType.percent_change), ((point("0"), point("1")),)
    )
    score = evaluate_transformation(
        RollingZScoreParameters(transformation_type="rolling_z_score", window=2),
        ((point("3"), point("3")),),
    )
    assert {ratio.missing_reason, change.missing_reason, score.missing_reason} == {
        MissingReason.division_by_zero
    }


def test_overflow_and_half_even_rounding_are_deterministic() -> None:
    overflow = evaluate_transformation(
        no_params(TransformationType.difference),
        ((point("-92233720368.54775808"), point("92233720368.54775807")),),
    )
    rounded = evaluate_transformation(
        no_params(TransformationType.ratio),
        ((point("0.000000025"),), (point("2"),)),
    )
    assert overflow.missing_reason is MissingReason.numeric_overflow
    assert rounded.value == Decimal("0.00000001")


def test_registry_is_closed_and_validates_arity_and_parameters() -> None:
    assert set(REGISTRY) == set(TransformationType)
    assert get_transformation_spec("ratio").ordered_aliases == ("numerator", "denominator")
    with pytest.raises(AnalyticsContractError):
        get_transformation_spec("python_eval")
    with pytest.raises(AnalyticsContractError):
        evaluate_transformation(no_params(TransformationType.ratio), ((point("1"),),))


def metadata(
    *,
    unit: str = "USD",
    frequency: DataFrequency = DataFrequency.monthly,
    geography: str = "US",
    currency: str | None = "USD",
    seasonal: SeasonalAdjustment = SeasonalAdjustment.adjusted,
) -> InputMetadata:
    return InputMetadata(
        unit=unit,
        frequency=frequency,
        geography=geography,
        currency=currency,
        seasonal_adjustment=seasonal,
    )


def test_metadata_derivation_and_incompatibility() -> None:
    ratio = REGISTRY[TransformationType.ratio].validate_metadata([metadata(), metadata()])
    spread = REGISTRY[TransformationType.spread].validate_metadata([metadata(), metadata()])
    percent = REGISTRY[TransformationType.percent_change].validate_metadata([metadata()])
    assert (ratio.unit, ratio.currency) == ("ratio", None)
    assert (spread.unit, spread.currency) == ("USD", "USD")
    assert (percent.unit, percent.currency) == ("percent", None)
    assert (
        REGISTRY[TransformationType.rolling_z_score].validate_metadata([metadata()]).unit
        == "z_score"
    )
    assert REGISTRY[TransformationType.rebase_index].validate_metadata([metadata()]).unit == "index"
    for incompatible in (
        metadata(unit="EUR"),
        metadata(frequency=DataFrequency.quarterly),
        metadata(geography="CA"),
        metadata(seasonal=SeasonalAdjustment.unknown),
    ):
        with pytest.raises(AnalyticsContractError):
            REGISTRY[TransformationType.ratio].validate_metadata([metadata(), incompatible])
    with pytest.raises(AnalyticsContractError):
        REGISTRY[TransformationType.difference].validate_metadata(
            [metadata(frequency=DataFrequency.irregular)]
        )


def test_canonicalization_is_stable_private_and_rejects_floats() -> None:
    parameters = RebaseIndexParameters(
        transformation_type="rebase_index",
        base_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        base_value=Decimal("100.00000000"),
    )
    serialized = canonical_parameters(parameters)
    assert serialized == canonical_parameters(parameters)
    assert '"base_value":"100.00000000"' in serialized
    fingerprint = parameters_fingerprint(parameters)
    assert len(fingerprint) == 64
    assert fingerprint == fingerprint.lower()
    assert canonical_json({"b": 1, "a": Decimal("2.00")}) == '{"a":"2.00","b":1}'
    with pytest.raises(AnalyticsContractError):
        canonical_json({"unsafe": 1.5})


@pytest.mark.parametrize(
    ("frequency", "previous", "yoy"),
    [
        (DataFrequency.daily, datetime(2026, 3, 2, tzinfo=UTC), datetime(2025, 3, 3, tzinfo=UTC)),
        (DataFrequency.weekly, datetime(2026, 2, 24, tzinfo=UTC), datetime(2025, 3, 4, tzinfo=UTC)),
        (DataFrequency.monthly, datetime(2026, 2, 3, tzinfo=UTC), datetime(2025, 3, 3, tzinfo=UTC)),
        (
            DataFrequency.quarterly,
            datetime(2025, 12, 3, tzinfo=UTC),
            datetime(2025, 3, 3, tzinfo=UTC),
        ),
        (DataFrequency.annual, datetime(2025, 3, 3, tzinfo=UTC), datetime(2025, 3, 3, tzinfo=UTC)),
    ],
)
def test_exact_calendar_anchors(
    frequency: DataFrequency, previous: datetime, yoy: datetime
) -> None:
    current = datetime(2026, 3, 3, tzinfo=UTC)
    assert previous_period_anchor(current, frequency) == previous
    assert year_over_year_anchor(current, frequency) == yoy


def test_leap_day_has_no_nearest_date_substitution() -> None:
    leap_day = datetime(2024, 2, 29, tzinfo=UTC)
    assert year_over_year_anchor(leap_day, DataFrequency.daily) is None
    assert previous_period_anchor(datetime(2024, 3, 31, tzinfo=UTC), DataFrequency.monthly) is None
    with pytest.raises(AnalyticsContractError):
        previous_period_anchor(leap_day, DataFrequency.irregular)


def test_point_contract_and_input_data_are_not_mutated() -> None:
    with pytest.raises(AnalyticsContractError):
        PointValue(P, None)
    with pytest.raises(AnalyticsContractError):
        PointValue(M, Decimal("1"))
    inputs = ((point("1"), point("2")),)
    before = inputs
    evaluate_transformation(no_params(TransformationType.difference), inputs)
    assert inputs == before


def test_registry_has_no_arbitrary_execution_or_runtime_registration_path() -> None:
    import macrovision.analytics_transformations as module

    source = inspect.getsource(module)
    assert "eval(" not in source
    assert "exec(" not in source
    assert "ast." not in source
    assert not hasattr(module, "register_transformation")
