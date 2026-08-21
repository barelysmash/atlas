from datetime import date
from pathlib import Path

from restaurantos.nightly_history import read_history_jsonl
from restaurantos.operating_brief import (
    generate_operating_brief,
    summarize_operating_period,
)


def operating_brief_from_history(
    history_path: str | Path,
    start_date: date,
    end_date: date,
    *,
    entity: str | None = None,
    label: str | None = None,
    compare_start_date: date | None = None,
    compare_end_date: date | None = None,
    compare_label: str | None = None,
) -> str:
    """Generate an operating brief from a private local history ledger."""
    compare_dates = (compare_start_date, compare_end_date)
    if (compare_start_date is None) != (compare_end_date is None):
        raise ValueError("comparison start and end dates must be provided together")

    records = read_history_jsonl(history_path)
    current = summarize_operating_period(
        records,
        start_date,
        end_date,
        entity=entity,
        label=label,
    )

    previous = None
    if all(value is not None for value in compare_dates):
        assert compare_start_date is not None
        assert compare_end_date is not None
        previous = summarize_operating_period(
            records,
            compare_start_date,
            compare_end_date,
            entity=entity or current.entity,
            label=compare_label,
        )

    return generate_operating_brief(current, previous)


def write_operating_brief(path: str | Path, brief: str) -> Path:
    """Atomically write a generated brief outside the repository if desired."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    temporary.write_text(brief, encoding="utf-8")
    temporary.replace(destination)
    return destination
