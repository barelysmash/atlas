from datetime import UTC, datetime

from atlas_core import Goal, MetricTarget, OperationalRecord, ReasoningResult
from atlas_core.reasoning_pipeline import ReasoningPipeline

NOW = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)

GROW_WINE = Goal.create(
    summary="Grow beverage revenue.",
    targets=[MetricTarget("wine_receipts", "increase")],
    priority="high",
    category="atlas.marketing",
)


def rising_months(count: int = 6) -> list[OperationalRecord]:
    return [
        OperationalRecord.create(
            source="tabc",
            entity="Fonda San Miguel",
            period=f"2026-{month:02d}",
            category="beverage",
            metric="wine_receipts",
            value=40000.0 + month * 2000,
            grain="monthly",
        )
        for month in range(1, count + 1)
    ]


def test_a_single_record_still_produces_a_result():
    result = ReasoningPipeline([GROW_WINE]).run(rising_months(1)[0], now=NOW)

    assert isinstance(result, ReasoningResult)
    assert len(result.observations) == 1


def test_a_window_observes_change_over_time():
    result = ReasoningPipeline([GROW_WINE]).run_window(rising_months(), now=NOW)

    assert len(result.observations) == 2
    assert len(result.insights) == 1
    assert len(result.decisions) == 1


def test_a_rising_metric_is_sustained_rather_than_corrected():
    result = ReasoningPipeline([GROW_WINE]).run_window(rising_months(), now=NOW)

    assert result.insights[0].assessment == "favorable"
    assert result.decisions[0].summary == (
        "Sustain the current approach to wine_receipts."
    )
    assert result.decisions[0].category == "atlas.marketing"


def test_without_goals_a_pipeline_observes_but_concludes_nothing():
    """Without a goal there is no basis on which to call movement good or bad."""
    result = ReasoningPipeline().run_window(rising_months(), now=NOW)

    assert result.observations
    assert result.insights == []
    assert result.decisions == []


def test_a_goal_metric_with_no_data_is_reported_as_a_gap():
    watching_food = Goal.create(
        summary="Hold food cost.",
        targets=[MetricTarget("food_cost_pct", "decrease")],
        category="atlas.vendor",
    )

    result = ReasoningPipeline([watching_food]).run_window(rising_months(), now=NOW)

    assert [gap.metric for gap in result.gaps] == ["food_cost_pct"]
    assert result.insights == []
