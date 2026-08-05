from dataclasses import dataclass

from atlas_core.metric import Metric
from atlas_core.observation import Observation


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """A citation of one metric from one Observation.

    Mirrors the evidenceItem shape shared by JAM's insight and decision
    schemas. An Observation may carry several metrics; a citation names the
    one the reasoning used, which is what makes the trace precise.

    The metric is a copy, and copies drift. JAM's validator rejects a citation
    whose metric disagrees with the Observation it names, so build these with
    ``citing`` rather than by hand.
    """

    observation_id: str
    statement: str
    metric: Metric | None = None
    source_ref: str | None = None

    @classmethod
    def citing(
        cls,
        observation: Observation,
        metric_name: str,
        statement: str | None = None,
    ) -> "EvidenceItem":
        """Cite one metric of an Observation, copying it from the source.

        Raises if the Observation carries no such metric, so a citation that
        could never validate fails here rather than at emission.
        """
        metric = observation.get_metric(metric_name)
        if metric is None:
            available = ", ".join(m.name for m in observation.metrics) or "none"
            raise ValueError(
                f"{observation.observation_id} has no metric named "
                f"{metric_name!r}; it has: {available}"
            )
        return cls(
            observation_id=observation.observation_id,
            statement=observation.summary if statement is None else statement,
            metric=metric,
            source_ref=observation.source_ref,
        )
