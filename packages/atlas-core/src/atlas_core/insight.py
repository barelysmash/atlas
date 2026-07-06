from dataclasses import dataclass, field

from atlas_core.observation import Observation


@dataclass(frozen=True, slots=True)
class Insight:
    """An interpretation supported by observations.

    Insights explain what observations likely mean.
    """

    summary: str
    confidence: float
    observations: list[Observation] = field(default_factory=list)