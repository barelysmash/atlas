from atlas_core import Observation
from atlas_core.insight_engine import generate_insights


def test_generate_insights_from_wine_observation():
    observation = Observation(
        category="sales",
        metric="wine_receipts",
        value=50000.0,
        summary="wine_receipts was 50,000.",
        evidence=["tabc:Fonda San Miguel:2026-06"],
    )

    insights = generate_insights([observation])

    assert len(insights) == 1
    assert insights[0].summary == "Wine remains an active revenue contributor."
    assert insights[0].confidence == 0.80
    assert insights[0].observations == [observation]


def test_generate_insights_ignores_unknown_metrics():
    observation = Observation(
        category="sales",
        metric="unknown_metric",
        value=1.0,
        summary="unknown_metric was 1.",
        evidence=["test"],
    )

    insights = generate_insights([observation])

    assert insights == []