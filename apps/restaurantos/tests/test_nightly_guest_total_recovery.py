"""Explicit whole-service guest totals, never partial-room estimates."""

from datetime import date

import pytest
from restaurantos.nightly import normalize_nightly_report
from restaurantos.nightly_email import parse_nightly_email


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "We finished with 375 guests all day, including the bar and Atrium.",
            375,
        ),
        ("We finished with 294 guests all day.", 294),
        ("We finished with 294 guests   all   day!", 294),
        ("We FINISHED WITH 294 GUESTS ALL DAY.", 294),
    ],
)
def test_explicit_all_day_guest_total_recovers_missing_covers(text, expected):
    report = parse_nightly_email(
        f"We started with 210 reserved covers. {text}",
        service_date=date(2026, 10, 26),
    )

    assert report.reservation_covers == 210
    assert report.total_covers is None
    assert report.narrative_total_covers == expected
    assert report.effective_total_covers == expected
    guest_records = [
        record
        for record in normalize_nightly_report(report)
        if record.metric == "guest_count"
    ]
    assert len(guest_records) == 1
    assert guest_records[0].value == expected


@pytest.mark.parametrize(
    "text",
    [
        "We finished with 200 guests in the main dining room.",
        "We started with 200 reserved covers.",
        "Bar / Atrium: 125\nReservations: 210",
        "We built that up to 245 in the main dining room.",
        "We finished with 210 guests for the early seating.",
    ],
)
def test_partial_counts_are_not_promoted_to_total_guests(text):
    report = parse_nightly_email(text, service_date=date(2026, 10, 26))
    assert report.effective_total_covers is None
    assert not [
        record
        for record in normalize_nightly_report(report)
        if record.metric == "guest_count"
    ]


def test_conflicting_structured_total_is_not_silently_overwritten():
    report = parse_nightly_email(
        "We finished with 294 guests all day.\nTotal: 295",
        service_date=date(2026, 10, 26),
    )
    assert report.narrative_total_covers == 294
    assert report.total_covers == 295
    assert report.effective_total_covers == 295
    assert "narrative_total_mismatch" in report.quality_flags
