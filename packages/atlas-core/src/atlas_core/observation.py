from dataclasses import dataclass, field

from atlas_core.identifiers import new_observation_id


@dataclass(frozen=True, slots=True)
class Observation:
    """A factual statement derived from evidence.

    Observations describe what happened.
    They do not interpret why it happened.

    ``observation_id`` is excluded from equality. Two observations of the
    same fact remain equal by content, which keeps deduplication working,
    while each still carries the identity that Insights and Decisions cite
    as evidence.
    """

    category: str
    metric: str
    value: float | str
    summary: str
    evidence: list[str] = field(default_factory=list)
    observation_id: str = field(default_factory=new_observation_id, compare=False)
