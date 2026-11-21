"""Nights in review and partial nights, shared by the peer API and the writer.

Both read the manifest's per-night reviews and count, for a window, how many
flagged nights are in the ledger (in review) and how many are not (missing).
Both also read the manifest's partial nights (nights filled from an approved
point-of-sale summary, carrying net sales and voids only) and count them per
window.
Keeping the reading and the counting here means the two cannot drift, and the
nightly writer does not load the HTTP server to use them.

What this knows is limited to the manifest: a night is counted only when the
manifest flags it. A night whose report never arrived is not flagged, so it is
not counted anywhere.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

Reviews = Mapping[date, tuple[str, ...]]


def read_reviews(manifest_path: Path) -> dict[date, tuple[str, ...]] | None:
    """Nights in review, by service date, from the manifest.

    None means unknown: no manifest yet, an unreadable one, or one written
    before reviews were recorded by night. An empty dict means the manifest
    lists none.
    """
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError covers invalid JSON and bytes that are not UTF-8.
        return None
    entries = raw.get("reviews") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return None
    reviews: dict[date, tuple[str, ...]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            night = date.fromisoformat(str(entry.get("service_date")))
        except ValueError:
            continue
        reasons = entry.get("reasons")
        reviews[night] = tuple(
            str(reason) for reason in (reasons if isinstance(reasons, list) else [])
        )
    return reviews


@dataclass(frozen=True, slots=True)
class NightCounts:
    """Flagged nights in one window: counts only, never figures."""

    in_review: int
    missing: int
    reasons: dict[str, int]


def count_flagged_nights(
    reviews: Reviews | None,
    ledger_nights: Collection[date],
    start: date,
    end: date,
) -> NightCounts | None:
    """Flagged nights between ``start`` and ``end`` inclusive; None if unknown.

    In review: a flagged night that is in the ledger (usually one field
    flagged). Missing: a flagged night that is not (its report arrived but
    could not be read). ``ledger_nights`` are the entity's service nights.
    """
    if reviews is None:
        return None
    in_review = 0
    missing = 0
    reasons: dict[str, int] = {}
    for night, night_reasons in reviews.items():
        if not start <= night <= end:
            continue
        if night in ledger_nights:
            in_review += 1
        else:
            missing += 1
        for reason in night_reasons:
            reasons[reason] = reasons.get(reason, 0) + 1
    return NightCounts(
        in_review=in_review, missing=missing, reasons=dict(sorted(reasons.items()))
    )


def read_partial_nights(manifest_path: Path) -> set[date] | None:
    """Nights filled from an approved Toast summary: net sales and voids only.

    None means unknown: no manifest, an unreadable one, or one written before
    partial nights were recorded. An empty set means the manifest lists none.
    """
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError covers invalid JSON and bytes that are not UTF-8.
        return None
    entries = raw.get("partial_nights") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return None
    nights: set[date] = set()
    for entry in entries:
        try:
            nights.add(date.fromisoformat(str(entry)))
        except ValueError:
            continue
    return nights


def count_partial_nights(
    partial: Collection[date] | None, start: date, end: date
) -> int | None:
    """Partial nights between ``start`` and ``end`` inclusive; None if unknown."""
    if partial is None:
        return None
    return sum(1 for night in partial if start <= night <= end)
