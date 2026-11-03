"""First-of-month empty reporting windows must not halt nightly ingestion."""

import json
from datetime import date
from pathlib import Path

import pytest
from restaurantos.nightly_backfill import backfill_nightly_emails
from restaurantos.nightly_history import build_nightly_history
from restaurantos.nightly_refresh import (
    NightlyBriefWindow,
    _summarize_brief_window,
    read_nightly_message_jsonl,
    rebuild_nightly_history,
)
from restaurantos.operating_brief import summarize_operating_period

BODY = """\
SPLH: $80.00
Labor (actual): $4,000.00
Horas (actual): 250.00
Reservations: 200
Dining Room: 240
Bar/Atrium: 160
Total: 400
"""


def _messages(path: Path, *service_dates: date) -> Path:
    rows = [
        {
            "message_id": f"synthetic-{day.isoformat()}",
            "subject": f"EOD {day:%m/%d/%Y}",
            "body": BODY,
            "sent_at": f"{day.isoformat()}T23:30:00-06:00",
        }
        for day in service_dates
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def _refresh(
    tmp_path: Path,
    *service_dates: date,
    current: NightlyBriefWindow,
    previous: NightlyBriefWindow | None,
) -> tuple[str, dict[str, object], str]:
    source = _messages(tmp_path / "messages.jsonl", *service_dates)
    history = tmp_path / "history.jsonl"
    manifest = tmp_path / "manifest.json"
    brief = tmp_path / "brief.md"
    result = rebuild_nightly_history(
        source,
        history,
        manifest,
        restaurant="Test Restaurant",
        brief_path=brief,
        brief_window=current,
        compare_window=previous,
    )
    assert result.record_count > 0
    assert result.service_nights == len(service_dates)
    assert result.message_count == len(service_dates)
    assert len(history.read_text(encoding="utf-8").splitlines()) == result.record_count
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["record_count"] == result.record_count
    return (
        brief.read_text(encoding="utf-8"),
        payload,
        history.read_text(encoding="utf-8"),
    )


def test_empty_first_day_of_november_produces_explicit_no_data_brief(tmp_path):
    brief, manifest, _ = _refresh(
        tmp_path,
        date(2026, 10, 1),
        date(2026, 10, 28),
        current=NightlyBriefWindow(date(2026, 11, 1), date(2026, 11, 1), "November 1"),
        previous=NightlyBriefWindow(date(2026, 10, 1), date(2026, 10, 1), "October 1"),
    )
    assert manifest["service_nights"] == 2
    assert "## November 1" in brief
    assert "- Service nights represented: 0" in brief
    assert "- Net sales: n/a" in brief
    assert "- Covers: n/a" in brief
    assert "Sales 0/0; covers 0/0; labor 0/0" in brief
    assert "## vs October 1" in brief
    assert "- Net sales: n/a" in brief  # no misleading zero-percent change


def test_empty_comparison_period_does_not_break_november_refresh(tmp_path):
    brief, manifest, _ = _refresh(
        tmp_path,
        date(2026, 11, 2),
        current=NightlyBriefWindow(
            date(2026, 11, 1), date(2026, 11, 2), "November 1-2"
        ),
        previous=NightlyBriefWindow(
            date(2026, 10, 1), date(2026, 10, 2), "October 1-2"
        ),
    )
    assert manifest["service_nights"] == 1
    assert "- Service nights represented: 1" in brief
    assert "Sales 1/1; covers 1/1; labor 1/1" in brief
    assert "## vs October 1-2" in brief
    assert "- Net sales / covered night: n/a (1 vs 0 nights)" in brief


def test_both_windows_empty_preserves_existing_history_and_unknown_metrics(tmp_path):
    brief, manifest, history = _refresh(
        tmp_path,
        date(2026, 10, 28),
        current=NightlyBriefWindow(date(2026, 11, 1), date(2026, 11, 1)),
        previous=NightlyBriefWindow(date(2026, 10, 1), date(2026, 10, 1)),
    )
    assert manifest["service_nights"] == 1
    assert '"metric":"guest_count"' in history
    assert brief.count("- Net sales: n/a") == 2
    assert "- Service nights represented: 0" in brief
    assert "Sales 0/0; covers 0/0; labor 0/0" in brief


def test_explicit_entity_mismatch_still_rejected(tmp_path):
    source = _messages(tmp_path / "messages.jsonl", date(2026, 10, 28))
    reports = backfill_nightly_emails(
        read_nightly_message_jsonl(source), restaurant="Test Restaurant"
    )
    records = list(build_nightly_history(reports).records)
    window = NightlyBriefWindow(date(2026, 11, 1), date(2026, 11, 1))
    with pytest.raises(ValueError, match="requested restaurant"):
        _summarize_brief_window(records, window, "Wrong Restaurant")
    with pytest.raises(ValueError, match="no daily records"):
        summarize_operating_period(
            records,
            date(2026, 11, 1),
            date(2026, 11, 1),
            entity="Test Restaurant",
        )
