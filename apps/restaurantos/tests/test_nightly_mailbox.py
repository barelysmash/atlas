import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from restaurantos.nightly_backfill import NightlyEmailMessage
from restaurantos.nightly_mailbox import sync_nightly_mailbox
from restaurantos.nightly_refresh import read_nightly_message_jsonl


@dataclass
class FakeMailbox:
    messages: list[NightlyEmailMessage]
    calls: list[datetime | None] = field(default_factory=list)

    def fetch_messages(self, since: datetime | None) -> list[NightlyEmailMessage]:
        self.calls.append(since)
        return list(self.messages)


def _message(message_id: str, day: int, body: str = "SPLH: $80") -> NightlyEmailMessage:
    return NightlyEmailMessage(
        message_id=message_id,
        subject=f"EOD 8/{day}/2026",
        body=body,
        sent_at=datetime(2026, 8, day, 23, 30, tzinfo=UTC),
    )


def _write_bundle(path: Path, messages: list[NightlyEmailMessage]) -> None:
    path.write_text(
        "".join(
            json.dumps(
                {
                    "message_id": message.message_id,
                    "subject": message.subject,
                    "body": message.body,
                    "sent_at": message.sent_at.isoformat(),
                }
            )
            + "\n"
            for message in messages
        ),
        encoding="utf-8",
    )


def test_sync_refetches_lookback_and_upserts_by_message_id(tmp_path: Path):
    bundle = tmp_path / "private" / "messages.jsonl"
    state = tmp_path / "private" / "sync.json"
    bundle.parent.mkdir(parents=True)
    existing = _message("message-19", 19, body="old body")
    _write_bundle(bundle, [existing])

    updated = _message("message-19", 19, body="corrected body")
    new = _message("message-20", 20)
    mailbox = FakeMailbox([updated, new])

    result = sync_nightly_mailbox(
        mailbox,
        bundle,
        state,
        lookback=timedelta(days=2),
        synced_at=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
    )

    assert mailbox.calls == [datetime(2026, 8, 17, 23, 30, tzinfo=UTC)]
    assert result.fetched_message_count == 2
    assert result.new_message_count == 1
    assert result.updated_message_count == 1
    assert result.bundle_message_count == 2

    messages = read_nightly_message_jsonl(bundle)
    assert [message.message_id for message in messages] == ["message-19", "message-20"]
    assert messages[0].body == "corrected body"

    state_payload = json.loads(state.read_text(encoding="utf-8"))
    assert state_payload["bundle_message_count"] == 2
    assert state_payload["new_message_count"] == 1
    assert state_payload["updated_message_count"] == 1
    assert "message-19" not in state.read_text(encoding="utf-8")
    assert "message-20" not in state.read_text(encoding="utf-8")


def test_sync_without_existing_bundle_fetches_without_cursor(tmp_path: Path):
    bundle = tmp_path / "messages.jsonl"
    state = tmp_path / "state.json"
    mailbox = FakeMailbox([_message("message-20", 20)])

    result = sync_nightly_mailbox(mailbox, bundle, state)

    assert mailbox.calls == [None]
    assert result.new_message_count == 1
    assert result.fetch_since is None
    assert bundle.exists()
    assert state.exists()


def test_sync_duplicate_provider_ids_does_not_clobber_bundle(tmp_path: Path):
    bundle = tmp_path / "messages.jsonl"
    state = tmp_path / "state.json"
    existing = _message("message-19", 19)
    _write_bundle(bundle, [existing])
    original = bundle.read_text(encoding="utf-8")
    duplicate = _message("duplicate", 20)
    mailbox = FakeMailbox([duplicate, duplicate])

    with pytest.raises(ValueError, match="duplicate message_id"):
        sync_nightly_mailbox(mailbox, bundle, state)

    assert bundle.read_text(encoding="utf-8") == original
    assert not state.exists()


def test_sync_rejects_aliasing_bundle_and_state(tmp_path: Path):
    same = tmp_path / "same.jsonl"
    mailbox = FakeMailbox([_message("message-20", 20)])

    with pytest.raises(ValueError, match="must be distinct"):
        sync_nightly_mailbox(mailbox, same, same)
