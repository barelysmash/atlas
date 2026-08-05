from datetime import UTC, datetime

from atlas_core import (
    Decision,
    EvidenceItem,
    Insight,
    Metric,
    Observation,
    ReasoningResult,
    Recommendation,
)

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)


def test_create_reasoning_result():
    observation = Observation(
        domain="sales",
        subject="Fonda San Miguel",
        summary="wine_receipts was 50,000.",
        metrics=(Metric(name="wine_receipts", value=50000.0),),
        source_ref="tabc:Fonda San Miguel:2026-06",
        observed_at=OBSERVED_AT,
    )

    insight = Insight(
        domain="sales",
        statement="Wine remains an active revenue contributor.",
        confidence=0.80,
        evidence=(EvidenceItem.citing(observation, "wine_receipts"),),
        created_at=CREATED_AT,
    )

    decision = Decision(
        domain="sales",
        category="atlas.marketing",
        priority="low",
        confidence=0.80,
        summary="Continue promoting premium wine.",
        evidence=insight.evidence,
        derived_from=(insight.insight_id,),
        recommendations=(Recommendation(statement="Continue premium wine sampling."),),
        created_at=CREATED_AT,
    )

    result = ReasoningResult(
        observations=[observation],
        insights=[insight],
        decisions=[decision],
    )

    assert result.observations == [observation]
    assert result.insights == [insight]
    assert result.decisions == [decision]
