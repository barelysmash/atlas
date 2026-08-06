from dataclasses import dataclass, field
from datetime import datetime

from atlas_core.evidence_item import EvidenceItem
from atlas_core.goal import Goal
from atlas_core.identifiers import new_insight_id


@dataclass(frozen=True, slots=True)
class Insight:
    """An interpretation connecting Observations to a Decision.

    Insights explain what observations likely mean. An Insight can be wrong
    while every Observation behind it is right, which is why it is recorded
    separately.

    ``statement`` is declarative, never imperative: a Decision instructs, an
    Insight interprets. An Insight that reads as an instruction has skipped a
    step.

    An Insight has no category. Categories classify recommended action, and an
    Insight recommends nothing.

    ``goal`` records the goal the interpretation was formed under. Meaning is
    relative to a goal, and the same movement supports one and undermines
    another. It is internal reasoning state and does not serialise: JAM's
    Insight contract carries the conclusion, not the engine's configuration.

    Unlike a Decision, confidence has no emission floor. A tentative
    interpretation is worth recording; a tentative recommendation is not.
    """

    domain: str
    statement: str
    confidence: float
    evidence: tuple[EvidenceItem, ...]
    created_at: datetime
    method: str | None = None
    goal: Goal | None = None
    assessment: str | None = None
    insight_id: str = field(default_factory=new_insight_id, compare=False)

    def cites(self, observation_id: str) -> bool:
        """Whether this interpretation rests on that Observation."""
        return any(item.observation_id == observation_id for item in self.evidence)
