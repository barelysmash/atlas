from dataclasses import dataclass, field
from datetime import datetime

from atlas_core.identifiers import new_observation_id
from atlas_core.metric import Metric


@dataclass(frozen=True, slots=True)
class Observation:
    """A measurement event: one subject, one period, one query.

    Observations describe what was measured.
    They do not interpret why it happened.

    Shaped to JAM's observation contract, so it can be emitted without
    translation. ``metrics`` is a tuple rather than a list because the
    dataclass is frozen and a list inside it would not be.

    ``observation_id`` is excluded from equality, so two observations of the
    same measurement remain equal by content while each carries the identity
    that Insights and Decisions cite.

    ``periods`` names the periods this measurement draws on, and is internal
    reasoning state rather than contract data: it does not serialise. An
    observation computed across periods needs to say how many corroborate it,
    which is what lets a sustained trend outweigh one quiet period, and the
    contract has only a single ``source_ref`` string.
    """

    domain: str
    summary: str
    metrics: tuple[Metric, ...]
    observed_at: datetime
    subject: str | None = None
    source_ref: str | None = None
    periods: tuple[str, ...] = ()
    observation_id: str = field(default_factory=new_observation_id, compare=False)

    def has_metric(self, name: str) -> bool:
        """Whether this measurement includes a metric by that name."""
        return any(metric.name == name for metric in self.metrics)

    def get_metric(self, name: str) -> Metric | None:
        """The named metric, or None. Names are unique within an Observation."""
        return next((metric for metric in self.metrics if metric.name == name), None)
