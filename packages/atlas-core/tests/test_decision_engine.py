from datetime import UTC, datetime

from atlas_core import (
    EvidenceItem,
    Goal,
    Insight,
    Metric,
    MetricTarget,
    Observation,
)
from atlas_core.decision_engine import generate_decisions

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)

GROW_WINE = Goal.create(
    summary="Grow beverage revenue.",
    targets=[MetricTarget("wine_receipts", "increase")],
    priority="high",
    category="atlas.marketing",
)


def make_insight(
    assessment: str | None,
    goal: Goal | None = GROW_WINE,
    confidence: float = 0.60,
) -> Insight:
    observation = Observation(
        domain="beverage",
        subject="Fonda San Miguel",
        summary="wine_receipts moved.",
        metrics=(Metric(name="wine_receipts", value=50000.0, delta=0.02),),
        source_ref="tabc:fsm:2026-05 tabc:fsm:2026-06",
        observed_at=OBSERVED_AT,
        periods=("2026-05", "2026-06"),
    )

    return Insight(
        domain="beverage",
        statement="wine_receipts is trending.",
        confidence=confidence,
        evidence=(EvidenceItem.citing(observation, "wine_receipts"),),
        created_at=CREATED_AT,
        goal=goal,
        assessment=assessment,
    )


def test_favorable_movement_recommends_sustaining():
    decisions = generate_decisions([make_insight("favorable")], now=NOW)

    assert len(decisions) == 1
    assert decisions[0].summary == "Sustain the current approach to wine_receipts."
    assert decisions[0].recommendations[0].statement == (
        "Identify what is driving wine_receipts and protect it."
    )


def test_unfavorable_movement_recommends_intervention():
    decisions = generate_decisions([make_insight("unfavorable")], now=NOW)

    assert decisions[0].summary == "Intervene on wine_receipts."
    assert [rec.statement for rec in decisions[0].recommendations] == [
        "Investigate what changed in wine_receipts since 2026-05.",
        "Choose one corrective action for wine_receipts and measure it.",
    ]


def test_intervention_inherits_the_goal_priority():
    decisions = generate_decisions([make_insight("unfavorable")], now=NOW)

    assert decisions[0].priority == "high"


def test_sustaining_is_one_priority_step_below_intervening():
    decisions = generate_decisions([make_insight("favorable")], now=NOW)

    assert decisions[0].priority == "medium"


def test_a_stall_calls_for_an_experiment_not_a_correction():
    """Nothing has gone wrong that could be put right."""
    decisions = generate_decisions([make_insight("stalled")], now=NOW)

    assert decisions[0].summary == "Try something new on wine_receipts."
    assert decisions[0].recommendations[0].statement == (
        "Design one experiment to move wine_receipts and predict its direction."
    )
    assert decisions[0].priority == "medium"


def test_the_decision_carries_the_category_its_goal_declared():
    decisions = generate_decisions([make_insight("favorable")], now=NOW)

    assert decisions[0].category == "atlas.marketing"


def test_the_decision_inherits_evidence_and_confidence_from_its_insight():
    insight = make_insight("favorable")

    decisions = generate_decisions([insight], now=NOW)

    assert decisions[0].evidence == insight.evidence
    assert decisions[0].confidence == 0.60
    assert decisions[0].rests_on(insight.insight_id)


def test_insight_without_a_goal_yields_no_decision():
    assert generate_decisions([make_insight("favorable", goal=None)], now=NOW) == []


def test_a_goal_without_a_category_yields_no_decision():
    """A Decision must say what kind of action it recommends."""
    uncategorised = Goal.create(
        summary="Grow beverage revenue.",
        targets=[MetricTarget("wine_receipts", "increase")],
    )

    assert generate_decisions([make_insight("favorable", uncategorised)], now=NOW) == []


def test_an_insight_below_the_confidence_floor_yields_no_decision():
    """A tentative interpretation is worth recording; acting on it is not."""
    thin = make_insight("favorable", confidence=0.2)

    assert generate_decisions([thin], now=NOW) == []


def test_the_clock_is_injectable():
    decisions = generate_decisions([make_insight("favorable")], now=NOW)

    assert decisions[0].created_at == NOW
