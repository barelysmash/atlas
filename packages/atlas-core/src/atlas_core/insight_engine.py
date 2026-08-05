from datetime import UTC, datetime

from atlas_core.evidence_item import EvidenceItem
from atlas_core.insight import Insight
from atlas_core.observation import Observation

WINE_RECEIPTS = "wine_receipts"


def generate_insights(
    observations: list[Observation],
    now: datetime | None = None,
) -> list[Insight]:
    """Generate deterministic insights from observations.

    The clock is injectable so a run can be reproduced.
    """
    moment = datetime.now(UTC) if now is None else now
    insights: list[Insight] = []
    for observation in observations:
        if observation.has_metric(WINE_RECEIPTS):
            insights.append(
                Insight(
                    domain=observation.domain,
                    statement="Wine remains an active revenue contributor.",
                    confidence=0.80,
                    evidence=(EvidenceItem.citing(observation, WINE_RECEIPTS),),
                    created_at=moment,
                    method="threshold_breach",
                )
            )
    return insights
