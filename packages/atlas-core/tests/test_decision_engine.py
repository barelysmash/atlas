from datetime import datetime, timezone

from atlas_core import EvidenceItem, Insight, Metric, Observation
from atlas_core.decision_engine import generate_decisions

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)


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
    return Insight(
        domain="sales",
        statement=statement,
        confidence=confidence,
        evidence=(
            EvidenceItem.citing(_observation(metric_name, 50000.0), metric_name),
        ),
        created_at=CREATED_AT,
    )


def test_generate_decisions_from_wine_insight():
    insight = _insight(
        "Wine remains an active revenue contributor.", 0.80, "wine_receipts"
    )

    decisions = generate_decisions([insight])

    assert len(decisions) == 1
    assert decisions[0].summary == "Continue promoting premium wine."
    assert decisions[0].confidence == 0.80
    assert decisions[0].recommendations == ["Continue premium wine sampling."]
    assert decisions[0].insights == [insight]


def test_generate_decisions_ignores_unknown_insights():
    insight = _insight("Beer receipts were recorded.", 0.50, "beer_receipts")
    assert generate_decisions([insight]) == []
