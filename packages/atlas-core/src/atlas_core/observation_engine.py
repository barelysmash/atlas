from atlas_core.observation import Observation
from atlas_core.operational_record import OperationalRecord


def generate_observations(record: OperationalRecord) -> list[Observation]:
    """Generate factual observations from an OperationalRecord."""
    return [
        Observation(
            category=record.category,
            metric=record.metric,
            value=record.value,
            summary=f"{record.metric} was {record.value:,.0f}.",
            evidence=[f"{record.source}:{record.entity}:{record.period}"],
        )
    ]