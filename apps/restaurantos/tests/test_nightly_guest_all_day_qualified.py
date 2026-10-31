"""Whole-day guest counts with explicit bar/atrium inclusion only."""

from datetime import date

import pytest
from restaurantos.nightly import normalize_nightly_report
from restaurantos.nightly_email import parse_nightly_email


@pytest.mark.parametrize(
    ("text", "total"),
    [
        (
            "We finished with 310 guests in the main dining room and 405 "
            "all day, including the bar and Atrium.",
            405,
        ),
        (
            "We FINISHED WITH 310 GUESTS IN THE MAIN DINING ROOM AND 405 "
            "ALL DAY INCLUDING THE BAR AND ATRIUM!",
            405,
        ),
        (
            "We finished with 1,050 guests in the main dining room and "
            "1,240 all day, including the bar and Atrium.",
            1240,
        ),
        (
            "We finished with 300 guests in the main dining room and 120 "
            "in the bar and Atrium, bringing us to 420 guests all day!",
            420,
        ),
        (
            "We finished with 300 guests in the main dining room and 120 "
            "in the bar and Atrium, BRINGING US TO 420 GUESTS ALL DAY.",
            420,
        ),
    ],
)
def test_explicit_qualified_all_day_total(text, total):
    report = parse_nightly_email(
        f"We started with 210 reserved covers. {text}",
        service_date=date(2026, 10, 16),
    )
    assert report.reservation_covers == 210
    assert report.total_covers is None
    assert report.narrative_total_covers == total
    assert report.effective_total_covers == total
    assert [
        record.value
        for record in normalize_nightly_report(report)
        if record.metric == "guest_count"
    ] == [total]


@pytest.mark.parametrize(
    "text",
    [
        "We finished with 300 guests in the main dining room and 80 "
        "in the bar and Atrium.",
        "We finished with 300 guests in the main dining room and 405 all day.",
        "We finished with 300 guests in the main dining room and 405 all day, "
        "including only the main dining room.",
        "We finished with 300 guests in the main dining room and 405 in total, "
        "including the bar and Atrium.",
        "We finished with 300 guests in the main dining room and 120 in the "
        "bar and Atrium, bringing us to 420 guests for the first seating.",
        "We started with 210 reserved covers and built up to 300 "
        "in the main dining room.",
    ],
)
def test_no_unqualified_or_partial_total_promoted(text):
    report = parse_nightly_email(text, service_date=date(2026, 10, 16))
    assert report.narrative_total_covers is None


def test_explicit_structured_total_remains_authoritative():
    report = parse_nightly_email(
        "We finished with 300 guests in the main dining room and 405 "
        "all day, including the bar and Atrium.\nTotal: 406",
        service_date=date(2026, 10, 2),
    )
    assert report.narrative_total_covers == 405
    assert report.total_covers == 406
    assert report.effective_total_covers == 406
    assert "narrative_total_mismatch" in report.quality_flags
