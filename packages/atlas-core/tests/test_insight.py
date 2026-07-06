from atlas_core import Insight, Observation


def test_create_insight_from_observations():
    observation = Observation(
        category="operations",
        metric="wine_receipts",
        value=50000.0,
        summary="Wine receipts were $50,000.",
        evidence=["TABC June 2026"],
    )

    insight = Insight(
        summary="Wine performance is meaningful enough to monitor.",
        confidence=0.8,
        observations=[observation],
    )

    assert insight.summary == "Wine performance is meaningful enough to monitor."
    assert insight.confidence == 0.8
    assert insight.observations == [observation]