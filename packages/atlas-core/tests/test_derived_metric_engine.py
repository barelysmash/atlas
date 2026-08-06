from atlas_core import OperationalRecord, block_records, derive_metrics


def make_record(
    period: str, metric: str, value: float, grain: str = "daily"
) -> OperationalRecord:
    return OperationalRecord.create(
        source="pos",
        entity="Fonda San Miguel",
        period=period,
        category="labor",
        metric=metric,
        value=value,
        grain=grain,
    )


def test_rate_is_derived_from_its_components():
    records = [
        make_record("2026-06", "net_sales", 30000.0, grain="monthly"),
        make_record("2026-06", "labor_hours", 1000.0, grain="monthly"),
    ]

    splh = [r for r in derive_metrics(records) if r.metric == "splh"]

    assert len(splh) == 1
    assert splh[0].value == 30.0
    assert splh[0].aggregation == "rate"


def test_components_are_left_in_place():
    records = [
        make_record("2026-06", "net_sales", 30000.0, grain="monthly"),
        make_record("2026-06", "labor_hours", 1000.0, grain="monthly"),
    ]

    metrics = {record.metric for record in derive_metrics(records)}

    assert metrics == {"net_sales", "labor_hours", "splh"}


def test_a_missing_component_derives_nothing():
    records = [make_record("2026-06", "net_sales", 30000.0, grain="monthly")]

    assert derive_metrics(records) == records


def test_zero_denominator_derives_nothing():
    records = [
        make_record("2026-06", "net_sales", 30000.0, grain="monthly"),
        make_record("2026-06", "labor_hours", 0.0, grain="monthly"),
    ]

    assert [r for r in derive_metrics(records) if r.metric == "splh"] == []


def test_weekly_rate_uses_block_totals_not_the_mean_of_nightly_rates():
    """A busy night and a slow night do not carry equal weight."""
    sales = [4000.0] * 6 + [1000.0]
    hours = [100.0] * 6 + [50.0]

    records = [
        make_record(f"2026-06-{day:02d}", "net_sales", value)
        for day, value in enumerate(sales, start=1)
    ] + [
        make_record(f"2026-06-{day:02d}", "labor_hours", value)
        for day, value in enumerate(hours, start=1)
    ]

    splh = [r for r in derive_metrics(block_records(records)) if r.metric == "splh"]

    # Block totals: 25,000 sales over 650 hours.
    assert round(splh[0].value, 2) == 38.46

    # The mean of the nightly rates would have been 37.14, flattered by the
    # slow night counting as much as each busy one.
    nightly = [s / h for s, h in zip(sales, hours, strict=True)]
    assert round(sum(nightly) / len(nightly), 2) == 37.14


def sales_and_capacity(
    period: str, sales: float, cogs: float, seat_hours: float
) -> list[OperationalRecord]:
    return [
        make_record(period, "net_sales", sales, grain="monthly"),
        make_record(period, "cogs", cogs, grain="monthly"),
        make_record(period, "seat_hours", seat_hours, grain="monthly"),
    ]


def test_revenue_per_seat_hour_is_derived():
    records = sales_and_capacity("2026-06", 30000.0, 9000.0, 1000.0)

    revpash = [r for r in derive_metrics(records) if r.metric == "revpash"]

    assert revpash[0].value == 30.0


def test_contribution_margin_is_a_difference_and_stays_summable():
    records = sales_and_capacity("2026-06", 30000.0, 9000.0, 1000.0)

    margin = [r for r in derive_metrics(records) if r.metric == "contribution_margin"]

    assert margin[0].value == 21000.0
    assert margin[0].aggregation == "sum"


def test_definitions_may_build_on_one_another():
    """cm_per_seat_hour divides a metric that is itself derived."""
    records = sales_and_capacity("2026-06", 30000.0, 9000.0, 1000.0)

    per_seat_hour = [
        r for r in derive_metrics(records) if r.metric == "cm_per_seat_hour"
    ]

    assert per_seat_hour[0].value == 21.0
    assert per_seat_hour[0].aggregation == "rate"


def test_margin_without_cost_data_derives_nothing():
    records = [
        make_record("2026-06", "net_sales", 30000.0, grain="monthly"),
        make_record("2026-06", "seat_hours", 1000.0, grain="monthly"),
    ]

    metrics = {r.metric for r in derive_metrics(records)}

    assert "revpash" in metrics
    assert "contribution_margin" not in metrics
    assert "cm_per_seat_hour" not in metrics


def test_a_share_is_reported_on_a_percentage_scale():
    """A share beside other shares must read on the same scale."""
    records = [
        make_record("2026-05", "wine_receipts", 14670.0, grain="monthly"),
        make_record("2026-05", "total_receipts", 236470.0, grain="monthly"),
    ]

    share = [r for r in derive_metrics(records) if r.metric == "wine_share"]

    assert round(share[0].value, 2) == 6.20


def test_the_default_definitions_cannot_be_mutated_by_a_caller():
    from atlas_core.derived_metric import DEFAULT_DERIVED_METRICS

    assert isinstance(DEFAULT_DERIVED_METRICS, tuple)
