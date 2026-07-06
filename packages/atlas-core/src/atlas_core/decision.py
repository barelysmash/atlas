from dataclasses import dataclass, field

from atlas_core.insight import Insight


@dataclass(frozen=True, slots=True)
class Decision:
    """A recommended course of action supported by insights."""

    summary: str
    confidence: float
    recommendations: list[str] = field(default_factory=list)
    insights: list[Insight] = field(default_factory=list)