from datetime import date, timedelta

import pytest
from atlas_core import OperationalRecord, block_records


def make_record(
    period: str,
    metric: str,
    value: float,
    grain: str = "daily",
    aggregation: str = "sum",
) -> OperationalRecord:
    return OperationalRecord.create(
        source="pos",
        entity="Fonda San Miguel",
        period=period,
        category="sales",
        metric=metric,
        value=value,
        grain=grain,
        aggregation=aggregation,
    )


def run(
    days: int,
    metric: str = "net_sales",
    skip_weekday: int | None = None,
    value: float = 100.0,
    start: date = date(2026, 5, 4),
    **kwargs: str,
) -> list[OperationalRecord]:
    records = []

    for offset in range(days):
        day = start + timedelta(days=offset)

        if skip_weekday is not None and day.weekday() == skip_weekday:
            continue

        records.append(make_record(day.isoformat(), metric, value, **kwargs))

    return records


def test_monthly_records_pass_through_untouched():
    records = [
        make_record("2026-05", "wine_receipts", 49000.0, grain="monthly"),
        make_record("2026-06", "wine_receipts", 50000.0, grain="monthly"),
    ]

    assert block_records(records) == records


def test_daily_records_roll_up_into_calendar_weeks():
    blocked = block_records(run(14))

    assert len(blocked) == 2
    assert blocked[0].period == "2026-05-04..2026-05-10"
    assert blocked[1].period == "2026-05-11..2026-05-17"


def test_summed_metrics_are_totalled_across_the_week():
    blocked = block_records(run(7))

    assert blocked[0].value == 700.0


def test_averaged_metrics_are_meaned_across_the_week():
    blocked = block_records(
        run(7, metric="hospitality_score", value=4.0, aggregation="mean")
    )

    assert blocked[0].value == 4.0


def test_a_closed_weekday_still_yields_aligned_weeks():
    """Six reports a week must not carry each block into the next week."""
    blocked = block_records(run(28, skip_weekday=0))

    assert [record.period for record in blocked] == [
        "2026-05-05..2026-05-10",
        "2026-05-12..2026-05-17",
        "2026-05-19..2026-05-24",
        "2026-05-26..2026-05-31",
    ]


def test_a_partial_week_at_the_edge_is_dropped():
    """A partial week must not be compared against a full one."""
    blocked = block_records(run(10))

    assert len(blocked) == 1
    assert blocked[0].period == "2026-05-04..2026-05-10"


def test_a_week_broken_by_an_unplanned_closure_is_dropped():
    records = [record for record in run(21) if record.period != "2026-05-13"]

    periods = [record.period for record in block_records(records)]

    assert "2026-05-11..2026-05-17" not in periods
    assert len(periods) == 2


def test_a_window_of_only_partial_weeks_keeps_them():
    """The usual trading week is inferred from the window it is given.

    Three days is the only week length present, so three days becomes the
    trading week and the block is kept. Pinned rather than corrected: with
    nothing fuller to compare against, there is no evidence the week is
    partial.
    """
    blocked = block_records(run(3))

    assert len(blocked) == 1
    assert blocked[0].period == "2026-05-04..2026-05-06"


def test_metrics_with_different_reporting_days_still_align():
    """Capacity covers every trading night; sales may miss one."""
    sales = run(14, metric="net_sales", skip_weekday=0)
    capacity = run(14, metric="seat_hours", skip_weekday=0, value=980.0)

    blocked = block_records(sales + capacity)
    by_metric: dict[str, list[str]] = {}

    for record in blocked:
        by_metric.setdefault(record.metric, []).append(record.period)

    assert by_metric["net_sales"] == by_metric["seat_hours"]


def test_a_rate_cannot_be_rolled_up_from_its_own_values():
    with pytest.raises(ValueError, match="cannot be rolled up"):
        block_records(run(7, metric="splh", value=42.0, aggregation="rate"))


def test_a_metric_may_not_mix_grains():
    records = [
        make_record("2026-06-01", "net_sales", 100.0, grain="daily"),
        make_record("2026-06", "net_sales", 3000.0, grain="monthly"),
    ]

    with pytest.raises(ValueError, match="mixes grains"):
        block_records(records)


def test_a_daily_record_must_carry_a_date():
    records = [make_record("week 23", "net_sales", 100.0, grain="daily")]

    with pytest.raises(ValueError, match="not a date"):
        block_records(records)


def test_metrics_are_blocked_independently():
    records = run(7) + [
        make_record("2026-05", "wine_receipts", 49000.0, grain="monthly"),
    ]

    blocked = block_records(records)

    assert {record.metric for record in blocked} == {"net_sales", "wine_receipts"}
