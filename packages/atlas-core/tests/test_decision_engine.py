from atlas_core import Insight, Observation
from atlas_core.decision_engine import generate_decisions


def test_generate_decisions_from_wine_insight():
    observation = Observation(
        category="sales",
        metric="wine_receipts",
        value=50000.0,
        summary="wine_receipts was 50,000.",
        evidence=["tabc:Fonda San Miguel:2026-06"],
    )

    insight = Insight(
        summary="Wine remains an active revenue contributor.",
        confidence=0.80,
        observations=[observation],
    )

    decisions = generate_decisions([insight])

    assert len(decisions) == 1
    assert decisions[0].summary == "Continue promoting premium wine."
    assert decisions[0].confidence == 0.80
    assert decisions[0].recommendations == [
        "Continue premium wine sampling."
    ]
    assert decisions[0].insights == [insight]


def test_generate_decisions_ignores_unknown_insights():
    observation = Observation(
        category="sales",
        metric="beer_receipts",
        value=25000.0,
        summary="beer_receipts was 25,000.",
        evidence=["tabc:Fonda San Miguel:2026-06"],
    )

    insight = Insight(
        summary="Beer receipts were recorded.",
        confidence=0.50,
        observations=[observation],
    )

    decisions = generate_decisions([insight])

    assert decisions == []