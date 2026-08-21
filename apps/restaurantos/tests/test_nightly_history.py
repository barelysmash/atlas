import json
from datetime import UTC, datetime

from restaurantos.nightly_backfill import NightlyEmailMessage, backfill_nightly_emails
from restaurantos.nightly_history import (
    build_nightly_history,
    read_history_jsonl,
    write_history_jsonl,
    write_history_manifest,
)


def nightly_message(message_id: str = "private-message-id") -> NightlyEmailMessage:
    return NightlyEmailMessage(
        message_id=message_id,
        subject="EOD 08.19.26",
        body="""
        Net Sales: $21,500.00
        SPLH: $78.01
        Labor: $4,054.15
        Hours: 275.74
        Reservations: 232
        Dining Room: 262
        Bar / Atrium: 135
        Total: 397
        Total Comps: $343.74
        Voids: $23.50
        """,
        sent_at=datetime(2026, 8, 20, 0, 5, tzinfo=UTC),
    )


def test_build_history_normalizes_and_derives_metrics():
    result = backfill_nightly_emails((nightly_message(),))

    history = build_nightly_history(result)
    metrics = {record.metric for record in history.records}

    assert history.manifest.service_nights == 1
    assert history.manifest.first_service_date == "2026-08-19"
    assert history.manifest.last_service_date == "2026-08-19"
    assert "net_sales" in metrics
    assert "guest_count" in metrics
    assert "splh" in metrics
    assert "average_check" in metrics
    assert "reservation_share" in metrics
    assert "labor_cost_pct" in metrics


def test_jsonl_redacts_source_message_ids_by_default(tmp_path):
    result = backfill_nightly_emails((nightly_message(),))
    history = build_nightly_history(result, include_derived_metrics=False)

    path = write_history_jsonl(tmp_path / "nightly.jsonl", history)
    text = path.read_text(encoding="utf-8")

    assert "private-message-id" not in text
    assert "source_message_id" not in text

    payloads = [json.loads(line) for line in text.splitlines()]
    assert payloads
    assert all("id" not in payload for payload in payloads)
    assert all("timestamp" not in payload for payload in payloads)


def test_jsonl_can_explicitly_preserve_source_message_ids(tmp_path):
    result = backfill_nightly_emails((nightly_message(),))
    history = build_nightly_history(result, include_derived_metrics=False)

    path = write_history_jsonl(
        tmp_path / "nightly-private.jsonl",
        history,
        include_source_message_ids=True,
    )

    assert "private-message-id" in path.read_text(encoding="utf-8")


def test_jsonl_round_trip_preserves_canonical_measurements(tmp_path):
    result = backfill_nightly_emails((nightly_message(),))
    history = build_nightly_history(result, include_derived_metrics=False)
    path = write_history_jsonl(tmp_path / "nightly.jsonl", history)

    restored = read_history_jsonl(path)

    expected = [
        (
            record.source,
            record.entity,
            record.period,
            record.category,
            record.metric,
            record.value,
            record.grain,
            record.aggregation,
        )
        for record in history.records
    ]
    actual = [
        (
            record.source,
            record.entity,
            record.period,
            record.category,
            record.metric,
            record.value,
            record.grain,
            record.aggregation,
        )
        for record in restored
    ]

    assert actual == expected


def test_manifest_is_privacy_safe_and_counts_review_reasons(tmp_path):
    incomplete = NightlyEmailMessage(
        message_id="private-incomplete-id",
        subject="EOD 08.18.26",
        body="SPLH: $91.50\nTotal Comps: $902.50\n",
        sent_at=datetime(2026, 8, 19, 0, 5, tzinfo=UTC),
    )
    result = backfill_nightly_emails((incomplete,))
    history = build_nightly_history(result)

    path = write_history_manifest(tmp_path / "manifest.json", history)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["service_nights"] == 1
    assert payload["review_count"] == 1
    assert payload["review_reason_counts"]["missing_labor_cost_actual"] == 1
    assert payload["review_reason_counts"]["missing_labor_hours_actual"] == 1
    assert "private-incomplete-id" not in path.read_text(encoding="utf-8")
