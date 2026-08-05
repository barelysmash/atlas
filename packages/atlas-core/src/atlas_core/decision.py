from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from atlas_core.evidence_item import EvidenceItem
from atlas_core.identifiers import new_decision_id
from atlas_core.recommendation import Recommendation

Priority = Literal["critical", "high", "medium", "low"]

# A Decision below this confidence should not be emitted. Recommending action
# on thin grounds is worse than staying silent. Insights have no such floor.
CONFIDENCE_FLOOR = 0.30


@dataclass(frozen=True, slots=True)
class Decision:
    """A recommended course of action, shaped to the JAM contract.

    ``summary`` is imperative, in deliberate contrast to an Insight's
    declarative ``statement``. It lands verbatim in the Executive Brief.

    ``evidence`` is what was measured. ``derived_from`` is what was concluded.
    The two arrays answer different questions and both are carried.

    ``priority`` is the cost of acting late, not the magnitude of impact.
    """

    domain: str
    category: str
    priority: Priority
    confidence: float
    summary: str
    evidence: tuple[EvidenceItem, ...]
    recommendations: tuple[Recommendation, ...]
    created_at: datetime
    rationale: str | None = None
    derived_from: tuple[str, ...] = ()
    requires_approval: bool = True
    decision_id: str = field(default_factory=new_decision_id, compare=False)

    def __post_init__(self) -> None:
        if not self.evidence:
            raise ValueError("a Decision with no evidence is an opinion")
        if not self.recommendations:
            raise ValueError("a Decision must recommend at least one action")
        if not self.requires_approval:
            irreversible = [
                r.recommendation_id for r in self.recommendations if not r.reversible
            ]
            if irreversible:
                raise ValueError(
                    "requires_approval is False but these recommendations are "
                    "not reversible: " + ", ".join(irreversible)
                )

    def cites(self, observation_id: str) -> bool:
        """Whether this Decision rests on that Observation."""
        return any(item.observation_id == observation_id for item in self.evidence)

    def rests_on(self, insight_id: str) -> bool:
        """Whether this Decision was derived from that Insight."""
        return insight_id in self.derived_from
