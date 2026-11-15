"""Review-only Gmail intake for Toast exports; does not mutate the nightly ledger."""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from restaurantos.gmail_mailbox import GmailApiMailbox

MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024
MAX_ZIP_MEMBERS = 100
DATE_PATTERN = re.compile(r"SalesSummary_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.zip$", re.I)


@dataclass(frozen=True)
class ToastSalesPreview:
    service_date: str
    net_sales: float
    guests: int
    orders: int
    source_sha256: str


def _csv_rows(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    data = archive.read(name)
    text = data.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def preview_sales_summary(filename: str, data: bytes) -> ToastSalesPreview:
    """Validate a one-day Toast summary and cross-check its independent reports."""
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError("attachment exceeds size limit")
    match = DATE_PATTERN.fullmatch(Path(filename).name)
    if not match or match.group(1) != match.group(2):
        raise ValueError("expected a single-day SalesSummary_YYYY-MM-DD_YYYY-MM-DD.zip")
    date.fromisoformat(match.group(1))
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid ZIP") from exc
    with archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_MEMBERS:
            raise ValueError("too many ZIP members")
        if sum(member.file_size for member in members) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("ZIP uncompressed size exceeds limit")
        for member in members:
            if member.is_dir():
                continue
            path = Path(member.filename)
            if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
                raise ValueError("unsafe ZIP member path")
            if not member.filename.lower().endswith(".csv"):
                raise ValueError("unexpected non-CSV ZIP member")
        names = {member.filename for member in members}
        required = {"Revenue summary.csv", "Net sales summary.csv",
                    "Sales by day.csv", "Service mode summary.csv"}
        if not required <= names:
            raise ValueError("missing required Toast sales reports")
        revenue = _csv_rows(archive, "Revenue summary.csv")
        net = _csv_rows(archive, "Net sales summary.csv")
        daily = _csv_rows(archive, "Sales by day.csv")
        modes = _csv_rows(archive, "Service mode summary.csv")
        if not all((len(revenue) == 1, len(net) == 1, len(daily) == 1)):
            raise ValueError("expected one summary row per daily source")
        if daily[0].get("yyyyMMdd") != match.group(1).replace("-", ""):
            raise ValueError("CSV service date does not match ZIP filename")
        sales = float(net[0]["Net sales"])
        gross = float(net[0]["Gross sales"])
        discounts = float(net[0]["Sales discounts"])
        refunds = float(net[0]["Sales refunds"])
        revenue_sales = float(revenue[0]["Net sales"])
        daily_sales = float(daily[0]["Net sales"])
        mode_totals = [row for row in modes if row.get("Service mode") == "Total"]
        if len(mode_totals) != 1:
            raise ValueError("missing unique service mode total")
        mode_sales = float(mode_totals[0]["Net sales"])
        if any(abs(value - sales) > 0.011 for value in
               (gross + discounts + refunds, revenue_sales, daily_sales, mode_sales)):
            raise ValueError("conflicting Toast net sales")
        guests = int(daily[0]["Total guests"])
        orders = int(daily[0]["Total orders"])
        if guests < 0 or orders < 0 or sales < 0:
            raise ValueError("unexpected negative totals")
        if guests != int(mode_totals[0]["Total guests"]) or orders != int(mode_totals[0]["Total orders"]):
            raise ValueError("conflicting Toast guest or order totals")
        return ToastSalesPreview(match.group(1), sales, guests, orders,
                                 hashlib.sha256(data).hexdigest())


def _decode_data(encoded: str) -> bytes:
    return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))


def _attachment_parts(payload: dict) -> list[dict]:
    results = []
    def walk(part: dict) -> None:
        if part.get("filename") and isinstance(part.get("body"), dict):
            results.append(part)
        for child in part.get("parts") or []:
            if isinstance(child, dict):
                walk(child)
    walk(payload)
    return results


def stage_toast_gmail_imports(
    mailbox: GmailApiMailbox,
    destination: str | Path,
    *,
    query: str = "label:Atlas/Imports has:attachment -in:trash -in:spam",
) -> list[dict]:
    """Fetch matching Gmail attachments into immutable private staging.

    Files are never applied to the ledger. Errors are returned for review,
    and duplicates remain idempotent by attachment SHA-256.
    """
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    token = mailbox.token_provider.access_token()
    results: list[dict] = []
    for message_id in mailbox._message_ids(token, query):
        message = mailbox._get(
            f"users/{mailbox.user_id}/messages/{message_id}", token,
            {"format": "full"},
        )
        for part in _attachment_parts(message.get("payload", {})):
            filename = part["filename"]
            if not filename.lower().endswith(".zip"):
                results.append({"message_id": message_id, "filename": filename,
                                "status": "unsupported_review"})
                continue
            body = part["body"]
            encoded = body.get("data")
            if not encoded:
                attachment_id = body.get("attachmentId")
                if not attachment_id:
                    results.append({"message_id": message_id, "filename": filename,
                                    "status": "missing_attachment_body"})
                    continue
                encoded = mailbox._get(
                    f"users/{mailbox.user_id}/messages/{message_id}/attachments/{attachment_id}",
                    token,
                ).get("data")
            if not isinstance(encoded, str):
                results.append({"message_id": message_id, "filename": filename,
                                "status": "invalid_attachment_body"})
                continue
            declared_size = body.get("size", 0)
            if isinstance(declared_size, int) and declared_size > MAX_ATTACHMENT_BYTES:
                results.append({"message_id": message_id, "filename": filename,
                                "status": "too_large"})
                continue
            data = _decode_data(encoded)
            try:
                preview = preview_sales_summary(filename, data)
            except (ValueError, KeyError, UnicodeError, OverflowError, zipfile.BadZipFile) as exc:
                results.append({"message_id": message_id, "filename": filename,
                                "status": "validation_failed", "reason": str(exc)})
                continue
            item_dir = root / preview.source_sha256
            item_dir.mkdir(mode=0o700, exist_ok=True)
            original = item_dir / "source.zip"
            metadata = item_dir / "review.json"
            if original.exists() and original.read_bytes() != data:
                raise RuntimeError("SHA-256 archive collision")
            if not original.exists():
                original.write_bytes(data)
                original.chmod(0o600)
            review = {
                "status": "pending_review",
                "message_id": message_id,
                "filename": filename,
                "service_date": preview.service_date,
                "net_sales": preview.net_sales,
                "guests": preview.guests,
                "orders": preview.orders,
                "sha256": preview.source_sha256,
            }
            if not metadata.exists():
                metadata.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
                metadata.chmod(0o600)
            results.append(review)
    return results
