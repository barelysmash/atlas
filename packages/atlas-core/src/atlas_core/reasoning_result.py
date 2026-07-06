from dataclasses import dataclass, field

from atlas_core.decision import Decision
from atlas_core.insight import Insight
from atlas_core.observation import Observation


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    """Complete output of the Atlas reasoning pipeline."""

    observations: list[Observation] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)