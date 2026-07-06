from atlas_core.decision import Decision
from atlas_core.insight import Insight


def generate_decisions(insights: list[Insight]) -> list[Decision]:
    """Generate deterministic decisions from insights."""

    decisions: list[Decision] = []

    for insight in insights:
        if insight.summary == "Wine remains an active revenue contributor.":
            decisions.append(
                Decision(
                    summary="Continue promoting premium wine.",
                    confidence=0.80,
                    recommendations=[
                        "Continue premium wine sampling."
                    ],
                    insights=[insight],
                )
            )

    return decisions