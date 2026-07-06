from atlas_core import Decision, Insight, Observation


def test_create_decision_from_insights():
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