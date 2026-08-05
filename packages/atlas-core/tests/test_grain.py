import pytest
from atlas_core import OperationalRecord
from atlas_core.grain import (
    AGGREGATIONS,
    DAILY,
    GRAIN_PERIODS,
    GRAINS,
    MEAN,
    MONTHLY,
    RATE,
    SUM,
    WEEKLY,
)
from atlas_core.observation_engine import generate_observations


def _record(**overrides) -> OperationalRecord:
    kwargs = {
        "source": "tabc",
        "entity": "Fonda San Miguel",
        "period": "2026-06",
        "category": "sales",
        "metric": "wine_receipts",
        "value": 50000.0,
    }
    kwargs.update(overrides)
    return OperationalRecord.create(**kwargs)


def test_every_grain_states_the_duration_it_covers():
    assert set(GRAIN_PERIODS) == set(GRAINS)


@pytest.mark.parametrize(
    ("grain", "duration"), [(DAILY, "P1D"), (WEEKLY, "P1W"), (MONTHLY, "P1M")]
)
def test_grain_maps_to_an_iso_duration(grain, duration):
    assert GRAIN_PERIODS[grain] == duration


def test_a_record_defaults_to_a_monthly_sum():
    record = _record()
    assert record.grain == MONTHLY
    assert record.aggregation == SUM


def test_a_record_may_state_its_grain():
    assert _record(grain=DAILY).grain == DAILY


@pytest.mark.parametrize("aggregation", [SUM, MEAN, RATE])
def test_every_aggregation_is_accepted(aggregation):
    assert _record(aggregation=aggregation).aggregation == aggregation


def test_an_unknown_grain_is_refused():
    with pytest.raises(ValueError, match="grain must be one of"):
        _record(grain="fortnightly")


def test_an_unknown_aggregation_is_refused():
    with pytest.raises(ValueError, match="aggregation must be one of"):
        _record(aggregation="median")


@pytest.mark.parametrize(
    ("grain", "duration"), [(DAILY, "P1D"), (WEEKLY, "P1W"), (MONTHLY, "P1M")]
)
def test_the_emitted_metric_states_the_period_it_covers(grain, duration):
    observation = generate_observations(_record(grain=grain))[0]
    assert observation.metrics[0].period == duration


def test_rate_is_a_distinct_aggregation():
    # A week's sales per labour hour is total sales over total hours, not the
    # mean of seven nightly rates. The vocabulary has to be able to say so.
    assert RATE in AGGREGATIONS
    assert RATE != MEAN
