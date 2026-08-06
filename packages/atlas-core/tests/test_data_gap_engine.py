from datetime import UTC, datetime

from atlas_core import Goal, Metric, MetricTarget, Observation
from atlas_core.data_gap import NO_DATA, SINGLE_PERIOD
from atlas_core.data_gap_engine import generate_data_gaps
from atlas_core.insight_engine import generate_insights

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)

GROW_WINE = Goal.create(
    summary="Grow beverage revenue.",
    targets=[
        MetricTarget("wine_receipts", "increase"),
        MetricTarget("premium_mix", "increase"),
    ],
    priority="high",
    category="atlas.marketing",
)


def make_observation(metric: str, direction: str | None) -> Observation:
    return Observation(
        domain="sales",
        subject="Fonda San Miguel",
        summary=f"{metric} moved.",
        metrics=(
            Metric(
                name=metric,
                value=50000.0,
                delta=0.02 if direction else None,
            ),
        ),
        source_ref="tabc:fsm:2026-06",
        observed_at=OBSERVED_AT,
        periods=("2026-06",),
    )


def test_metric_with_no_data_is_reported():
    gaps = generate_data_gaps([make_observation("wine_receipts", "up")], [GROW_WINE])

    assert len(gaps) == 1
    assert gaps[0].metric == "premium_mix"
    assert gaps[0].reason == NO_DATA
    assert gaps[0].summary == (
        "'Grow beverage revenue.' tracks premium_mix, but no data was supplied for it."
    )


def test_metric_with_one_period_is_reported_separately():
    gaps = generate_data_gaps([make_observation("wine_receipts", None)], [GROW_WINE])
    reasons = {gap.metric: gap.reason for gap in gaps}

    assert reasons == {
        "wine_receipts": SINGLE_PERIOD,
        "premium_mix": NO_DATA,
    }


def test_evaluable_metric_produces_no_gap():
    observations = [
        make_observation("wine_receipts", "up"),
        make_observation("premium_mix", "up"),
    ]

    assert generate_data_gaps(observations, [GROW_WINE]) == []


def test_no_goals_means_no_gaps():
    assert generate_data_gaps([make_observation("wine_receipts", "up")], []) == []


def test_every_goal_metric_is_either_interpreted_or_reported():
    """Nothing a goal tracks may be passed over in silence."""
    observations = [
        make_observation("wine_receipts", "up"),
        make_observation("premium_mix", None),
    ]

    insights = generate_insights(observations, [GROW_WINE])
    gaps = generate_data_gaps(observations, [GROW_WINE])

    interpreted = {
        item.metric.name
        for insight in insights
        for item in insight.evidence
        if item.metric is not None
    }
    reported = {gap.metric for gap in gaps}

    assert interpreted | reported == set(GROW_WINE.metrics)
    assert interpreted & reported == set()
