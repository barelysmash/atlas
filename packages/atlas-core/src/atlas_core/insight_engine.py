from datetime import UTC, datetime

from atlas_core.evidence_item import EvidenceItem
from atlas_core.goal import (
    FAVORABLE,
    STALLED,
    UNFAVORABLE,
    Goal,
    movement_from_delta,
)
from atlas_core.insight import Insight
from atlas_core.observation import Observation

TREND_PHRASES = {
    FAVORABLE: "trending in support of",
    STALLED: "flat against",
    UNFAVORABLE: "trending against",
}

BASE_CONFIDENCE = 0.5
CONFIDENCE_STEP = 0.1
MAX_CONFIDENCE = 0.9


def _distinct_periods(observations: list[Observation]) -> list[str]:
    periods: list[str] = []

    for observation in observations:
        for period in observation.periods:
            if period not in periods:
                periods.append(period)

    return periods


def _confidence(observations: list[Observation]) -> float:
    """Scale confidence with the amount of corroborating evidence.

    One period of evidence is a data point; several periods pointing the same
    way is a pattern. Confidence is capped below certainty because a
    deterministic rule cannot rule out a cause it never considered.
    """
    periods = len(_distinct_periods(observations))

    return min(
        BASE_CONFIDENCE + CONFIDENCE_STEP * max(periods - 1, 0),
        MAX_CONFIDENCE,
    )


def _best_evidenced(observations: list[Observation]) -> Observation:
    """The observation resting on the most periods.

    A metric can be described by more than one observation: a single period's
    move and a streak across several. Judging by the latest move alone lets one
    quiet period inside the tolerance band overturn a sustained trend, so the
    broadest observation decides. Ties fall to the most recent, listed first.
    """
    return max(observations, key=lambda observation: len(observation.periods))


def _movement(observation: Observation, metric: str) -> tuple[str | None, float | None]:
    """The direction and change a metric shows, read from its delta."""
    measured = observation.get_metric(metric)

    return movement_from_delta(measured.delta if measured else None)


def generate_insights(
    observations: list[Observation],
    goals: list[Goal] | None = None,
    now: datetime | None = None,
) -> list[Insight]:
    """Interpret observations against the goals they bear on.

    A goal determines which metrics matter and which direction counts as
    progress, so an observation only becomes an insight in the presence of a
    goal that tracks its metric. Observations of the same metric aggregate into
    one insight: several observations are evidence for a single hypothesis, not
    evidence for several.
    """
    moment = datetime.now(UTC) if now is None else now
    insights: list[Insight] = []

    for goal in goals or []:
        for metric in goal.metrics:
            supporting = [
                observation
                for observation in observations
                if observation.has_metric(metric)
            ]
            directed = [
                observation
                for observation in supporting
                if _movement(observation, metric)[0] is not None
            ]

            if not directed:
                continue

            strongest = _best_evidenced(directed)
            direction, change = _movement(strongest, metric)
            assessment = goal.assess(metric, direction, change)

            if assessment is None:
                continue

            insights.append(
                Insight(
                    domain=strongest.domain,
                    statement=(
                        f"{metric} is {TREND_PHRASES[assessment]} '{goal.summary}'."
                    ),
                    confidence=_confidence(supporting),
                    evidence=tuple(
                        EvidenceItem.citing(observation, metric)
                        for observation in supporting
                    ),
                    created_at=moment,
                    method="trend_extrapolation",
                    goal=goal,
                    assessment=assessment,
                )
            )

    return insights
