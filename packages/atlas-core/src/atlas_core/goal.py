from collections.abc import Sequence
from dataclasses import dataclass, field

INCREASE = "increase"
DECREASE = "decrease"
MAINTAIN = "maintain"

TARGET_DIRECTIONS = (INCREASE, DECREASE, MAINTAIN)

UP = "up"
DOWN = "down"
FLAT = "flat"

OBSERVED_DIRECTIONS = (UP, DOWN, FLAT)

PRIORITIES = ("low", "medium", "high")

FAVORABLE_MOVES = {
    INCREASE: UP,
    DECREASE: DOWN,
    MAINTAIN: FLAT,
}

# How a metric stands relative to its target.
FAVORABLE = "favorable"
STALLED = "stalled"
UNFAVORABLE = "unfavorable"

ASSESSMENTS = (FAVORABLE, STALLED, UNFAVORABLE)


def movement_from_delta(delta: float | None) -> tuple[str | None, float | None]:
    """Translate a Metric delta into an observed direction and a change.

    JAM expresses delta as a fraction: 0.12 is a twelve percent rise. A
    MetricTarget tolerance is a dead band in percentage points, because that is
    how a band is stated in practice. Feeding one into the other without
    converting makes a twelve percent rise sit inside a five point band and
    read as flat, so the conversion happens here, once, at the boundary.
    """
    if delta is None:
        return None, None
    if delta > 0:
        direction = UP
    elif delta < 0:
        direction = DOWN
    else:
        direction = FLAT
    return direction, delta * 100


@dataclass(frozen=True, slots=True)
class MetricTarget:
    """The direction a metric must move to serve a goal.

    tolerance is a dead band in percentage points. Movement smaller than the
    tolerance counts as no movement at all, which is what makes a maintain
    target usable: real measurements are never exactly flat, so without a band
    every period would read as a deviation.
    """

    metric: str
    direction: str
    tolerance: float = 0.0

    def __post_init__(self) -> None:
        if not self.metric:
            raise ValueError("metric is required")
        if self.direction not in TARGET_DIRECTIONS:
            raise ValueError(f"direction must be one of {TARGET_DIRECTIONS}")
        if self.tolerance < 0:
            raise ValueError("tolerance cannot be negative")


@dataclass(frozen=True, slots=True)
class Goal:
    """An explicit outcome the organisation is pursuing.

    Goals determine what information matters, how decisions are evaluated, and
    what constitutes success. Reasoning without a goal can produce
    observations, but it has no basis for concluding anything from them.

    A Goal is reasoning apparatus, not a contract object. It carries targets,
    tolerances, and assessment logic, and it does not appear in JAM's Insight
    schema: serialising it would put the engine's configuration alongside its
    conclusion.
    """

    summary: str
    targets: tuple[MetricTarget, ...] = field(default_factory=tuple)
    priority: str = "medium"

    @classmethod
    def create(
        cls,
        summary: str,
        targets: Sequence[MetricTarget] | None = None,
        priority: str = "medium",
    ) -> "Goal":
        if not summary:
            raise ValueError("summary is required")
        if priority not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")

        return cls(
            summary=summary,
            targets=tuple(targets or ()),
            priority=priority,
        )

    @property
    def metrics(self) -> list[str]:
        """The metrics this goal makes relevant."""
        return [target.metric for target in self.targets]

    def tracks(self, metric: str) -> bool:
        """Whether this goal makes the metric relevant."""
        return any(target.metric == metric for target in self.targets)

    def target_for(self, metric: str) -> MetricTarget | None:
        """The target for a metric, or None when the goal does not track it."""
        for target in self.targets:
            if target.metric == metric:
                return target

        return None

    def assess(
        self,
        metric: str,
        direction: str | None,
        change: float | None = None,
    ) -> str | None:
        """How an observed move stands relative to this goal.

        Three outcomes, not two. A metric moving the wrong way and a metric not
        moving at all are different situations: one is a reversal, the other is
        a stall. Collapsing them means a goal that wants growth reports a flat
        month as a decline and calls for intervention on a number that did not
        move.

        Movement within the target tolerance is treated as flat, so a
        rounding-scale wobble neither counts as progress toward an increase
        target nor as a deviation from a maintain target.

        Returns None when the goal does not track the metric, or when the
        observation carries no direction: an honest "cannot say" rather than a
        false reading.
        """
        target = self.target_for(metric)

        if target is None or direction not in OBSERVED_DIRECTIONS:
            return None

        if change is not None and abs(change) <= target.tolerance:
            direction = FLAT

        if direction == FAVORABLE_MOVES[target.direction]:
            return FAVORABLE

        # A directional target that saw no movement has stalled rather than
        # reversed. A maintain target has no stalled state: not moving is
        # precisely what it asked for, and any movement beyond tolerance is a
        # genuine deviation.
        if direction == FLAT:
            return STALLED

        return UNFAVORABLE

    def is_favorable(
        self,
        metric: str,
        direction: str | None,
        change: float | None = None,
    ) -> bool | None:
        """Whether an observed move serves this goal.

        Retained for callers that only need the binary reading. Prefer assess,
        which distinguishes a stall from a reversal.
        """
        assessment = self.assess(metric, direction, change)

        if assessment is None:
            return None

        return assessment == FAVORABLE
