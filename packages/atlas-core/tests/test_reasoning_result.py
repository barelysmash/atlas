from datetime import datetime, timezone

from atlas_core import (
    Decision,
    EvidenceItem,
    Insight,
    Metric,
    Observation,
    ReasoningResult,
)

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)


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
        summary="Continue promoting premium wine.",
        confidence=0.80,
        recommendations=["Continue premium wine sampling."],
        insights=[insight],
    )

    result = ReasoningResult(
        observations=[observation],
        insights=[insight],
        decisions=[decision],
    )

    assert result.observations == [observation]
    assert result.insights == [insight]
    assert result.decisions == [decision]
