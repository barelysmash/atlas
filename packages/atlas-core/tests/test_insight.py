from datetime import datetime, timezone

from atlas_core import Insight, Metric, Observation

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def test_create_insight_from_observations():
    observation = Observation(
        domain="operations",
        subject="Fonda San Miguel",
        summary="Wine receipts were $50,000.",
        metrics=(Metric(name="wine_receipts", value=50000.0),),
        source_ref="TABC June 2026",
        observed_at=OBSERVED_AT,
    )

    insight = Insight(
        summary="Wine performance is meaningful enough to monitor.",
        confidence=0.8,
        observations=[observation],
    )

    assert insight.summary == "Wine performance is meaningful enough to monitor."
    assert insight.confidence == 0.8
    assert insight.observations == [observation]
