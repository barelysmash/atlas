import json
from datetime import date
from pathlib import Path

import pytest

from restaurantos.operating_brief_runner import (
    operating_brief_from_history,
    write_operating_brief,
)


def write_history(path: Path) -> Path:
    rows = [
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-06-01",
            "category": "sales",
            "metric": "net_sales",
            "value": 4000.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-06-01",
            "category": "labor",
            "metric": "labor_hours",
            "value": 100.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-06-01",
            "category": "labor",
            "metric": "labor_cost",
            "value": 1000.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-06-01",
            "category": "demand",
            "metric": "guest_count",
            "value": 100.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-05-01",
            "category": "sales",
            "metric": "net_sales",
            "value": 2000.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-05-01",
            "category": "labor",
            "metric": "labor_hours",
            "value": 80.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-05-01",
            "category": "labor",
            "metric": "labor_cost",
            "value": 800.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
        {
            "source": "nightly_email",
            "entity": "Test Restaurant",
            "period": "2026-05-01",
            "category": "demand",
            "metric": "guest_count",
            "value": 50.0,
            "dimensions": {},
            "grain": "daily",
            "aggregation": "sum",
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_runner_reads_private_history_and_generates_comparison(tmp_path: Path):
    history = write_history(tmp_path / "history.jsonl")

    brief = operating_brief_from_history(
        history,
        date(2026, 6, 1),
        date(2026, 6, 1),
        entity="Test Restaurant",
        label="June 1",
        compare_start_date=date(2026, 5, 1),
        compare_end_date=date(2026, 5, 1),
        compare_label="May 1",
    )

    assert "# Test Restaurant Operating Brief" in brief
    assert "## June 1" in brief
    assert "## vs May 1" in brief
    assert "- Net sales: +100.0%" in brief
    assert "- SPLH: +60.0%" in brief


def test_runner_requires_both_comparison_dates(tmp_path: Path):
    history = write_history(tmp_path / "history.jsonl")

    with pytest.raises(ValueError, match="must be provided together"):
        operating_brief_from_history(
            history,
            date(2026, 6, 1),
            date(2026, 6, 1),
            compare_start_date=date(2026, 5, 1),
        )


def test_runner_can_resolve_single_entity_without_name(tmp_path: Path):
    history = write_history(tmp_path / "history.jsonl")

    brief = operating_brief_from_history(
        history,
        date(2026, 6, 1),
        date(2026, 6, 1),
    )

    assert brief.startswith("# Test Restaurant Operating Brief")


def test_writer_creates_parent_and_replaces_existing_file(tmp_path: Path):
    destination = tmp_path / "private" / "brief.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("old", encoding="utf-8")

    written = write_operating_brief(destination, "new\n")

    assert written == destination
    assert destination.read_text(encoding="utf-8") == "new\n"
    assert not destination.with_suffix(".md.tmp").exists()
