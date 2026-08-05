from datetime import datetime, timezone

from atlas_core import Decision, EvidenceItem, Insight, Metric, Observation

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)


def test_create_decision_from_insights():
    observation = Observation(
        domain="operations",
        subject="Fonda San Miguel",
        summary="Wine receipts were $50,000.",
        metrics=(Metric(name="wine_receipts", value=50000.0),),
        source_ref="TABC June 2026",
        observed_at=OBSERVED_AT,
    )

    insight = Insight(
        domain="operations",
        statement="Wine performance is meaningful enough to monitor.",
        confidence=0.8,
        evidence=(EvidenceItem.citing(observation, "wine_receipts"),),
        created_at=CREATED_AT,
    )

    decision = Decision(
        summary="Continue monitoring wine performance.",
        confidence=0.75,
        recommendations=["Review wine receipts again next month."],
        insights=[insight],
    )

    assert decision.summary == "Continue monitoring wine performance."
    assert decision.confidence == 0.75
    assert decision.recommendations == ["Review wine receipts again next month."]
    assert decision.insights == [insight]
