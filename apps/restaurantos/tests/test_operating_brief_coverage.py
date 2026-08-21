from datetime import date

from atlas_core.operational_record import OperationalRecord
from restaurantos.operating_brief import (
    generate_operating_brief,
    summarize_operating_period,
)


def record(period: str, metric: str, value: float) -> OperationalRecord:
    return OperationalRecord.create(
        source="nightly_email",
        entity="Fonda San Miguel",
        period=period,
        category="operations",
        metric=metric,
        value=value,
        grain="daily",
        aggregation="sum",
    )


def test_volume_comparison_normalizes_when_coverage_differs():
    records = [
        record("2026-06-01", "net_sales", 1000.0),
        record("2026-06-02", "net_sales", 1000.0),
        record("2026-07-01", "net_sales", 1100.0),
    ]
    previous = summarize_operating_period(
        records,
        date(2026, 6, 1),
        date(2026, 6, 2),
        label="June",
    )
    current = summarize_operating_period(
        records,
        date(2026, 7, 1),
        date(2026, 7, 1),
        label="July",
    )

    brief = generate_operating_brief(current, previous)

    assert "Net sales / covered night: +10.0% (1 vs 2 nights)" in brief
    assert current.per_night("net_sales") == 1100.0
    assert previous.per_night("net_sales") == 1000.0
