from atlas_core.insight import Insight
from atlas_core.observation import Observation


def generate_insights(observations: list[Observation]) -> list[Insight]:
    """Generate deterministic insights from observations."""

    insights: list[Insight] = []

    for observation in observations:
        if observation.metric == "wine_receipts":
            insights.append(
                Insight(
                    summary="Wine remains an active revenue contributor.",
                    confidence=0.80,
                    observations=[observation],
                )
            )

    return insights