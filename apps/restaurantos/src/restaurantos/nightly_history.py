import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atlas_core.derived_metric_engine import derive_metrics
from atlas_core.operational_record import OperationalRecord

from restaurantos.metrics import NIGHTLY_DERIVED_METRICS
from restaurantos.nightly import normalize_nightly_report
from restaurantos.nightly_backfill import BackfillResult


@dataclass(frozen=True, slots=True)
class NightlyHistoryManifest:
    service_nights: int
    record_count: int
    first_service_date: str | None
    last_service_date: str | None
    skipped_message_count: int
    review_count: int
    warning_counts: tuple[tuple[str, int], ...]
    review_reason_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class NightlyHistory:
    records: tuple[OperationalRecord, ...]
    manifest: NightlyHistoryManifest


def _record_sort_key(record: OperationalRecord) -> tuple[str, str, str, str]:
    dimensions = json.dumps(record.dimensions, sort_keys=True, default=str)
    return record.period, record.metric, record.category, dimensions


def _manifest(
    result: BackfillResult,
    records: list[OperationalRecord],
) -> NightlyHistoryManifest:
    service_dates = sorted(
        entry.report.service_date.isoformat() for entry in result.entries
    )
    warning_counts = Counter(
        warning for entry in result.entries for warning in entry.warnings
    )
    review_reason_counts = Counter(
        reason for review in result.review for reason in review.reasons
    )

    return NightlyHistoryManifest(
        service_nights=len(result.entries),
        record_count=len(records),
        first_service_date=service_dates[0] if service_dates else None,
        last_service_date=service_dates[-1] if service_dates else None,
        skipped_message_count=len(result.skipped_message_ids),
        review_count=len(result.review),
        warning_counts=tuple(sorted(warning_counts.items())),
        review_reason_counts=tuple(sorted(review_reason_counts.items())),
    )


def build_nightly_history(
    result: BackfillResult,
    *,
    include_derived_metrics: bool = True,
) -> NightlyHistory:
    """Build canonical daily history from a reconciled nightly backfill."""
    records: list[OperationalRecord] = []

    for entry in result.entries:
        nightly_records = normalize_nightly_report(entry.report)
        if include_derived_metrics:
            nightly_records = derive_metrics(nightly_records, NIGHTLY_DERIVED_METRICS)
        records.extend(nightly_records)

    records.sort(key=_record_sort_key)
    return NightlyHistory(
        records=tuple(records),
        manifest=_manifest(result, records),
    )


def _serializable_dimensions(
    dimensions: dict[str, Any],
    *,
    include_source_message_ids: bool,
) -> dict[str, Any]:
    if include_source_message_ids:
        return dict(dimensions)
    return {
        key: value for key, value in dimensions.items() if key != "source_message_id"
    }


def _record_payload(
    record: OperationalRecord,
    *,
    include_source_message_ids: bool,
) -> dict[str, Any]:
    return {
        "source": record.source,
        "entity": record.entity,
        "period": record.period,
        "category": record.category,
        "metric": record.metric,
        "value": record.value,
        "dimensions": _serializable_dimensions(
            record.dimensions,
            include_source_message_ids=include_source_message_ids,
        ),
        "grain": record.grain,
        "aggregation": record.aggregation,
    }


def write_history_jsonl(
    path: str | Path,
    history: NightlyHistory,
    *,
    include_source_message_ids: bool = False,
) -> Path:
    """Atomically write deterministic operational facts as JSON Lines."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")

    lines = [
        json.dumps(
            _record_payload(
                record,
                include_source_message_ids=include_source_message_ids,
            ),
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in history.records
    ]
    temporary.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    temporary.replace(destination)
    return destination


def read_history_jsonl(path: str | Path) -> list[OperationalRecord]:
    """Load a persisted nightly fact ledger into canonical records."""
    records: list[OperationalRecord] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        records.append(
            OperationalRecord.create(
                source=payload["source"],
                entity=payload["entity"],
                period=payload["period"],
                category=payload["category"],
                metric=payload["metric"],
                value=payload["value"],
                dimensions=payload.get("dimensions", {}),
                grain=payload["grain"],
                aggregation=payload["aggregation"],
            )
        )
    return records


def write_history_manifest(path: str | Path, history: NightlyHistory) -> Path:
    """Write a privacy-safe audit manifest alongside the nightly ledger."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f"{destination.suffix}.tmp")
    manifest = history.manifest
    payload = {
        "service_nights": manifest.service_nights,
        "record_count": manifest.record_count,
        "first_service_date": manifest.first_service_date,
        "last_service_date": manifest.last_service_date,
        "skipped_message_count": manifest.skipped_message_count,
        "review_count": manifest.review_count,
        "warning_counts": dict(manifest.warning_counts),
        "review_reason_counts": dict(manifest.review_reason_counts),
    }
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
