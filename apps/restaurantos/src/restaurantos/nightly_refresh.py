import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from atlas_core.operational_record import OperationalRecord

from restaurantos.nightly_backfill import NightlyEmailMessage, backfill_nightly_emails
from restaurantos.nightly_history import (
    build_nightly_history,
    write_history_jsonl,
    write_history_manifest,
)
from restaurantos.operating_brief import (
    generate_operating_brief,
    summarize_operating_period,
)
from restaurantos.operating_brief_runner import write_operating_brief


@dataclass(frozen=True, slots=True)
class NightlyBriefWindow:
    start_date: date
    end_date: date
    label: str | None = None

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("brief end date cannot be before start date")


@dataclass(frozen=True, slots=True)
class NightlyRefreshResult:
    message_count: int
    service_nights: int
    record_count: int
    skipped_message_count: int
    review_count: int
    first_service_date: str | None
    last_service_date: str | None
    history_path: Path
    manifest_path: Path
    brief_path: Path | None = None


def _parse_sent_at(value: object, line_number: int) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"line {line_number}: sent_at must be an ISO datetime string")
    try:
        sent_at = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            f"line {line_number}: invalid sent_at ISO datetime {value!r}"
        ) from error
    if sent_at.utcoffset() is None:
        raise ValueError(f"line {line_number}: sent_at must include a timezone offset")
    return sent_at


def read_nightly_message_jsonl(path: str | Path) -> list[NightlyEmailMessage]:
    """Read a private JSONL source bundle without persisting it elsewhere."""
    messages: list[NightlyEmailMessage] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {line_number}: invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: expected a JSON object")

        required = ("message_id", "subject", "body", "sent_at")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(
                f"line {line_number}: missing required fields {', '.join(missing)}"
            )

        message_id = payload["message_id"]
        subject = payload["subject"]
        body = payload["body"]
        if not isinstance(message_id, str):
            raise ValueError(f"line {line_number}: message_id must be a string")
        if not isinstance(subject, str):
            raise ValueError(f"line {line_number}: subject must be a string")
        if not isinstance(body, str):
            raise ValueError(f"line {line_number}: body must be a string")
        if message_id in seen_ids:
            raise ValueError(f"line {line_number}: duplicate message_id {message_id!r}")
        seen_ids.add(message_id)

        messages.append(
            NightlyEmailMessage(
                message_id=message_id,
                subject=subject,
                body=body,
                sent_at=_parse_sent_at(payload["sent_at"], line_number),
            )
        )

    if not messages:
        raise ValueError("nightly message bundle is empty")
    return messages


def read_service_date_overrides(path: str | Path) -> dict[str, date]:
    """Read a private message-id to service-date override map."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("service date overrides must be a JSON object")

    overrides: dict[str, date] = {}
    for message_id, raw_date in payload.items():
        if not isinstance(message_id, str) or not isinstance(raw_date, str):
            raise ValueError("service date overrides must map strings to ISO dates")
        try:
            overrides[message_id] = date.fromisoformat(raw_date)
        except ValueError as error:
            raise ValueError(
                f"invalid service date override for {message_id!r}: {raw_date!r}"
            ) from error
    return overrides


def _validate_output_paths(
    history_path: Path,
    manifest_path: Path,
    brief_path: Path | None,
) -> None:
    outputs = [history_path.resolve(), manifest_path.resolve()]
    if brief_path is not None:
        outputs.append(brief_path.resolve())
    if len(outputs) != len(set(outputs)):
        raise ValueError("history, manifest, and brief outputs must use distinct paths")


def _render_brief(
    records: list[OperationalRecord],
    current: NightlyBriefWindow,
    compare: NightlyBriefWindow | None,
    restaurant: str,
) -> str:
    current_summary = summarize_operating_period(
        records,
        current.start_date,
        current.end_date,
        entity=restaurant,
        label=current.label,
    )
    previous_summary = None
    if compare is not None:
        previous_summary = summarize_operating_period(
            records,
            compare.start_date,
            compare.end_date,
            entity=restaurant,
            label=compare.label,
        )
    return generate_operating_brief(current_summary, previous_summary)


def rebuild_nightly_history(
    messages_path: str | Path,
    history_path: str | Path,
    manifest_path: str | Path,
    *,
    restaurant: str,
    overrides_path: str | Path | None = None,
    brief_path: str | Path | None = None,
    brief_window: NightlyBriefWindow | None = None,
    compare_window: NightlyBriefWindow | None = None,
) -> NightlyRefreshResult:
    """Deterministically rebuild private history from a complete source bundle."""
    if not restaurant.strip():
        raise ValueError("restaurant is required")
    if (brief_path is None) != (brief_window is None):
        raise ValueError("brief path and brief window must be provided together")
    if compare_window is not None and brief_window is None:
        raise ValueError("comparison window requires a brief window")

    history_destination = Path(history_path)
    manifest_destination = Path(manifest_path)
    brief_destination = Path(brief_path) if brief_path is not None else None
    _validate_output_paths(
        history_destination,
        manifest_destination,
        brief_destination,
    )

    messages = read_nightly_message_jsonl(messages_path)
    overrides: Mapping[str, date] | None = None
    if overrides_path is not None:
        overrides = read_service_date_overrides(overrides_path)

    backfill = backfill_nightly_emails(
        messages,
        restaurant=restaurant,
        service_date_overrides=overrides,
    )
    history = build_nightly_history(backfill)
    if not history.records or history.manifest.service_nights == 0:
        raise ValueError("source bundle produced no service-night history")

    brief = None
    if brief_window is not None:
        brief = _render_brief(
            list(history.records),
            brief_window,
            compare_window,
            restaurant,
        )

    write_history_jsonl(history_destination, history)
    write_history_manifest(manifest_destination, history)
    if brief_destination is not None and brief is not None:
        write_operating_brief(brief_destination, brief)

    manifest = history.manifest
    return NightlyRefreshResult(
        message_count=len(messages),
        service_nights=manifest.service_nights,
        record_count=manifest.record_count,
        skipped_message_count=manifest.skipped_message_count,
        review_count=manifest.review_count,
        first_service_date=manifest.first_service_date,
        last_service_date=manifest.last_service_date,
        history_path=history_destination,
        manifest_path=manifest_destination,
        brief_path=brief_destination,
    )
