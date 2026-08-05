from dataclasses import dataclass, field

from atlas_core.data_gap import DataGap
from atlas_core.decision import Decision
from atlas_core.insight import Insight
from atlas_core.observation import Observation


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    """Complete output of the Atlas reasoning pipeline.

    gaps records what the pipeline could not evaluate. It is part of the
    result, not an error condition: what a goal cannot see is as much a
    finding as what it can.
    """

    observations: list[Observation] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    gaps: list[DataGap] = field(default_factory=list)
