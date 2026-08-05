from atlas_core.grain import GRAIN_PERIODS
from atlas_core.metric import Metric
from atlas_core.observation import Observation
from atlas_core.operational_record import OperationalRecord


def generate_observations(record: OperationalRecord) -> list[Observation]:
    """Generate factual observations from an OperationalRecord.

    This is the boundary where an internal record becomes a contract object.
    OperationalRecord keeps its own vocabulary; the rename to the contract's
    happens here and nowhere else.

    A record carries one metric, so this produces single-metric Observations.
    The contract permits many, and grouping several records measured together
    would be the change that starts using it.

    record.dimensions does not cross the boundary. It is query metadata rather
    than part of the measurement, and the contract has nowhere for it.
    """
    return [
        Observation(
            domain=record.category,
            subject=record.entity,
            summary=f"{record.metric} was {record.value:,.0f}.",
            metrics=(
                Metric(
                    name=record.metric,
                    value=record.value,
                    period=GRAIN_PERIODS[record.grain],
                ),
            ),
            source_ref=f"{record.source}:{record.entity}:{record.period}",
            observed_at=record.timestamp,
        )
    ]
