from datetime import UTC, datetime

from atlas_core.decision import CONFIDENCE_FLOOR, Decision, Priority
from atlas_core.goal import FAVORABLE, STALLED
from atlas_core.insight import Insight
from atlas_core.recommendation import Recommendation

# A goal's priority and a Decision's are different vocabularies: a goal has no
# critical tier. The mapping is written out rather than assumed, so that adding
# a tier to either one is a change someone has to make deliberately.
AS_DECISION_PRIORITY: dict[str, Priority] = {
    "high": "high",
    "medium": "medium",
    "low": "low",
}

# Sustaining what works is real but less urgent than correcting what does not,
# so it lands one step below the goal's own priority.
LOWER_PRIORITY: dict[str, Priority] = {
    "high": "medium",
    "medium": "low",
    "low": "low",
}


def _metric(insight: Insight) -> str | None:
    """The metric this interpretation is about, taken from its citations."""
    for item in insight.evidence:
        if item.metric is not None:
            return item.metric.name

    return None


def _earliest_period(insight: Insight) -> str | None:
    """The earliest period the interpretation rests on, for a since clause."""
    refs = [item.source_ref for item in insight.evidence if item.source_ref]

    if not refs:
        return None

    periods = sorted(ref.rsplit(":", 1)[-1] for ref in " ".join(refs).split())

    return periods[0] if periods else None


def generate_decisions(
    insights: list[Insight],
    now: datetime | None = None,
) -> list[Decision]:
    """Recommend action on each insight, judged against its goal.

    A metric moving against its goal calls for intervention at the goal's
    priority. A metric moving in support of its goal calls for sustaining what
    works, which is real but less urgent, so it lands one priority step lower.

    An insight without a goal produces nothing: there is no basis on which to
    call the movement good or bad. Nor does one whose goal has not declared a
    decision category, because a Decision must say what kind of action it
    recommends and only the goal knows.
    """
    moment = datetime.now(UTC) if now is None else now
    decisions: list[Decision] = []
    recommendations: tuple[Recommendation, ...]

    for insight in insights:
        goal = insight.goal
        metric = _metric(insight)

        if goal is None or goal.category is None or metric is None:
            continue
        if insight.assessment is None:
            continue
        if insight.confidence < CONFIDENCE_FLOOR:
            continue

        if insight.assessment == FAVORABLE:
            summary = f"Sustain the current approach to {metric}."
            recommendations = (
                Recommendation(
                    statement=f"Identify what is driving {metric} and protect it.",
                    reversible=True,
                ),
            )
            priority = LOWER_PRIORITY[goal.priority]
            rationale = (
                f"{metric} is moving in support of '{goal.summary}'. What is "
                "working is worth understanding before it stops working."
            )
        elif insight.assessment == STALLED:
            # A stall calls for a trial, not a correction. Nothing has gone
            # wrong that could be put right; what is missing is a cause of
            # movement, and the way to find one is to test it.
            summary = f"Try something new on {metric}."
            recommendations = (
                Recommendation(
                    statement=(
                        f"Design one experiment to move {metric} and predict "
                        "its direction."
                    ),
                    reversible=True,
                ),
            )
            priority = LOWER_PRIORITY[goal.priority]
            rationale = (
                f"{metric} is flat against '{goal.summary}'. Nothing has gone "
                "wrong that could be put right, so the next step is a trial "
                "rather than a correction."
            )
        else:
            since = _earliest_period(insight)
            window = f" since {since}" if since else ""
            summary = f"Intervene on {metric}."
            recommendations = (
                Recommendation(
                    statement=f"Investigate what changed in {metric}{window}.",
                    reversible=True,
                ),
                Recommendation(
                    statement=(
                        f"Choose one corrective action for {metric} and measure it."
                    ),
                ),
            )
            priority = AS_DECISION_PRIORITY[goal.priority]
            rationale = (
                f"{metric} is moving against '{goal.summary}'. The cause is "
                "not yet known, so the correction follows the investigation "
                "rather than replacing it."
            )

        decisions.append(
            Decision(
                domain=insight.domain,
                category=goal.category,
                priority=priority,
                confidence=insight.confidence,
                summary=summary,
                rationale=rationale,
                evidence=insight.evidence,
                derived_from=(insight.insight_id,),
                recommendations=recommendations,
                created_at=moment,
            )
        )

    return decisions
