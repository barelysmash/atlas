import pytest
from atlas_core import OperationalRecord
from atlas_core.trend_observation_engine import generate_trend_observations


def make_record(period: str, metric: str, value: float) -> OperationalRecord:
    return OperationalRecord.create(
        source="tabc",
        entity="Fonda San Miguel",
        period=period,
        category="sales",
        metric=metric,
        value=value,
    )


def test_requires_records():
    with pytest.raises(ValueError):
        generate_trend_observations([])


def test_single_record_reports_value_in_period():
    observations = generate_trend_observations(
        [make_record("2026-06", "wine_receipts", 50000.0)]
    )

    assert len(observations) == 1
    assert observations[0].summary == "wine_receipts was 50,000 in 2026-06."
    assert observations[0].source_ref == "tabc:Fonda San Miguel:2026-06"
    assert observations[0].periods == ("2026-06",)


def test_a_single_period_records_no_movement():
    """One period cannot show change, and the delta must say so."""
    observations = generate_trend_observations(
        [make_record("2026-06", "wine_receipts", 50000.0)]
    )

    assert observations[0].metrics[0].delta is None


def test_reports_period_over_period_change():
    observations = generate_trend_observations(
        [
            make_record("2026-05", "wine_receipts", 49000.0),
            make_record("2026-06", "wine_receipts", 50000.0),
        ]
    )

    assert len(observations) == 1
    assert observations[0].summary == (
        "wine_receipts was 50,000 in 2026-06 (+2.0% vs 2026-05)."
    )
    assert observations[0].source_ref == (
        "tabc:Fonda San Miguel:2026-05 tabc:Fonda San Miguel:2026-06"
    )
    assert observations[0].periods == ("2026-05", "2026-06")


def test_change_is_carried_as_a_contract_delta():
    """JAM states delta as a fraction: two percent is 0.02, not 2.0."""
    observations = generate_trend_observations(
        [
            make_record("2026-05", "wine_receipts", 49000.0),
            make_record("2026-06", "wine_receipts", 50000.0),
        ]
    )

    assert observations[0].metrics[0].delta == pytest.approx(0.0204, abs=1e-4)


def test_orders_records_by_period():
    observations = generate_trend_observations(
        [
            make_record("2026-06", "wine_receipts", 50000.0),
            make_record("2026-05", "wine_receipts", 49000.0),
        ]
    )

    assert observations[0].metrics[0].value == 50000.0


def test_reports_streak_when_direction_persists():
    observations = generate_trend_observations(
        [
            make_record("2026-03", "wine_receipts", 44000.0),
            make_record("2026-04", "wine_receipts", 47500.0),
            make_record("2026-05", "wine_receipts", 49000.0),
            make_record("2026-06", "wine_receipts", 50000.0),
        ]
    )

    assert len(observations) == 2
    assert observations[1].summary == (
        "wine_receipts has increased for 3 consecutive periods "
        "(2026-03 through 2026-06)."
    )
    assert observations[1].periods == (
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
    )


def test_a_streak_states_the_span_it_covers_not_the_grain():
    """Three consecutive monthly rises describe P3M, not P1M."""
    observations = generate_trend_observations(
        [
            make_record("2026-03", "wine_receipts", 44000.0),
            make_record("2026-04", "wine_receipts", 47500.0),
            make_record("2026-05", "wine_receipts", 49000.0),
            make_record("2026-06", "wine_receipts", 50000.0),
        ]
    )

    assert observations[0].metrics[0].period == "P1M"
    assert observations[1].metrics[0].period == "P3M"


def test_no_streak_when_direction_reverses():
    observations = generate_trend_observations(
        [
            make_record("2026-03", "liquor_receipts", 97000.0),
            make_record("2026-04", "liquor_receipts", 101000.0),
            make_record("2026-05", "liquor_receipts", 99000.0),
            make_record("2026-06", "liquor_receipts", 100000.0),
        ]
    )

    assert len(observations) == 1


def test_metrics_are_observed_independently():
    observations = generate_trend_observations(
        [
            make_record("2026-05", "wine_receipts", 49000.0),
            make_record("2026-05", "beer_receipts", 24500.0),
            make_record("2026-06", "wine_receipts", 50000.0),
            make_record("2026-06", "beer_receipts", 25000.0),
        ]
    )

    metrics = [observation.metrics[0].name for observation in observations]

    assert metrics == ["wine_receipts", "beer_receipts"]


def test_zero_previous_value_does_not_divide_by_zero():
    observations = generate_trend_observations(
        [
            make_record("2026-05", "wine_receipts", 0.0),
            make_record("2026-06", "wine_receipts", 50000.0),
        ]
    )

    assert "(+0.0% vs 2026-05)" in observations[0].summary


def test_observations_carry_the_record_category_as_their_domain():
    observations = generate_trend_observations(
        [make_record("2026-06", "wine_receipts", 50000.0)]
    )

    assert observations[0].domain == "sales"
    assert observations[0].subject == "Fonda San Miguel"


def test_a_small_value_is_not_rounded_away_to_nothing():
    """A market share below one percent is a small share, not none."""
    observations = generate_trend_observations(
        [
            make_record("2026-05", "market_share", 0.48),
            make_record("2026-06", "market_share", 0.52),
        ]
    )

    assert "0.52" in observations[0].summary
    assert "was 0 in" not in observations[0].summary
