from restaurantos.tabc_importer import TABCRecord


def total_receipts(records: list[TABCRecord]) -> float:
    """Return the total receipts across all records."""
    return sum(record.total_receipts for record in records)


def month_over_month(current: float, previous: float) -> float:
    """Return month-over-month percentage change."""
    if previous == 0:
        return 0.0

    return ((current - previous) / previous) * 100