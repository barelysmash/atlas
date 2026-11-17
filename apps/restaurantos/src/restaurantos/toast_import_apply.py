"""Explicit, audited approval of a staged Toast night, and how the ledger reads it.

Staging (toast_email_intake) never touches the ledger. This module is the
other half: a person approves one staged night by date, and the nightly
rebuild then adds that night to the ledger as a *partial* night.

Partial means net sales and voids only. A Toast sales summary has no labor
and no reservations. Its guest count spans every service mode and has not
been checked against the cover count the nightly emails report, and its
discount total has not been checked against the emails' comps, so neither is
written to the ledger. Both stay in the private approval file for later.

A night that already has a nightly email is never overridden: the email wins
and the approved import is ignored for that date.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from restaurantos.nightly import NightlyReport
from restaurantos.toast_email_intake import preview_sales_summary

TOAST_SOURCE = "toast_sales_summary"
AUDIT_LOG = "audit.jsonl"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ApprovedToastNight:
    service_date: date
    net_sales: float
    void_amount: float | None
    sha256: str


def _staged_candidates(review_root: Path, service_date: date) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if not review_root.is_dir():
        return candidates
    for item in sorted(review_root.iterdir()):
        metadata = item / "review.json"
        if not _SHA256.fullmatch(item.name) or not metadata.is_file():
            continue
        try:
            review = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            isinstance(review, dict)
            and review.get("service_date") == service_date.isoformat()
            and review.get("sha256") == item.name
            and isinstance(review.get("filename"), str)
        ):
            candidates.append(review)
    return candidates


def _append_audit(approved_root: Path, event: dict[str, Any]) -> None:
    # Dates, hashes and actions only. Figures never enter the audit log.
    path = approved_root / AUDIT_LOG
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    path.chmod(0o600)


def approve_staged_import(
    review_root: str | Path,
    approved_root: str | Path,
    service_date: date,
    *,
    sha256: str | None = None,
    replace: bool = False,
    now: datetime | None = None,
) -> ApprovedToastNight:
    """Approve the staged Toast summary for one service date.

    The staged ZIP is validated again from its bytes; the figures in
    review.json are not trusted. Raises ValueError when nothing is staged for
    the date, when several different files are staged and none was chosen, or
    when a different file is already approved and ``replace`` is not set.
    """
    staging = Path(review_root)
    destination_root = Path(approved_root)

    candidates = _staged_candidates(staging, service_date)
    if sha256 is not None:
        candidates = [item for item in candidates if item["sha256"] == sha256]
    if not candidates:
        raise ValueError(f"no staged Toast summary for {service_date.isoformat()}")
    if len(candidates) > 1:
        choices = ", ".join(item["sha256"][:12] for item in candidates)
        raise ValueError(
            f"several staged files for {service_date.isoformat()} ({choices}); "
            "choose one with its sha256"
        )

    review = candidates[0]
    digest: str = review["sha256"]
    data = (staging / digest / "source.zip").read_bytes()
    preview = preview_sales_summary(review["filename"], data)
    if preview.source_sha256 != digest:
        raise ValueError("staged ZIP does not match its recorded sha256")
    if preview.service_date != service_date.isoformat():
        raise ValueError("staged ZIP is for a different service date")

    destination_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = destination_root / f"{service_date.isoformat()}.json"
    action = "approved"
    if destination.exists():
        existing = json.loads(destination.read_text(encoding="utf-8"))
        if existing.get("sha256") == digest:
            action = "reapproved_same_file"
        elif not replace:
            raise ValueError(
                f"a different file is already approved for "
                f"{service_date.isoformat()}; pass replace to switch"
            )
        else:
            action = "replaced"

    approved_at = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    payload = {
        "source": TOAST_SOURCE,
        "service_date": service_date.isoformat(),
        "sha256": digest,
        "filename": review["filename"],
        "approved_at": approved_at,
        "net_sales": preview.net_sales,
        "void_amount": preview.void_amount,
        # Held back from the ledger until checked against the nightly emails.
        "unapplied": {
            "guests": preview.guests,
            "orders": preview.orders,
            "sales_discounts": preview.sales_discounts,
        },
    }
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    temporary.chmod(0o600)
    temporary.replace(destination)

    _append_audit(
        destination_root,
        {
            "action": action,
            "service_date": service_date.isoformat(),
            "sha256": digest,
            "at": approved_at,
        },
    )
    return ApprovedToastNight(
        service_date=service_date,
        net_sales=preview.net_sales,
        void_amount=preview.void_amount,
        sha256=digest,
    )


def _money(value: object, name: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{path.name}: {name} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{path.name}: {name} must be a non-negative number")
    return number


def read_approved_nights(approved_root: str | Path) -> list[ApprovedToastNight]:
    """Load every approved night. A malformed file is an error, not a skip."""
    root = Path(approved_root)
    if not root.is_dir():
        return []
    nights: list[ApprovedToastNight] = []
    for path in sorted(root.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("source") != TOAST_SOURCE:
            raise ValueError(f"{path.name}: not an approved Toast night")
        try:
            service_date = date.fromisoformat(str(payload.get("service_date")))
        except ValueError:
            raise ValueError(f"{path.name}: invalid service_date") from None
        if path.stem != service_date.isoformat():
            raise ValueError(f"{path.name}: file name does not match service_date")
        digest = payload.get("sha256")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError(f"{path.name}: invalid sha256")
        void_amount = payload.get("void_amount")
        nights.append(
            ApprovedToastNight(
                service_date=service_date,
                net_sales=_money(payload.get("net_sales"), "net_sales", path),
                void_amount=(
                    None
                    if void_amount is None
                    else _money(void_amount, "void_amount", path)
                ),
                sha256=digest,
            )
        )
    return nights


def approved_reports(
    nights: list[ApprovedToastNight],
    restaurant: str,
) -> list[NightlyReport]:
    """Partial nightly reports: net sales and voids, nothing else."""
    return [
        NightlyReport(
            restaurant=restaurant,
            service_date=night.service_date,
            net_sales=night.net_sales,
            voids=night.void_amount,
        )
        for night in nights
    ]
