import json
from datetime import date
from pathlib import Path

import pytest

from restaurantos.nightly_refresh import (
    NightlyBriefWindow,
    read_nightly_message_jsonl,
    read_service_date_overrides,
    rebuild_nightly_history,
)


BODY_19 = """
SPLH: $80.00
Labor (actual): $4,000.00
Horas (actual): 250.00
Reservations: 200
Dining Room: 240
Bar/Atrium: 160
Total: 400
Total Comps: $500.00
Total Voids: $100.00
"""

BODY_20 = """
SPLH: $90.00
Labor (actual): $4,200.00
Horas (actual): 260.00
Reservations: 220
Dining Room: 260
Bar/Atrium: 170
Total: 430
Total Comps: $450.00
Total Voids: $75.00
"""


def _write_messages(path: Path) -> Path:
    rows = [
        {
            "message_id": "synthetic-19",
            "subject": "EOD 8/19/2026",
            "body": BODY_19,
            "sent_at": "2026-08-19T23:30:00-05:00",
        },
        {
            "message_id": "synthetic-20",
            "subject": "EOD 8/20/2026",
            "body": BODY_20,
            "sent_at": "2026-08-20T23:30:00-05:00",
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def test_message_bundle_reader_requires_timezone(tmp_path: Path):
    source = tmp_path / "messages.jsonl"
    source.write_text(
        json.dumps(
            {
                "message_id": "synthetic-1",
                "subject": "EOD 8/20/2026",
                "body": BODY_20,
                "sent_at": "2026-08-20T23:30:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="timezone offset"):
        read_nightly_message_jsonl(source)


def test_message_bundle_reader_rejects_duplicate_ids(tmp_path: Path):
    source = tmp_path / "messages.jsonl"
    row = {
        "message_id": "synthetic-1",
        "subject": "EOD 8/20/2026",
        "body": BODY_20,
        "sent_at": "2026-08-20T23:30:00-05:00",
    }
    source.write_text(
        json.dumps(row) + "\n" + json.dumps(row) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate message_id"):
        read_nightly_message_jsonl(source)


def test_override_reader_parses_iso_dates(tmp_path: Path):
    source = tmp_path / "overrides.json"
    source.write_text(
        json.dumps({"synthetic-20": "2026-08-19"}),
        encoding="utf-8",
    )

    overrides = read_service_date_overrides(source)

    assert overrides["synthetic-20"].isoformat() == "2026-08-19"


def test_refresh_rebuilds_redacted_history_manifest_and_brief(tmp_path: Path):
    messages = _write_messages(tmp_path / "messages.jsonl")
    history = tmp_path / "private" / "history.jsonl"
    manifest = tmp_path / "private" / "manifest.json"
    brief = tmp_path / "private" / "brief.md"

    result = rebuild_nightly_history(
        messages,
        history,
        manifest,
        restaurant="Test Restaurant",
        brief_path=brief,
        brief_window=NightlyBriefWindow(
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 20),
            label="August 20",
        ),
        compare_window=NightlyBriefWindow(
            start_date=date(2026, 8, 19),
            end_date=date(2026, 8, 19),
            label="August 19",
        ),
    )

    assert result.message_count == 2
    assert result.service_nights == 2
    assert result.first_service_date == "2026-08-19"
    assert result.last_service_date == "2026-08-20"
    assert result.history_path == history
    assert result.manifest_path == manifest
    assert result.brief_path == brief

    history_text = history.read_text(encoding="utf-8")
    assert "synthetic-19" not in history_text
    assert "synthetic-20" not in history_text
    assert '"entity":"Test Restaurant"' in history_text
    assert '"metric":"net_sales"' in history_text

    manifest_text = manifest.read_text(encoding="utf-8")
    assert "synthetic-19" not in manifest_text
    assert "synthetic-20" not in manifest_text
    manifest_payload = json.loads(manifest_text)
    assert manifest_payload["service_nights"] == 2
    assert manifest_payload["first_service_date"] == "2026-08-19"
    assert manifest_payload["last_service_date"] == "2026-08-20"

    brief_text = brief.read_text(encoding="utf-8")
    assert "# Test Restaurant Operating Brief" in brief_text
    assert "## August 20" in brief_text
    assert "## vs August 19" in brief_text
    assert "synthetic-19" not in brief_text
    assert "synthetic-20" not in brief_text


def test_refresh_does_not_clobber_outputs_when_bundle_has_no_reports(tmp_path: Path):
    messages = tmp_path / "messages.jsonl"
    messages.write_text(
        json.dumps(
            {
                "message_id": "chatter-1",
                "subject": "Re: EOD",
                "body": "Thanks!",
                "sent_at": "2026-08-20T23:30:00-05:00",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    history = tmp_path / "history.jsonl"
    manifest = tmp_path / "manifest.json"
    history.write_text("keep-history\n", encoding="utf-8")
    manifest.write_text("keep-manifest\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no service-night history"):
        rebuild_nightly_history(
            messages,
            history,
            manifest,
            restaurant="Test Restaurant",
        )

    assert history.read_text(encoding="utf-8") == "keep-history\n"
    assert manifest.read_text(encoding="utf-8") == "keep-manifest\n"


def test_refresh_requires_distinct_output_paths(tmp_path: Path):
    messages = _write_messages(tmp_path / "messages.jsonl")
    same = tmp_path / "same.jsonl"

    with pytest.raises(ValueError, match="distinct paths"):
        rebuild_nightly_history(
            messages,
            same,
            same,
            restaurant="Test Restaurant",
        )
