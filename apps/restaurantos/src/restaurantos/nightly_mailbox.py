import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from restaurantos.nightly_backfill import NightlyEmailMessage
from restaurantos.nightly_refresh import read_nightly_message_jsonl


class NightlyMailboxSource(Protocol):
    """Provider boundary for retrieving private nightly email messages."""

    def fetch_messages(self, since: datetime | None) -> list[NightlyEmailMessage]: ...


@dataclass(frozen=True, slots=True)
class NightlyMailboxSyncResult:
    fetched_message_count: int
    new_message_count: int
    updated_message_count: int
    bundle_message_count: int
    fetch_since: datetime | None
    last_seen_sent_at: datetime | None
    bundle_path: Path
    state_path: Path


def _validate_message(message: NightlyEmailMessage) -> None:
    if not message.message_id:
        raise ValueError("mailbox message_id is required")
    if message.sent_at.utcoffset() is None:
        raise ValueError(
            f"mailbox message {message.message_id!r} sent_at must include a timezone"
        )


def _message_payload(message: NightlyEmailMessage) -> dict[str, str]:
    return {
        "message_id": message.message_id,
        "subject": message.subject,
        "body": message.body,
        "sent_at": message.sent_at.isoformat(),
    }


def _sort_key(message: NightlyEmailMessage) -> tuple[datetime, str]:
    return message.sent_at.astimezone(UTC), message.message_id


def _read_existing_bundle(path: Path) -> list[NightlyEmailMessage]:
    if not path.exists():
        return []
    if path.stat().st_size == 0:
        return []
    return read_nightly_message_jsonl(path)


def _atomic_write_messages(path: Path, messages: list[NightlyEmailMessage]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    lines = [
        json.dumps(_message_payload(message), sort_keys=True, separators=(",", ":"))
        for message in messages
    ]
    temporary.write_text(
        "\n".join(lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )
    temporary.replace(path)


def _atomic_write_state(
    path: Path,
    *,
    synced_at: datetime,
    fetch_since: datetime | None,
    last_seen_sent_at: datetime | None,
    fetched_message_count: int,
    new_message_count: int,
    updated_message_count: int,
    bundle_message_count: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    payload = {
        "synced_at": synced_at.astimezone(UTC).isoformat(),
        "fetch_since": (
            fetch_since.astimezone(UTC).isoformat() if fetch_since is not None else None
        ),
        "last_seen_sent_at": (
            last_seen_sent_at.astimezone(UTC).isoformat()
            if last_seen_sent_at is not None
            else None
        ),
        "fetched_message_count": fetched_message_count,
        "new_message_count": new_message_count,
        "updated_message_count": updated_message_count,
        "bundle_message_count": bundle_message_count,
    }
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def sync_nightly_mailbox(
    source: NightlyMailboxSource,
    bundle_path: str | Path,
    state_path: str | Path,
    *,
    lookback: timedelta = timedelta(days=2),
    synced_at: datetime | None = None,
) -> NightlyMailboxSyncResult:
    """Upsert provider messages into a complete private source bundle.

    The fetch cursor is derived from the bundle itself rather than trusting a
    separate state file. A lookback window intentionally re-fetches recent
    messages so late edits and provider-side corrections replace their prior
    version by stable message ID.
    """
    if lookback < timedelta(0):
        raise ValueError("mailbox lookback cannot be negative")

    destination = Path(bundle_path)
    state_destination = Path(state_path)
    if destination.resolve() == state_destination.resolve():
        raise ValueError("mailbox bundle and state paths must be distinct")

    existing = _read_existing_bundle(destination)
    for message in existing:
        _validate_message(message)

    latest_existing = max(
        (message.sent_at for message in existing),
        default=None,
        key=lambda value: value.astimezone(UTC),
    )
    fetch_since = latest_existing - lookback if latest_existing is not None else None

    fetched = source.fetch_messages(fetch_since)
    fetched_by_id: dict[str, NightlyEmailMessage] = {}
    for message in fetched:
        _validate_message(message)
        if message.message_id in fetched_by_id:
            raise ValueError(
                f"mailbox provider returned duplicate message_id {message.message_id!r}"
            )
        fetched_by_id[message.message_id] = message

    merged = {message.message_id: message for message in existing}
    new_message_count = 0
    updated_message_count = 0
    for message_id, message in fetched_by_id.items():
        previous = merged.get(message_id)
        if previous is None:
            new_message_count += 1
        elif previous != message:
            updated_message_count += 1
        merged[message_id] = message

    messages = sorted(merged.values(), key=_sort_key)
    last_seen_sent_at = max(
        (message.sent_at for message in messages),
        default=None,
        key=lambda value: value.astimezone(UTC),
    )

    sync_time = synced_at or datetime.now(UTC)
    if sync_time.utcoffset() is None:
        raise ValueError("synced_at must include a timezone offset")

    _atomic_write_messages(destination, messages)
    _atomic_write_state(
        state_destination,
        synced_at=sync_time,
        fetch_since=fetch_since,
        last_seen_sent_at=last_seen_sent_at,
        fetched_message_count=len(fetched),
        new_message_count=new_message_count,
        updated_message_count=updated_message_count,
        bundle_message_count=len(messages),
    )

    return NightlyMailboxSyncResult(
        fetched_message_count=len(fetched),
        new_message_count=new_message_count,
        updated_message_count=updated_message_count,
        bundle_message_count=len(messages),
        fetch_since=fetch_since,
        last_seen_sent_at=last_seen_sent_at,
        bundle_path=destination,
        state_path=state_destination,
    )
