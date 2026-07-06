from atlas_core import Decision, ExecutiveBrief, Insight, Observation, ReasoningResult


def test_executive_brief_from_reasoning():
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

    brief = ExecutiveBrief.from_reasoning(result)

    assert "# Executive Brief" in brief.markdown
    assert "- wine_receipts was 50,000." in brief.markdown
    assert "- Wine remains an active revenue contributor." in brief.markdown
    assert "- Continue promoting premium wine." in brief.markdown