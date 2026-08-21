from datetime import date

import pytest
from atlas_core.operational_record import OperationalRecord

from restaurantos.operating_brief import (
    generate_operating_brief,
    summarize_operating_period,
)


def record(
    period: str,
    metric: str,
    value: float,
    *,
    entity: str = "Fonda San Miguel",
    estimated: bool = False,
) -> OperationalRecord:
    dimensions = {"estimated": True} if estimated else {}
    return OperationalRecord.create(
        source="nightly_email",
        entity=entity,
        period=period,
        category="operations",
        metric=metric,
        value=value,
        dimensions=dimensions,
        grain="daily",
        aggregation="sum",
    )


def period_records() -> list[OperationalRecord]:
    return [
        record("2026-06-01", "net_sales", 4000.0),
        record("2026-06-01", "labor_hours", 100.0),
        record("2026-06-01", "labor_cost", 1000.0),
        record("2026-06-01", "reservation_covers", 80.0),
        record("2026-06-01", "guest_count", 100.0),
        record("2026-06-01", "dining_room_covers", 70.0),
        record("2026-06-01", "bar_atrium_covers", 30.0),
        record("2026-06-01", "comps", 100.0),
        record("2026-06-01", "voids", 40.0),
        record("2026-06-02", "net_sales", 1000.0, estimated=True),
        record("2026-06-02", "labor_hours", 50.0),
        record("2026-06-02", "labor_cost", 300.0),
        record("2026-06-02", "reservation_covers", 20.0),
        record("2026-06-02", "guest_count", 50.0),
        record("2026-06-02", "dining_room_covers", 25.0),
        record("2026-06-02", "bar_atrium_covers", 25.0),
        record("2026-06-02", "comps", 50.0),
        record("2026-06-02", "voids", 10.0),
    ]


def test_period_rates_use_summed_components_not_nightly_rate_means():
    summary = summarize_operating_period(
        period_records(),
        date(2026, 6, 1),
        date(2026, 6, 2),
    )

    assert summary.total("net_sales") == 5000.0
    assert summary.total("guest_count") == 150.0
    assert round(summary.metric("splh"), 2) == 33.33
    assert round(summary.metric("average_check"), 2) == 33.33
    assert round(summary.metric("labor_cost_pct"), 2) == 26.00
    assert round(summary.metric("reservation_share"), 2) == 66.67
    assert summary.metric("walk_in_covers") == 50.0


def test_rates_use_only_nights_where_both_components_exist():
    records = [
        record("2026-06-01", "net_sales", 4000.0),
        record("2026-06-01", "labor_hours", 100.0),
        record("2026-06-02", "net_sales", 6000.0),
    ]

    summary = summarize_operating_period(
        records,
        date(2026, 6, 1),
        date(2026, 6, 2),
    )

    assert summary.total("net_sales") == 10000.0
    assert summary.metric("splh") == 40.0
    assert summary.metric_nights("splh") == 1
    assert summary.nights_with("net_sales") == 2
    assert summary.nights_with("labor_hours") == 1


def test_estimated_sales_nights_are_audited():
    summary = summarize_operating_period(
        period_records(),
        date(2026, 6, 1),
        date(2026, 6, 2),
    )

    assert summary.estimated_sales_nights == 1


def test_multiple_entities_require_explicit_selection():
    records = [
        record("2026-06-01", "net_sales", 4000.0),
        record(
            "2026-06-01",
            "net_sales",
            1000.0,
            entity="Second Venue",
        ),
    ]

    with pytest.raises(ValueError, match="entity is required"):
        summarize_operating_period(
            records,
            date(2026, 6, 1),
            date(2026, 6, 1),
        )

    second = summarize_operating_period(
        records,
        date(2026, 6, 1),
        date(2026, 6, 1),
        entity="Second Venue",
    )
    assert second.total("net_sales") == 1000.0


def test_duplicate_base_metric_for_a_night_is_rejected():
    records = [
        record("2026-06-01", "net_sales", 4000.0),
        record("2026-06-01", "net_sales", 1000.0),
    ]

    with pytest.raises(ValueError, match="duplicate net_sales"):
        summarize_operating_period(
            records,
            date(2026, 6, 1),
            date(2026, 6, 1),
        )


def test_brief_reports_coverage_and_period_comparison():
    records = period_records()
    previous = summarize_operating_period(
        records,
        date(2026, 6, 1),
        date(2026, 6, 1),
        label="June 1",
    )
    current = summarize_operating_period(
        records,
        date(2026, 6, 2),
        date(2026, 6, 2),
        label="June 2",
    )

    brief = generate_operating_brief(current, previous)

    assert "# Fonda San Miguel Operating Brief" in brief
    assert "## June 2" in brief
    assert "Sales 1/1; covers 1/1; labor 1/1" in brief
    assert "Estimated sales nights: 1" in brief
    assert "## vs June 1" in brief
    assert "- Net sales: -75.0%" in brief
    assert "- Labor cost %: +5.0 pp" in brief


def test_comparison_must_use_same_entity():
    current = summarize_operating_period(
        period_records(),
        date(2026, 6, 1),
        date(2026, 6, 2),
    )
    other_records = [
        record(
            "2026-06-01",
            "net_sales",
            1000.0,
            entity="Second Venue",
        )
    ]
    previous = summarize_operating_period(
        other_records,
        date(2026, 6, 1),
        date(2026, 6, 1),
    )

    with pytest.raises(ValueError, match="same entity"):
        generate_operating_brief(current, previous)


def test_empty_period_is_rejected():
    with pytest.raises(ValueError, match="no daily records"):
        summarize_operating_period(
            period_records(),
            date(2026, 7, 1),
            date(2026, 7, 31),
        )
