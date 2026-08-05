from datetime import UTC, datetime

from atlas_core import EvidenceItem, Insight, Metric, Observation
from atlas_core.decision import CONFIDENCE_FLOOR
from atlas_core.decision_engine import generate_decisions

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)

WINE_INSIGHT = "Wine remains an active revenue contributor."


def _observation(metric_name: str, value: float) -> Observation:
    return Observation(
        domain="sales",
        subject="Fonda San Miguel",
        summary=f"{metric_name} was {value:,.0f}.",
        metrics=(Metric(name=metric_name, value=value),),
        source_ref="tabc:Fonda San Miguel:2026-06",
        observed_at=OBSERVED_AT,
    )


def _insight(statement: str, confidence: float, metric_name: str) -> Insight:
    observation = _observation(metric_name, 50000.0)
    return Insight(
        domain="sales",
        statement=statement,
        confidence=confidence,
        evidence=(EvidenceItem.citing(observation, metric_name),),
        created_at=CREATED_AT,
    )


def test_generate_decisions_from_wine_insight():
    insight = _insight(WINE_INSIGHT, 0.80, "wine_receipts")
    decisions = generate_decisions([insight], now=NOW)
    assert len(decisions) == 1
    assert decisions[0].summary == "Continue promoting premium wine."
    assert decisions[0].confidence == 0.80


def test_decision_carries_a_registered_category():
    decision = generate_decisions(
        [_insight(WINE_INSIGHT, 0.80, "wine_receipts")], now=NOW
    )[0]
    assert decision.category == "atlas.marketing"


def test_decision_inherits_evidence_from_its_insight():
    insight = _insight(WINE_INSIGHT, 0.80, "wine_receipts")
    decision = generate_decisions([insight], now=NOW)[0]
    assert decision.evidence == insight.evidence


def test_decision_records_the_insight_it_rests_on():
    insight = _insight(WINE_INSIGHT, 0.80, "wine_receipts")
    decision = generate_decisions([insight], now=NOW)[0]
    assert decision.rests_on(insight.insight_id)


def test_recommendation_is_structured():
    decision = generate_decisions(
        [_insight(WINE_INSIGHT, 0.80, "wine_receipts")], now=NOW
    )[0]
    rec = decision.recommendations[0]
    assert rec.statement == "Continue premium wine sampling."
    assert rec.action_type == "launch_promotion"
    assert rec.recommendation_id.startswith("rec_")


def test_an_irreversible_recommendation_requires_approval():
    decision = generate_decisions(
        [_insight(WINE_INSIGHT, 0.80, "wine_receipts")], now=NOW
    )[0]
    assert decision.recommendations[0].reversible is False
    assert decision.requires_approval is True


def test_the_clock_is_injectable():
    decision = generate_decisions(
        [_insight(WINE_INSIGHT, 0.80, "wine_receipts")], now=NOW
    )[0]
    assert decision.created_at == NOW


def test_generate_decisions_ignores_unknown_insights():
    assert (
        generate_decisions(
            [_insight("Beer receipts were recorded.", 0.50, "beer_receipts")], now=NOW
        )
        == []
    )


def test_insights_below_the_confidence_floor_produce_no_decision():
    thin = _insight(WINE_INSIGHT, CONFIDENCE_FLOOR - 0.01, "wine_receipts")
    assert generate_decisions([thin], now=NOW) == []


def test_an_insight_at_the_floor_still_produces_a_decision():
    at_floor = _insight(WINE_INSIGHT, CONFIDENCE_FLOOR, "wine_receipts")
    assert len(generate_decisions([at_floor], now=NOW)) == 1
