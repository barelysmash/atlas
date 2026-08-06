from datetime import UTC, datetime

from atlas_core import Goal, Metric, MetricTarget, Observation
from atlas_core.insight_engine import generate_insights

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)

GROW_WINE = Goal.create(
    summary="Grow beverage revenue.",
    targets=[MetricTarget("wine_receipts", "increase")],
    priority="high",
    category="atlas.marketing",
)


def make_observation(
    metric: str,
    direction: str | None,
    periods: tuple[str, ...],
    change: float = 2.0,
    summary: str = "",
) -> Observation:
    sign = {"up": 1, "down": -1}.get(direction or "", 0)
    return Observation(
        domain="sales",
        subject="Fonda San Miguel",
        summary=summary or f"{metric} moved.",
        metrics=(
            Metric(
                name=metric,
                value=50000.0,
                delta=sign * change / 100 if direction else None,
            ),
        ),
        source_ref=" ".join(f"tabc:fsm:{period}" for period in periods),
        observed_at=OBSERVED_AT,
        periods=periods,
    )


def test_no_goals_means_no_insights():
    observation = make_observation("wine_receipts", "up", ("2026-06",))

    assert generate_insights([observation], []) == []


def test_favorable_movement_supports_the_goal():
    observation = make_observation("wine_receipts", "up", ("2026-06",))

    insights = generate_insights([observation], [GROW_WINE], now=NOW)

    assert len(insights) == 1
    assert insights[0].statement == (
        "wine_receipts is trending in support of 'Grow beverage revenue.'."
    )
    assert insights[0].goal == GROW_WINE
    assert insights[0].assessment == "favorable"


def test_unfavorable_movement_is_reported_as_such():
    observation = make_observation("wine_receipts", "down", ("2026-06",))

    insights = generate_insights([observation], [GROW_WINE], now=NOW)

    assert insights[0].statement == (
        "wine_receipts is trending against 'Grow beverage revenue.'."
    )


def test_untracked_metrics_produce_no_insight():
    observation = make_observation("beer_receipts", "up", ("2026-06",))

    assert generate_insights([observation], [GROW_WINE], now=NOW) == []


def test_observation_without_movement_produces_no_insight():
    observation = make_observation("wine_receipts", None, ("2026-06",))

    assert generate_insights([observation], [GROW_WINE], now=NOW) == []


def test_observations_of_one_metric_aggregate_into_one_insight():
    latest = make_observation("wine_receipts", "up", ("2026-05", "2026-06"))
    streak = make_observation(
        "wine_receipts", "up", ("2026-03", "2026-04", "2026-05", "2026-06")
    )

    insights = generate_insights([latest, streak], [GROW_WINE], now=NOW)

    assert len(insights) == 1
    assert len(insights[0].evidence) == 2


def test_confidence_rises_with_corroborating_periods():
    one_period = generate_insights(
        [make_observation("wine_receipts", "up", ("2026-06",))],
        [GROW_WINE],
        now=NOW,
    )
    four_periods = generate_insights(
        [
            make_observation(
                "wine_receipts",
                "up",
                ("2026-03", "2026-04", "2026-05", "2026-06"),
            )
        ],
        [GROW_WINE],
        now=NOW,
    )

    assert one_period[0].confidence == 0.5
    assert four_periods[0].confidence == 0.8


def test_periods_shared_between_observations_are_counted_once():
    """Two observations of one metric may rest on overlapping periods."""
    latest = make_observation("wine_receipts", "up", ("2026-05", "2026-06"))
    streak = make_observation(
        "wine_receipts", "up", ("2026-03", "2026-04", "2026-05", "2026-06")
    )

    insights = generate_insights([latest, streak], [GROW_WINE], now=NOW)

    # Four distinct periods across the two, not six.
    assert insights[0].confidence == 0.8


def test_confidence_is_capped_below_certainty():
    periods = tuple(f"2026-{month:02d}" for month in range(1, 13))

    insights = generate_insights(
        [make_observation("wine_receipts", "up", periods)], [GROW_WINE], now=NOW
    )

    assert insights[0].confidence == 0.9


def test_one_metric_can_serve_two_goals():
    also_grow = Goal.create(
        summary="Raise total receipts.",
        targets=[MetricTarget("wine_receipts", "increase")],
        category="atlas.marketing",
    )
    observation = make_observation("wine_receipts", "up", ("2026-06",))

    insights = generate_insights([observation], [GROW_WINE, also_grow], now=NOW)

    assert len(insights) == 2
    assert [insight.goal for insight in insights] == [GROW_WINE, also_grow]


def test_a_sustained_streak_outweighs_one_quiet_period():
    """A small latest move inside the band must not overturn a long trend."""
    banded = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase", tolerance=2.0)],
        category="atlas.marketing",
    )

    latest = make_observation("wine_receipts", "up", ("2026-05", "2026-06"), change=1.0)
    streak = make_observation(
        "wine_receipts",
        "up",
        ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"),
        change=22.0,
    )

    insights = generate_insights([latest, streak], [banded], now=NOW)

    assert insights[0].statement == (
        "wine_receipts is trending in support of 'Grow beverage revenue.'."
    )


def test_without_a_streak_the_latest_period_still_decides():
    """A move inside the band is a stall, not a reversal."""
    banded = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase", tolerance=2.0)],
        category="atlas.marketing",
    )

    latest = make_observation("wine_receipts", "up", ("2026-05", "2026-06"), change=1.0)

    insights = generate_insights([latest], [banded], now=NOW)

    assert insights[0].statement == (
        "wine_receipts is flat against 'Grow beverage revenue.'."
    )
    assert insights[0].assessment == "stalled"


def test_the_clock_is_injectable():
    observation = make_observation("wine_receipts", "up", ("2026-06",))

    assert generate_insights([observation], [GROW_WINE], now=NOW)[0].created_at == NOW


def test_the_insight_cites_the_observation_it_rests_on():
    observation = make_observation("wine_receipts", "up", ("2026-06",))

    insight = generate_insights([observation], [GROW_WINE], now=NOW)[0]

    assert insight.cites(observation.observation_id)
    assert insight.evidence[0].metric == observation.get_metric("wine_receipts")
