"""Read side of the briefings feed: the file, the change feed and its cursors.

The nightly workload writes the briefings file (``restaurantos.briefings``);
the peer API only reads it, here. Nothing in this module writes.

The change feed lists every briefing and tombstone in ascending
``(updated_at, id)`` order. ``updated_at`` is a fixed-width RFC 3339 UTC stamp
in whole seconds, so string order is time order, and the writer
keeps every new stamp strictly later than every stamp already in the file.

Cursors are opaque to clients: base64url JSON (no padding) holding a feed
position, a ``since`` window, a head and the file's generation. They are
stateless, so they survive restarts and token rotation, and are validated
structurally: a forged but well-formed cursor can only re-read data its bearer
may read anyway.

The generation is a random token the writer gives a briefings file when it
builds one from scratch (first run, a deleted file, or a damaged one) and
keeps on every later refresh. A cursor issued for another generation answers
``400 invalid_cursor``: its position means nothing in the rebuilt file, and
honouring it could silently skip deletions. The app answers that error by
re-running its backfill. A cursor with no generation is refused the same
way (cursors without one were never released), and a file with no valid
generation is not a briefings file: the API answers ``503
briefings_unavailable`` and the next refresh rebuilds it.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
from dataclasses import dataclass
from datetime import date
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

from restaurantos.http_errors import ApiError
from restaurantos.relative_summary import FIGURES_POLICY

FILE_FORMAT = 1
CURSOR_VERSION = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 100

# The fields a live briefing carries in the feed, in addition to "figures".
PUBLIC_FIELDS = (
    "id",
    "date",
    "title",
    "summary",
    "body_markdown",
    "tags",
    "created_at",
    "updated_at",
)

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_LIMIT = re.compile(r"[0-9]{1,3}")
_B64 = re.compile(r"[A-Za-z0-9_-]+")
# A file generation: what the writer issues (secrets.token_urlsafe), bounded.
GENERATION = re.compile(r"[A-Za-z0-9_-]{8,64}")

Key = tuple[str, str]
_START: Key = ("", "")


def _unavailable(message: str) -> ApiError:
    return ApiError(HTTPStatus.SERVICE_UNAVAILABLE, "briefings_unavailable", message)


def _bad(code: str, message: str) -> ApiError:
    return ApiError(HTTPStatus.BAD_REQUEST, code, message)


def not_found() -> ApiError:
    return ApiError(HTTPStatus.NOT_FOUND, "not_found", "No such route.")


@dataclass(frozen=True, slots=True)
class Entry:
    """One stored briefing or tombstone, as the nightly workload wrote it."""

    id: str
    updated_at: str
    deleted: bool
    date: str | None
    payload: dict[str, Any]

    @property
    def key(self) -> Key:
        return self.updated_at, self.id

    def public(self) -> dict[str, Any]:
        """What a client sees: a briefing, or a minimal tombstone."""
        if self.deleted:
            return {"id": self.id, "updated_at": self.updated_at, "deleted": True}
        item = {field: self.payload[field] for field in PUBLIC_FIELDS}
        item["deleted"] = False
        item["figures"] = FIGURES_POLICY
        return item


@dataclass(frozen=True, slots=True)
class Snapshot:
    entries: tuple[Entry, ...]
    by_id: dict[str, Entry]
    generation: str

    @property
    def head(self) -> Key:
        return self.entries[-1].key if self.entries else _START


def parse_entries(raw: Any) -> Snapshot:
    """Validate a decoded briefings file; ValueError if it is not one."""
    if not isinstance(raw, dict) or raw.get("format") != FILE_FORMAT:
        raise ValueError("not a briefings file of a known format")
    if raw.get("figures") != FIGURES_POLICY:
        raise ValueError("briefings file is not marked relative_only")
    generation = raw.get("generation")
    if not isinstance(generation, str) or not GENERATION.fullmatch(generation):
        raise ValueError("briefings file has no valid generation")
    briefings = raw.get("briefings")
    if not isinstance(briefings, list):
        raise ValueError("briefings file has no briefings list")
    entries: list[Entry] = []
    for item in briefings:
        if not isinstance(item, dict):
            raise ValueError("briefing entry is not an object")
        ident, stamp = item.get("id"), item.get("updated_at")
        if not isinstance(ident, str) or not isinstance(stamp, str):
            raise ValueError("briefing entry lacks id or updated_at")
        deleted = item.get("deleted") is True
        if not deleted:
            missing = [f for f in PUBLIC_FIELDS if f not in item]
            if missing:
                raise ValueError(f"briefing entry lacks {', '.join(missing)}")
        day = item.get("date")
        entries.append(
            Entry(
                id=ident,
                updated_at=stamp,
                deleted=deleted,
                date=day if isinstance(day, str) else None,
                payload=item,
            )
        )
    entries.sort(key=lambda entry: entry.key)
    by_id = {entry.id: entry for entry in entries}
    if len(by_id) != len(entries):
        raise ValueError("briefings file repeats an id")
    return Snapshot(entries=tuple(entries), by_id=by_id, generation=generation)


class BriefingsStore:
    """The briefings file, re-read only when it changes (as ``Ledger`` does)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int, int] | None = None
        self._snapshot: Snapshot | None = None

    @property
    def path(self) -> Path:
        return self._path

    def snapshot(self) -> Snapshot:
        try:
            stat = self._path.stat()
        except (FileNotFoundError, NotADirectoryError):
            raise _unavailable(
                "The briefings file does not exist yet; the nightly run builds it."
            ) from None
        stamp = (stat.st_mtime_ns, stat.st_size, stat.st_ino)
        with self._lock:
            if stamp != self._stamp:
                try:
                    raw = json.loads(self._path.read_text(encoding="utf-8"))
                    snapshot = parse_entries(raw)
                except (OSError, UnicodeDecodeError, ValueError):
                    raise _unavailable(
                        "The briefings file could not be read."
                    ) from None
                self._snapshot = snapshot
                self._stamp = stamp
            current = self._snapshot
        if current is None:  # cannot happen: a stamp is set with its snapshot
            raise _unavailable("The briefings file could not be read.")
        return current


# --------------------------------------------------------------------------
# Cursors


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    if not _B64.fullmatch(text):
        raise ValueError("not base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        raise ValueError("not base64url") from None


@dataclass(frozen=True, slots=True)
class Cursor:
    position: Key
    # The generation of the file the cursor was issued for.
    generation: str
    since: str | None = None
    head: Key | None = None


def encode_cursor(cursor: Cursor) -> str:
    fields: dict[str, Any] = {
        "v": CURSOR_VERSION,
        "p": list(cursor.position),
        "s": cursor.since,
        "h": None if cursor.head is None else list(cursor.head),
        "g": cursor.generation,
    }
    payload = json.dumps(fields, separators=(",", ":"), sort_keys=True)
    return _b64encode(payload.encode("utf-8"))


def _pair(value: Any) -> Key:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(part, str) for part in value)
    ):
        raise ValueError("bad position")
    return value[0], value[1]


def decode_cursor(text: str) -> Cursor:
    """The cursor, or ``400 invalid_cursor`` if this server did not issue it."""
    error = _bad("invalid_cursor", "cursor is not a cursor issued by this server")
    try:
        payload = _b64decode(text)
    except ValueError:
        raise error from None
    try:
        raw = json.loads(payload)
        if (
            not isinstance(raw, dict)
            or set(raw) != {"v", "p", "s", "h", "g"}
            or type(raw["v"]) is not int
            or raw["v"] != CURSOR_VERSION
        ):
            raise ValueError("unknown cursor version")
        since = raw["s"]
        if since is not None and not (
            isinstance(since, str) and _DATE.fullmatch(since)
        ):
            raise ValueError("bad since")
        if since is not None:
            date.fromisoformat(since)
        generation = raw["g"]
        if not isinstance(generation, str) or not GENERATION.fullmatch(generation):
            raise ValueError("bad generation")
        head = raw.get("h")
        return Cursor(
            position=_pair(raw["p"]),
            since=since,
            head=None if head is None else _pair(head),
            generation=generation,
        )
    except (UnicodeDecodeError, ValueError):
        raise error from None


# --------------------------------------------------------------------------
# Requests


@dataclass(frozen=True, slots=True)
class ListQuery:
    limit: int
    cursor: Cursor | None
    since: str | None


def _single(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if values is None:
        return None
    # A repeated parameter is as invalid as a malformed one.
    return values[0] if len(values) == 1 else "\0"


def parse_list_query(query: str) -> ListQuery:
    """Validate ``limit``, then ``cursor``, then ``since`` (if no cursor)."""
    params = parse_qs(query, keep_blank_values=True)

    raw_limit = _single(params, "limit")
    limit = DEFAULT_LIMIT
    if raw_limit is not None:
        if not _LIMIT.fullmatch(raw_limit) or not 1 <= int(raw_limit) <= MAX_LIMIT:
            raise _bad("invalid_limit", f"limit must be an integer 1..{MAX_LIMIT}")
        limit = int(raw_limit)

    raw_cursor = _single(params, "cursor")
    if raw_cursor is not None:
        # With a cursor, since is ignored and not validated: the cursor
        # carries its own window.
        return ListQuery(limit=limit, cursor=decode_cursor(raw_cursor), since=None)

    raw_since = _single(params, "since")
    since: str | None = None
    if raw_since is not None:
        if not _DATE.fullmatch(raw_since):
            raise _bad("invalid_since", "since must be a date in YYYY-MM-DD form")
        try:
            date.fromisoformat(raw_since)
        except ValueError:
            raise _bad(
                "invalid_since", "since must be a date in YYYY-MM-DD form"
            ) from None
        since = raw_since
    return ListQuery(limit=limit, cursor=None, since=since)


def briefing_id_from_path(segment: str) -> str:
    """The id from its URL-encoded path segment; 404 if it is not one."""
    ident = unquote(segment)
    if not ident or "/" in ident:
        raise not_found()
    return ident


# --------------------------------------------------------------------------
# Responses


def list_page(snapshot: Snapshot, query: ListQuery) -> dict[str, Any]:
    """One page of the change feed and the cursor that follows it.

    A ``since`` walk is bounded by the feed head as it was at its first
    request; its final (resume) cursor is that head, so everything changed
    after the walk began is returned on the next sync, for any date.
    Without ``since`` the resume cursor is the head at the last page.
    """
    if query.cursor is not None:
        if query.cursor.generation != snapshot.generation:
            # Issued for a file that has since been rebuilt from scratch.
            raise _bad(
                "invalid_cursor",
                "cursor is from before the briefings were rebuilt; start again "
                "without a cursor",
            )
        position = query.cursor.position
        since = query.cursor.since
        head = query.cursor.head
    else:
        position = _START
        since = query.since
        head = snapshot.head if since is not None else None

    eligible = [
        entry
        for entry in snapshot.entries
        if entry.key > position
        and (head is None or entry.key <= head)
        and (since is None or entry.deleted or (entry.date or "") >= since)
    ]
    page = eligible[: query.limit]
    has_more = len(eligible) > query.limit
    generation = snapshot.generation
    if has_more:
        following = Cursor(
            position=page[-1].key, since=since, head=head, generation=generation
        )
    else:
        reached = page[-1].key if page else position
        end = head if head is not None else snapshot.head
        following = Cursor(position=max(reached, end, position), generation=generation)
    return {
        "figures": FIGURES_POLICY,
        "has_more": has_more,
        "items": [entry.public() for entry in page],
        "next_cursor": encode_cursor(following),
    }


def single_briefing(snapshot: Snapshot, ident: str) -> dict[str, Any]:
    entry = snapshot.by_id.get(ident)
    if entry is None or entry.deleted:
        raise not_found()
    return entry.public()
