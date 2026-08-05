from datetime import UTC, datetime

from atlas_core.decision import CONFIDENCE_FLOOR, Decision
from atlas_core.insight import Insight
from atlas_core.recommendation import Recommendation

WINE_INSIGHT = "Wine remains an active revenue contributor."


def generate_decisions(
    insights: list[Insight],
    now: datetime | None = None,
) -> list[Decision]:
    """Generate deterministic decisions from insights.

    A Decision inherits its evidence from the Insight it rests on, so the
    Observations it cites are the ones the interpretation actually used, and
    it records the Insight in derived_from. Evidence is what was measured;
    derived_from is what was concluded.

    Insights below the emission floor produce no Decision. An interpretation
    worth recording is not always an action worth recommending.
    """
    moment = datetime.now(UTC) if now is None else now
    decisions: list[Decision] = []
    for insight in insights:
        if insight.statement != WINE_INSIGHT:
            continue
        if insight.confidence < CONFIDENCE_FLOOR:
            continue
        decisions.append(
            Decision(
                domain=insight.domain,
                category="atlas.marketing",
                priority="low",
                confidence=insight.confidence,
                summary="Continue promoting premium wine.",
                rationale=(
                    "Wine receipts remain a material share of revenue and the "
                    "sampling program is already in place. Continuing costs "
                    "little and stopping would forfeit an established lift."
                ),
                evidence=insight.evidence,
                derived_from=(insight.insight_id,),
                recommendations=(
                    Recommendation(
                        statement="Continue premium wine sampling.",
                        action_type="launch_promotion",
                        reversible=False,
                    ),
                ),
                created_at=moment,
            )
        )
    return decisions
