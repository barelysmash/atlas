from collections.abc import Sequence

from atlas_core.derived_metric import (
    DEFAULT_DERIVED_METRICS,
    DIFFERENCE,
    DerivedMetric,
)
from atlas_core.operational_record import OperationalRecord


def _by_period(
    records: list[OperationalRecord],
    metric: str,
) -> dict[str, OperationalRecord]:
    return {record.period: record for record in records if record.metric == metric}


def _apply(definition: DerivedMetric, left: float, right: float) -> float | None:
    if definition.operation == DIFFERENCE:
        return (left - right) * definition.scale

    if right == 0:
        return None

    return left / right * definition.scale


def derive_metrics(
    records: list[OperationalRecord],
    definitions: Sequence[DerivedMetric] | None = None,
) -> list[OperationalRecord]:
    """Append metrics derived from other metrics.

    Runs after blocking so that each rate is computed from the totals of the
    block it describes. Definitions are applied in order and may build on one
    another, so a margin can be derived from sales and cost and then divided
    by capacity in a later step.

    A period missing either input produces nothing, and is reported downstream
    as a data gap rather than guessed at.
    """
    definitions = DEFAULT_DERIVED_METRICS if definitions is None else definitions

    derived = list(records)

    for definition in definitions:
        lefts = _by_period(derived, definition.left)
        rights = _by_period(derived, definition.right)

        for period in sorted(lefts.keys() & rights.keys()):
            left, right = lefts[period], rights[period]
            value = _apply(definition, left.value, right.value)

            if value is None:
                continue

            derived.append(
                OperationalRecord.create(
                    source=left.source,
                    entity=left.entity,
                    period=period,
                    category=definition.category,
                    metric=definition.metric,
                    value=value,
                    grain=left.grain,
                    aggregation=definition.aggregation,
                )
            )

    return derived
