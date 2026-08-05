from dataclasses import dataclass

NO_DATA = "no_data"
SINGLE_PERIOD = "single_period"

REASONS = (NO_DATA, SINGLE_PERIOD)


@dataclass(frozen=True, slots=True)
class DataGap:
    """A goal metric that could not be evaluated.

    When evidence is weak, uncertainty should be communicated honestly. A goal
    whose metric has no data must be reported as unevaluated rather than passed
    over in silence, because silence is indistinguishable from "nothing is
    wrong".
    """

    goal: str
    metric: str
    reason: str
    summary: str
