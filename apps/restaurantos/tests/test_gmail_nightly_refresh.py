import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from restaurantos.__main__ import main
from restaurantos.gmail_mailbox import GmailApiMailbox
from restaurantos.gmail_nightly_refresh import gmail_nightly_refresh
from restaurantos.nightly_backfill import NightlyEmailMessage
from restaurantos.nightly_refresh import NightlyBriefWindow

BODY = """
Net Sales: $23,400.00
SPLH: $90.00
Labor (actual): $4,200.00
Horas (actual): 260.00
Starting Reservations: 220
Dining Room: 260
Bar/Atrium: 170
Total: 430
Total Comps: $450.00
Total Voids: $75.00
"""


def _credentials(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "client_id": "synthetic-client",
                "client_secret": "synthetic-secret",
                "refresh_token": "synthetic-refresh",
            }
        ),
        encoding="utf-8",
    )
    return path


def _gmail_message() -> NightlyEmailMessage:
    return NightlyEmailMessage(
        message_id="private-gmail-id",
        subject="EOD 8/20/2026",
        body=BODY,
        sent_at=datetime(2026, 8, 21, 4, 30, tzinfo=UTC),
    )


def _fake_fetch(self, since):
    return [_gmail_message()]


def test_gmail_refresh_keeps_provider_ids_out_of_history_and_state(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(GmailApiMailbox, "fetch_messages", _fake_fetch)
    credentials = _credentials(tmp_path / "gmail-oauth.json")
    messages = tmp_path / "private" / "messages.jsonl"
    state = tmp_path / "private" / "state.json"
    history = tmp_path / "private" / "history.jsonl"
    manifest = tmp_path / "private" / "manifest.json"
    brief = tmp_path / "private" / "brief.md"

    result = gmail_nightly_refresh(
        credentials,
        messages,
        state,
        history,
        manifest,
        restaurant="Test Restaurant",
        brief_path=brief,
        brief_window=NightlyBriefWindow(
            start_date=date(2026, 8, 20),
            end_date=date(2026, 8, 20),
            label="August 20",
        ),
    )

    assert result.sync.new_message_count == 1
    assert result.refresh.service_nights == 1
    assert "private-gmail-id" in messages.read_text(encoding="utf-8")
    assert "private-gmail-id" not in state.read_text(encoding="utf-8")
    assert "private-gmail-id" not in history.read_text(encoding="utf-8")
    assert "private-gmail-id" not in manifest.read_text(encoding="utf-8")
    assert "private-gmail-id" not in brief.read_text(encoding="utf-8")
    assert "# Test Restaurant Operating Brief" in brief.read_text(encoding="utf-8")


def test_gmail_refresh_rejects_private_path_alias_before_reading_credentials(
    tmp_path: Path,
):
    same = tmp_path / "same.json"

    with pytest.raises(ValueError, match="credentials and messages paths"):
        gmail_nightly_refresh(
            same,
            same,
            tmp_path / "state.json",
            tmp_path / "history.jsonl",
            tmp_path / "manifest.json",
            restaurant="Test Restaurant",
        )


def test_gmail_refresh_cli_reports_counts_without_message_ids(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(GmailApiMailbox, "fetch_messages", _fake_fetch)
    credentials = _credentials(tmp_path / "gmail-oauth.json")
    messages = tmp_path / "private" / "messages.jsonl"
    state = tmp_path / "private" / "state.json"
    history = tmp_path / "private" / "history.jsonl"
    manifest = tmp_path / "private" / "manifest.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restaurantos",
            "gmail-nightly-refresh",
            "--credentials",
            str(credentials),
            "--messages",
            str(messages),
            "--state",
            str(state),
            "--history",
            str(history),
            "--manifest",
            str(manifest),
            "--restaurant",
            "Test Restaurant",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "fetched_messages=1" in output
    assert "new_messages=1" in output
    assert "service_nights=1" in output
    assert "private-gmail-id" not in output
    assert "synthetic-refresh" not in output
