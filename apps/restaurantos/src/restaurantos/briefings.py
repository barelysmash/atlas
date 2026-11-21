"""Daily briefings for the owner's phone, built by the nightly workload.

One briefing per service night in the ledger, for one entity. Every figure in
a briefing comes from ``relative_summary``: percent changes, percentage-point
deltas, directions and night counts. No dollar amount, cover count, labor
total or rate level is written, so nothing in the briefings file (or the feed
that serves it) lets a reader reconstruct an absolute figure.

Partial nights (the manifest's ``partial_nights``: filled from an approved
point-of-sale summary, net sales and voids only) are honoured: a week
comparison resting on one reads "no comparison available" for every headline
it lacks, says why in one line, and is at most Medium confidence.

The briefings file lives next to the ledger under the private data root. A
refresh keeps each briefing's ``updated_at`` unless its content hash changes,
and turns a night that left the ledger into a tombstone. The peer API only
reads the file (``restaurantos.briefings_feed``).

Refreshes are serialised by an exclusive ``flock`` on ``<file>.lock`` held for
the whole read-compute-write, so a manual refresh during the nightly run waits
rather than overwriting it. ``fcntl`` (and the POSIX-only ``os`` attributes the
writer uses) are touched only when a refresh runs, so this module imports on
any platform; on a host without ``fcntl`` a refresh raises ``PosixHostRequiredError``
before it creates anything. A briefings file that cannot be read or parsed is
reported and rebuilt from the ledger, under a new generation (fresh
``updated_at`` values; earlier cursors answer ``invalid_cursor``).
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import tempfile
from collections.abc import Iterator
from collections.abc import Set as AbstractSet
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from atlas_core.operational_record import OperationalRecord

from restaurantos.briefings_feed import FILE_FORMAT, GENERATION, parse_entries
from restaurantos.coverage import (
    NightCounts,
    count_flagged_nights,
    count_partial_nights,
    read_partial_nights,
    read_reviews,
)
from restaurantos.nightly_history import read_history_jsonl
from restaurantos.nightly_schedule import aligned_month_windows
from restaurantos.operating_brief import summarize_operating_period
from restaurantos.relative_summary import FIGURES_POLICY, relative_operating_summary

_WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)

# The headline metrics, as relative_summary reports them.
_HEADLINES = (
    ("net_sales", "Net sales"),
    ("guest_count", "Covers"),
    ("average_check", "Average check"),
    ("splh", "Sales per labor hour"),
    ("labor_cost_pct", "Labor cost (share of sales)"),
    ("reservation_share", "Reservation share"),
    ("comp_pct", "Comp rate"),
    ("void_pct", "Void rate"),
)

# Nights missing across both month windows that make a comparison Low.
_MISSING_FOR_LOW = 3
_CONTENT_FIELDS = ("date", "title", "summary", "body_markdown", "tags")
_NO_COMPARISON = "no comparison available"
# The headline metrics a partial night carries: it was filled from an approved
# point-of-sale (Toast) summary, which has net sales and voids only.
_PARTIAL_CARRIES = frozenset({"net_sales", "void_pct"})


def briefing_id(entity: str, night: date) -> str:
    """Stable id from entity and service date.

    The id carries a short hash of the entity name, so the name is not sent in
    clear. The hash is an identifier, not a secret: a short, guessable name can
    be recovered from it by trying candidates.
    """
    digest = hashlib.sha256(entity.encode("utf-8")).hexdigest()[:8]
    return f"brf_{night.isoformat()}_{digest}"


def _day(night: date) -> str:
    return f"{_WEEKDAYS[night.weekday()]}, {_MONTHS[night.month - 1]} {night.day}"


def phrase(change: float | None, direction: str | None, unit: str) -> str:
    """'up 8.2%', 'down 1.4 points', 'flat' or 'no comparison available'."""
    if change is None or direction is None:
        return _NO_COMPARISON
    if direction == "flat":
        return "flat"
    size = f"{abs(change):.1f}"
    return f"{direction} {size}%" if unit == "percent" else f"{direction} {size} points"


def _compare(
    records: list[OperationalRecord],
    entity: str,
    current: tuple[date, date],
    previous: tuple[date, date],
) -> dict[str, str] | None:
    """Headline phrases for two windows, or None if either has no data."""
    try:
        now = summarize_operating_period(records, *current, entity=entity)
        before = summarize_operating_period(records, *previous, entity=entity)
    except ValueError:
        return None
    summary = relative_operating_summary(now, before)
    entries = {entry["metric"]: entry for entry in summary["changes"]}
    phrases: dict[str, str] = {}
    for metric, _label in _HEADLINES:
        entry = entries.get(metric, {})
        phrases[metric] = phrase(
            entry.get("change"), entry.get("direction"), str(entry.get("unit"))
        )
    return phrases


def _bullets(changes: dict[str, str] | None) -> list[str]:
    """One bullet per headline metric, even when there is nothing to compare."""
    return [
        f"- {label}: {changes[metric] if changes else _NO_COMPARISON}"
        for metric, label in _HEADLINES
    ]


def _coverage(
    reviews: dict[date, tuple[str, ...]] | None,
    nights: set[date],
    start: date,
    end: date,
) -> tuple[int, int] | None:
    """(nights in review, nights missing) in a window; None when unknown.

    The shared counting of ``restaurantos.coverage``, as the peer API does it.
    """
    counts: NightCounts | None = count_flagged_nights(reviews, nights, start, end)
    return None if counts is None else (counts.in_review, counts.missing)


def _nights(count: int) -> str:
    return "1 night" if count == 1 else f"{count} nights"


def _gaps(in_review: int, missing: int) -> str:
    return f"{_nights(in_review)} in review, {missing} missing"


def _text(coverage: tuple[int, int] | None, index: int) -> str:
    return "unknown" if coverage is None else str(coverage[index])


def _count_text(count: int | None) -> str:
    return "unknown" if count is None else str(count)


def _without_partial_metrics(changes: dict[str, str]) -> dict[str, str]:
    """A night-against-night comparison when a night is partial.

    A partial night carries net sales and voids only, so every other headline
    reads ``no comparison available``, whatever the other night carries.
    """
    return {
        metric: value if metric in _PARTIAL_CARRIES else _NO_COMPARISON
        for metric, value in changes.items()
    }


def _partial_line(partial_nights: list[date]) -> str:
    """The one plain line that says why a week comparison is cut short."""
    if len(partial_nights) == 1:
        names, verb = _day(partial_nights[0]), "was"
    else:
        # Both nights; the weekday is in the title and the finding's heading.
        names = " and ".join(
            f"{_MONTHS[night.month - 1]} {night.day}" for night in partial_nights
        )
        verb = "were"
    return (
        f"{names} {verb} filled from a point-of-sale summary, so only net sales "
        "and voids are known."
    )


def _rationale(reasons: list[str]) -> str:
    return "; ".join(reasons)


def render_briefing(
    records: list[OperationalRecord],
    entity: str,
    night: date,
    nights: set[date],
    reviews: dict[date, tuple[str, ...]] | None,
    partial: AbstractSet[date] | None = frozenset(),
) -> dict[str, Any]:
    """The content of one night's briefing (no id or timestamps).

    A pure function of the records, reviews and partial nights dated within
    the night's own windows (the night, a week earlier, month to date and the
    aligned days of the prior month): no wall clock, so an unchanged ledger
    renders the same. ``partial`` is the manifest's partial nights (filled
    from a point-of-sale summary: net sales and voids only); None is unknown.
    """
    week_night = night - timedelta(days=7)
    week = (
        _compare(records, entity, (night, night), (week_night, week_night))
        if week_night in nights
        else None
    )
    # The compared nights that carry net sales and voids only (SPEC 4.3, U4).
    week_partial = [
        candidate
        for candidate in (night, week_night)
        if partial is not None and candidate in partial and candidate in nights
    ]
    if week is not None and week_partial:
        week = _without_partial_metrics(week)
    month_window, prior_window = aligned_month_windows(night)
    month = _compare(
        records,
        entity,
        (month_window.start_date, month_window.end_date),
        (prior_window.start_date, prior_window.end_date),
    )
    current = _coverage(reviews, nights, month_window.start_date, night)
    prior = _coverage(reviews, nights, prior_window.start_date, prior_window.end_date)
    known = current is not None and prior is not None
    in_review = (current[0] + prior[0]) if current and prior else 0
    missing = (current[1] + prior[1]) if current and prior else 0
    night_reviewed = reviews is not None and night in reviews
    week_reviewed = reviews is not None and week_night in reviews
    partial_known = partial is not None
    partial_now = count_partial_nights(partial, month_window.start_date, night)
    partial_prior = count_partial_nights(
        partial, prior_window.start_date, prior_window.end_date
    )
    partial_in_months = (partial_now or 0) + (partial_prior or 0)

    # Why a comparison resting on a partial night is at most Medium: the
    # headlines that night lacks are not compared (week) or rest on fewer
    # nights (month). Partial nights never make a briefing Low by themselves.
    # Kept short: with every headline reading "no comparison available" a
    # body must still fit in 250 words.
    if len(week_partial) > 1:
        week_partial_note = "both nights are partial"
    elif week_partial == [night]:
        week_partial_note = "this night is partial"
    else:
        week_partial_note = "the week-earlier night is partial"
    partial_unknown_note = "partial nights are unknown"
    months_partial_note = (
        f"{partial_in_months} partial night{'' if partial_in_months == 1 else 's'}"
    )

    # Overall confidence: Low when the night itself is in review,
    # has no week-earlier night, or the two month windows miss 3+ nights;
    # High only with known, clean coverage, known partial nights, none of them
    # compared or in either month, and prior-month data; else Medium.
    medium: list[str] = []
    if night_reviewed:
        overall, reason = "Low", "this night is in review"
    elif week is None:
        overall, reason = "Low", "there is no week-earlier night to compare"
    elif known and missing >= _MISSING_FOR_LOW:
        overall, reason = "Low", f"{missing} nights are missing across both months"
    else:
        if not known:
            medium.append("coverage is unknown")
        if month is None:
            medium.append("no prior-month data")
        if known and (in_review or missing):
            medium.append(_gaps(in_review, missing))
        if not partial_known and known:
            # Without a manifest both are unknown; the first reason says so.
            medium.append(partial_unknown_note)
        if week_partial:
            medium.append(week_partial_note)
        elif partial_in_months:
            medium.append(months_partial_note)
        if medium:
            overall, reason = "Medium", _rationale(medium)
        else:
            overall, reason = "High", "no night in either month is flagged or partial"

    if week is None:
        week_level, week_note = "Low", "nothing to compare"
    else:
        week_reasons: list[str] = []
        if week_partial:
            week_reasons.append(week_partial_note)
        if (night_reviewed or week_reviewed) and week_partial:
            week_reasons.append("a night is in review")
        elif night_reviewed or week_reviewed:
            week_reasons.append("a night in the comparison is in review")
        if not partial_known:
            week_reasons.append(partial_unknown_note)
        if week_reasons:
            week_level, week_note = "Medium", _rationale(week_reasons)
        else:
            week_level, week_note = "High", "neither night is flagged or partial"

    if month is None:
        month_level, month_note = "Low", "nothing to compare"
    else:
        month_reasons: list[str] = []
        if not known and not partial_known:
            month_reasons.append("coverage and partial nights are unknown")
        elif not known:
            month_reasons.append("coverage is unknown")
        elif in_review or missing:
            month_reasons.append(_gaps(in_review, missing))
        if not partial_known and known:
            month_reasons.append(partial_unknown_note)
        elif partial_in_months:
            month_reasons.append(months_partial_note)
        if month_reasons:
            month_level, month_note = "Medium", _rationale(month_reasons)
        else:
            month_level, month_note = (
                "High",
                "no night in either month is flagged or partial",
            )

    month_label = month_window.label or "Month to date"
    prior_label = prior_window.label or "the prior month"
    body = [
        f"# {_day(night)}",
        "",
        "Relative figures only: changes, never amounts.",
        "",
        "## How did the night compare?",
        "",
        f"### Against {_day(week_night)}",
        "",
        *_bullets(week),
        # A blank line first: a plain line right after a list item would be
        # a lazy continuation of the last bullet in CommonMark.
        *(["", _partial_line(week_partial)] if week_partial else []),
        "",
        f"**Confidence:** {week_level} — {week_note}.",
        "",
        "## How is the month going?",
        "",
        f"### {month_label} against {prior_label}",
        "",
        *_bullets(month),
        "",
        f"**Confidence:** {month_level} — {month_note}.",
        "",
        "## How much weight does this bear?",
        "",
        "### Data coverage",
        "",
        f"- Nights in review this month: {_text(current, 0)}",
        f"- Nights missing this month: {_text(current, 1)}",
        f"- Nights in review, comparison days: {_text(prior, 0)}",
        f"- Nights missing, comparison days: {_text(prior, 1)}",
        f"- Partial nights this month: {_count_text(partial_now)}",
        f"- Partial nights, comparison days: {_count_text(partial_prior)}",
        f"- This night: {'in review' if night_reviewed else 'not flagged'}",
        "",
        f"**Confidence:** {overall} — {reason}.",
    ]

    week_sales = week["net_sales"] if week else _NO_COMPARISON
    month_sales = month["net_sales"] if month else _NO_COMPARISON
    summary = (
        f"Net sales {week_sales} on the week before; month to date "
        f"{month_sales}. Confidence: {overall.lower()}."
    )
    tags = ["restaurantos", "service-night", f"confidence:{overall.lower()}"]
    if night_reviewed:
        tags.append("in-review")
    return {
        "date": night.isoformat(),
        "title": f"{_day(night)}, {night.year}",
        "summary": summary,
        "body_markdown": "\n".join(body) + "\n",
        "tags": tags,
    }


def content_hash(content: dict[str, Any]) -> str:
    canonical = json.dumps(
        {field: content[field] for field in _CONTENT_FIELDS},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def format_stamp(moment: datetime) -> str:
    """Fixed-width RFC 3339 UTC in whole seconds: string order is time order.

    Whole seconds also keep digit runs out of the feed that could be mistaken
    for (or hide) a figure; the writer spaces runs at least a second apart.
    """
    return f"{moment.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}"


def parse_stamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True, slots=True)
class RefreshResult:
    briefings: int
    changed: int
    tombstones: int
    path: Path


def _entity_records(
    records: list[OperationalRecord], entity: str | None
) -> tuple[str, list[OperationalRecord]]:
    if entity is None:
        entities = {record.entity for record in records}
        if len(entities) != 1:
            raise ValueError("--entity is required when the ledger has several")
        entity = entities.pop()
    selected = [record for record in records if record.entity == entity]
    if not selected:
        raise ValueError("the ledger has no service nights for that entity")
    return entity, selected


def _service_nights(records: list[OperationalRecord]) -> set[date]:
    nights: set[date] = set()
    for record in records:
        try:
            nights.add(date.fromisoformat(record.period))
        except ValueError:
            continue
    return nights


_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


@dataclass(frozen=True, slots=True)
class _Existing:
    """What a refresh starts from: the entries, generation and file text."""

    entries: dict[str, dict[str, Any]]
    generation: str | None
    text: str | None


_ABSENT = _Existing(entries={}, generation=None, text=None)


def _read_existing(path: Path) -> _Existing:
    """The current briefings file, or nothing if it is absent or damaged.

    A damaged file (unreadable, not UTF-8, not JSON, not a briefings file, or
    a stamp the writer would not have written) is reported on stderr and
    treated as absent, so the refresh rebuilds it from the ledger instead of
    failing every night until someone deletes it by hand.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _ABSENT
    except (OSError, UnicodeDecodeError) as error:
        _report_damage(path, f"cannot be read ({type(error).__name__})")
        return _ABSENT
    try:
        snapshot = parse_entries(json.loads(text))
        for entry in snapshot.entries:
            if not _STAMP.fullmatch(entry.updated_at):
                raise ValueError("a briefing has a malformed updated_at")
            # The next run stamps at least a second later; a stamp at the end
            # of time would make every refresh fail, so it is damage too.
            parse_stamp(entry.updated_at) + timedelta(seconds=1)
    except OverflowError:
        _report_damage(path, "is not a valid briefings file (a stamp is out of range)")
        return _ABSENT
    except ValueError as error:
        _report_damage(path, f"is not a valid briefings file ({error})")
        return _ABSENT
    return _Existing(
        entries={entry.id: dict(entry.payload) for entry in snapshot.entries},
        generation=snapshot.generation,
        text=text,
    )


def _report_damage(path: Path, problem: str) -> None:
    print(
        f"restaurantos briefings-refresh: {path} {problem}; rebuilding it from "
        "the ledger (every briefing gets a fresh updated_at, so the phone "
        "re-downloads each one once)",
        file=sys.stderr,
    )


def _new_generation() -> str:
    generation = secrets.token_urlsafe(12)
    assert GENERATION.fullmatch(generation)
    return generation


class PosixHostRequiredError(RuntimeError):
    """The briefings writer needs POSIX file locking (``fcntl.flock``)."""


_POSIX_ONLY = (
    "the briefings file can only be written on a POSIX host "
    "(its refresh lock needs fcntl.flock)"
)


def _flock_module() -> Any:
    """``fcntl``, imported here so the module itself imports anywhere."""
    try:
        import fcntl
    except ImportError:
        raise PosixHostRequiredError(_POSIX_ONLY) from None
    return fcntl


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive ``flock`` on ``<path>.lock``; wait for any holder.

    The lock file is private (mode 600) and is left in place: removing it
    would let a waiter lock an unlinked inode while a newcomer locks a new
    file. The lock is released when the descriptor closes, even on a crash.
    """
    fcntl = _flock_module()
    lock_path = path.with_name(path.name + ".lock")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        if os.fstat(handle).st_mode & 0o077:
            os.fchmod(handle, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        os.close(handle)


def _write_private(path: Path, text: str) -> None:
    """Atomic write, mode 600: the file sits under the private data root."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def refresh_briefings(
    history_path: str | Path,
    manifest_path: str | Path,
    briefings_path: str | Path,
    *,
    entity: str | None = None,
    now: datetime | None = None,
) -> RefreshResult:
    """Build or refresh the briefings file from the ledger.

    Unchanged content keeps its ``updated_at``, so an unchanged ledger leaves
    the file byte-for-byte as it was. A changed or new briefing, and a
    tombstone for a night that left the ledger, get one stamp for this run,
    strictly later (by at least a second) than every stamp already in the file.

    Raises ``PosixHostRequiredError`` on a host without ``fcntl``, before anything
    is created.
    """
    destination = Path(briefings_path)
    history = Path(history_path)
    _flock_module()
    # A ledger that is missing, cannot be stat'ed, is a directory or is any
    # other non-regular file (a FIFO, socket or device) writes nothing, not
    # even the lock file or its directory, and a FIFO is never opened (that
    # would block). This uses stat(), not exists(), on purpose: stat() raises
    # the real error (FileNotFoundError, PermissionError, ...), so it is
    # reported as is, where exists() would hide a permission problem as
    # "missing". It follows symlinks, so a link to a regular file is fine.
    mode = history.stat().st_mode
    if stat.S_ISDIR(mode):
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(history))
    if not stat.S_ISREG(mode):
        raise OSError(
            errno.EINVAL, "the nightly ledger is not a regular file", str(history)
        )
    # Race: the ledger can still be deleted or replaced between this check and
    # the read under the lock. The refresh then fails on that read (non-zero
    # exit, nothing written) after creating only the lock file and directory.
    with _exclusive_lock(destination):
        # The ledger is read under the lock, so a refresh that waited for it
        # builds from the ledger as it is now, not as it was when it started.
        return _refresh_locked(destination, history, Path(manifest_path), entity, now)


def _refresh_locked(
    destination: Path,
    history_path: Path,
    manifest_path: Path,
    entity: str | None,
    now: datetime | None,
) -> RefreshResult:
    """The read-compute-write of ``refresh_briefings``, under its lock."""
    records = read_history_jsonl(history_path)
    entity, selected = _entity_records(records, entity)
    nights = _service_nights(selected)
    reviews = read_reviews(manifest_path)
    partial = read_partial_nights(manifest_path)
    current = _read_existing(destination)
    existing = current.entries

    latest = max(
        (parse_stamp(str(item["updated_at"])) for item in existing.values()),
        default=None,
    )
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    moment = moment.replace(microsecond=0)
    if latest is not None and moment <= latest:
        moment = latest + timedelta(seconds=1)
    stamp = format_stamp(moment)

    entries: dict[str, dict[str, Any]] = {}
    changed = 0
    for night in sorted(nights):
        ident = briefing_id(entity, night)
        content = render_briefing(selected, entity, night, nights, reviews, partial)
        digest = content_hash(content)
        previous = existing.get(ident)
        if (
            previous is not None
            and not previous.get("deleted")
            and previous.get("content_hash") == digest
        ):
            entries[ident] = previous
            continue
        changed += 1
        # created_at is kept for a changed live briefing; a new night, or one
        # returning after a tombstone, is created by this run.
        live = previous is not None and not previous.get("deleted")
        created = previous.get("created_at") if live and previous else None
        entries[ident] = {
            "id": ident,
            **content,
            "content_hash": digest,
            "created_at": created if isinstance(created, str) else stamp,
            "updated_at": stamp,
            "deleted": False,
        }

    for ident, previous in existing.items():
        if ident in entries:
            continue
        if previous.get("deleted"):
            entries[ident] = previous
            continue
        changed += 1
        entries[ident] = {
            "id": ident,
            "date": previous.get("date"),
            "updated_at": stamp,
            "deleted": True,
        }
    tombstones = sum(1 for entry in entries.values() if entry.get("deleted"))

    document = {
        "format": FILE_FORMAT,
        "figures": FIGURES_POLICY,
        # Kept across refreshes; new when the file is built from scratch, so
        # cursors issued for an earlier file are refused, not misread.
        "generation": current.generation or _new_generation(),
        "briefings": [entries[ident] for ident in sorted(entries)],
    }
    text = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if current.text != text:
        _write_private(destination, text)
    elif destination.stat().st_mode & 0o077:
        # Unchanged, but loosened by hand: the file is private host state.
        destination.chmod(0o600)
    return RefreshResult(
        briefings=len(nights),
        changed=changed,
        tombstones=tombstones,
        path=destination,
    )
