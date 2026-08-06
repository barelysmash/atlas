from atlas_core.goal import DOWN, FLAT, UP
from atlas_core.grain import GRAIN_PERIODS, MIN_STREAK_BLOCKS, span_period
from atlas_core.metric import Metric
from atlas_core.observation import Observation
from atlas_core.operational_record import OperationalRecord

DIRECTION_LABELS = {UP: "increased", DOWN: "decreased", FLAT: "held steady"}


def _amount(value: float) -> str:
    """Format a value without rounding a small one away to nothing.

    A market share below one percent renders as 0 under a whole-number format,
    which reads as no share at all rather than a small one.
    """
    if value and abs(value) < 10:
        return f"{value:,.2f}"

    return f"{value:,.0f}"


def _provenance(record: OperationalRecord) -> str:
    return f"{record.source}:{record.entity}:{record.period}"


def _source_ref(records: list[OperationalRecord]) -> str:
    """Join the provenance of every record an observation draws on.

    The contract carries one source_ref string. An observation computed across
    periods legitimately has several sources, so they are joined rather than
    dropped; the periods themselves are carried separately, where reasoning
    can count them.
    """
    return " ".join(_provenance(record) for record in records)


def _percent_change(current: float, previous: float) -> float:
    """Period-over-period percentage change."""
    if previous == 0:
        return 0.0

    return ((current - previous) / previous) * 100


def _direction(current: float, previous: float) -> str:
    if current > previous:
        return UP
    if current < previous:
        return DOWN

    return FLAT


def _streak(values: list[float]) -> tuple[str, int]:
    """The direction and length of the trailing monotonic run.

    A streak counts consecutive strictly increasing or strictly decreasing
    period-over-period moves ending at the latest period.
    """
    if len(values) < 2:
        return (FLAT, 0)

    direction = FLAT
    length = 0

    for current, previous in zip(reversed(values), reversed(values[:-1]), strict=False):
        step = _direction(current, previous)

        if step == FLAT:
            break

        if direction == FLAT:
            direction = step
        elif step != direction:
            break

        length += 1

    return (direction, length)


def _group_by_metric(
    records: list[OperationalRecord],
) -> dict[str, list[OperationalRecord]]:
    """Group records by metric, preserving first-appearance order."""
    grouped: dict[str, list[OperationalRecord]] = {}

    for record in records:
        grouped.setdefault(record.metric, []).append(record)

    return grouped


def _latest_observation(window: list[OperationalRecord]) -> Observation:
    latest = window[-1]

    if len(window) == 1:
        return Observation(
            domain=latest.category,
            subject=latest.entity,
            summary=f"{latest.metric} was {_amount(latest.value)} in {latest.period}.",
            metrics=(
                Metric(
                    name=latest.metric,
                    value=latest.value,
                    period=GRAIN_PERIODS[latest.grain],
                ),
            ),
            source_ref=_source_ref([latest]),
            observed_at=latest.timestamp,
            periods=(latest.period,),
        )

    previous = window[-2]
    change = _percent_change(latest.value, previous.value)

    return Observation(
        domain=latest.category,
        subject=latest.entity,
        summary=(
            f"{latest.metric} was {_amount(latest.value)} in {latest.period} "
            f"({change:+.1f}% vs {previous.period})."
        ),
        metrics=(
            Metric(
                name=latest.metric,
                value=latest.value,
                delta=change / 100,
                period=GRAIN_PERIODS[latest.grain],
            ),
        ),
        source_ref=_source_ref([previous, latest]),
        observed_at=latest.timestamp,
        periods=(previous.period, latest.period),
    )


def _streak_observation(window: list[OperationalRecord]) -> Observation | None:
    direction, length = _streak([record.value for record in window])

    if length < MIN_STREAK_BLOCKS:
        return None

    span = window[-(length + 1) :]
    latest = window[-1]
    change = _percent_change(latest.value, span[0].value)

    return Observation(
        domain=latest.category,
        subject=latest.entity,
        summary=(
            f"{latest.metric} has {DIRECTION_LABELS[direction]} for "
            f"{length} consecutive periods "
            f"({span[0].period} through {latest.period})."
        ),
        metrics=(
            Metric(
                name=latest.metric,
                value=latest.value,
                delta=change / 100,
                # The span, not the grain: a metric that rose for four months
                # describes P4M, and stating P1M would understate it.
                period=span_period(latest.grain, length),
            ),
        ),
        source_ref=_source_ref(span),
        observed_at=latest.timestamp,
        periods=tuple(record.period for record in span),
    )


def generate_trend_observations(
    records: list[OperationalRecord],
) -> list[Observation]:
    """Generate factual observations from a window of operational records.

    Records are grouped by metric and ordered by period. Each metric yields its
    latest value with period-over-period change, plus a streak observation when
    the metric has moved the same direction for at least MIN_STREAK_BLOCKS
    consecutive periods.

    Observations state what happened. They do not interpret why.
    """
    if not records:
        raise ValueError("records is required")

    observations: list[Observation] = []

    for window in _group_by_metric(records).values():
        ordered = sorted(window, key=lambda record: record.period)

        observations.append(_latest_observation(ordered))

        streak = _streak_observation(ordered)
        if streak is not None:
            observations.append(streak)

    return observations
