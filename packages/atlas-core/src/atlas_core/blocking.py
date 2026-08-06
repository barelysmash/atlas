from collections import Counter
from datetime import date

from atlas_core.grain import DAILY, MEAN, SUM
from atlas_core.operational_record import OperationalRecord


def _combine(records: list[OperationalRecord]) -> float:
    aggregation = records[0].aggregation
    values = [record.value for record in records]

    if aggregation == SUM:
        return sum(values)

    if aggregation == MEAN:
        return sum(values) / len(values)

    raise ValueError(
        f"{records[0].metric} is a rate and cannot be rolled up from its own "
        "values. Ingest the components it is derived from, at the grain they "
        "are measured, and let Atlas derive the rate."
    )


def _week(period: str) -> tuple[int, int] | None:
    """The ISO year and week of a period, if it names a date."""
    try:
        parsed = date.fromisoformat(period)
    except ValueError:
        return None

    year, week, _day = parsed.isocalendar()

    return (year, week)


def _block(records: list[OperationalRecord]) -> OperationalRecord:
    first, last = records[0], records[-1]

    if len(records) == 1:
        return first

    return OperationalRecord.create(
        source=first.source,
        entity=first.entity,
        period=f"{first.period}..{last.period}",
        category=first.category,
        metric=first.metric,
        value=_combine(records),
        dimensions=first.dimensions,
        grain=first.grain,
        aggregation=first.aggregation,
    )


def _weekly_blocks(window: list[OperationalRecord]) -> list[OperationalRecord]:
    """Roll daily records up into the calendar weeks they fall in.

    Weeks, not runs of seven records. A restaurant that closes one day each
    week files six reports, and counting to seven would carry each block into
    the following week, so the blocks would drift and stop holding one of
    every trading day.

    A week holding fewer days than the window's usual trading week is dropped,
    which removes both partial weeks at the edges of the window and weeks
    broken by an unplanned closure. The usual trading week is inferred from
    the window itself, so a window containing only partial weeks treats those
    as whole; see test_a_window_of_only_partial_weeks_keeps_them.
    """
    weeks: dict[tuple[int, int], list[OperationalRecord]] = {}

    for record in window:
        key = _week(record.period)

        if key is None:
            raise ValueError(
                f"{record.metric} is daily but its period {record.period!r} "
                "is not a date, so it cannot be placed in a calendar week"
            )

        weeks.setdefault(key, []).append(record)

    counts = Counter(len(days) for days in weeks.values())
    trading_week = max(counts, key=lambda size: (counts[size], size))

    return [
        _block(sorted(days, key=lambda record: record.period))
        for _key, days in sorted(weeks.items())
        if len(days) >= trading_week
    ]


def block_records(records: list[OperationalRecord]) -> list[OperationalRecord]:
    """Roll records up into the comparison blocks their grain calls for.

    Daily records are blocked by calendar week so that a comparison sets one
    week against another rather than one night against the night before, which
    at a restaurant compares a Saturday with a Friday.

    Grains that already compare one period at a time pass through untouched.
    """
    grouped: dict[str, list[OperationalRecord]] = {}

    for record in records:
        grouped.setdefault(record.metric, []).append(record)

    blocked: list[OperationalRecord] = []

    for metric, window in grouped.items():
        grains = {record.grain for record in window}

        if len(grains) > 1:
            raise ValueError(
                f"{metric} mixes grains {sorted(grains)}; a metric must be "
                "reported at one grain"
            )

        ordered = sorted(window, key=lambda record: record.period)

        if ordered[0].grain != DAILY:
            blocked.extend(ordered)
            continue

        blocked.extend(_weekly_blocks(ordered))

    return blocked
