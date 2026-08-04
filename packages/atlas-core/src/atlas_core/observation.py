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
    """

    domain: str
    summary: str
    metrics: tuple[Metric, ...]
    observed_at: datetime
    subject: str | None = None
    source_ref: str | None = None
    observation_id: str = field(default_factory=new_observation_id, compare=False)

    def has_metric(self, name: str) -> bool:
        """Whether this measurement includes a metric by that name."""
        return any(metric.name == name for metric in self.metrics)

    def get_metric(self, name: str) -> Metric | None:
        """The named metric, or None. Names are unique within an Observation."""
        return next((metric for metric in self.metrics if metric.name == name), None)
