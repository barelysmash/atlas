from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Observation:
    """A factual statement derived from evidence.

    Observations describe what happened.
    They do not interpret why it happened.
    """

    category: str
    metric: str
    value: float | str
    summary: str
    evidence: list[str] = field(default_factory=list)