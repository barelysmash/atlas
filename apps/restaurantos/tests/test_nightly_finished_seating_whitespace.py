"""Guarded whole-service guest-count recovery for wrapped EOD narrative."""

from datetime import date

import pytest
from restaurantos.nightly import normalize_nightly_report
from restaurantos.nightly_backfill import _reply_head
from restaurantos.nightly_email import (
    _narrative_total,
    _unquoted_primary_head,
    parse_nightly_email,
)


@pytest.mark.parametrize(
    "separator",
    ["\n", "\r\n", "\t", "  ", " \n ", " "],
)
def test_finished_seating_whitespace_is_whole_service_total(separator):
    report = parse_nightly_email(
        f"We started with 210 reserved covers. We FINISHED{separator}"
        "SEATING 325 guests.",
        service_date=date(2026, 10, 1),
    )
    assert report.reservation_covers == 210
    assert report.total_covers is None
    assert report.narrative_total_covers == 325
    assert report.effective_total_covers == 325
    assert [
        record.value
        for record in normalize_nightly_report(report)
        if record.metric == "guest_count"
    ] == [325]


@pytest.mark.parametrize(
    "body",
    [
        "No count in this report.\nOn Fri, Oct 1, 2026 wrote:\n"
        "We finished\nseating 325 guests.",
        "No total in primary.\n-------- Forwarded message --------\n"
        "We finished\nseating 325 guests.",
        "Finished\nseating 325 guests in main dining only.",
        "We finished\nseating 325 reservations.",
        "We finished\nseating 325 people.",
    ],
)
def test_wrapped_phrase_not_unconditionally_a_qualified_total(body):
    report = parse_nightly_email(body, service_date=date(2026, 9, 1))
    assert report.narrative_total_covers is None


@pytest.mark.parametrize(
    "body",
    [
        "Hello.\nOn Fri, Oct 1, 2026 wrote:\nWe finished\nseating 325 guests.",
        "Hello.\n-------- Forwarded message --------\nWe finished\nseating 325 guests.",
        "We finished\nseating 325 guests.",
    ],
)
def test_primary_reply_boundary_matches_backfill(body):
    assert _unquoted_primary_head(body) == _reply_head(body)


def test_existing_single_space_match_retains_precedence_over_fallback():
    body = "Finished seating 310 guests. We finished\nseating 325 guests."
    assert _narrative_total(body) == 310


def test_structured_total_remains_authoritative_over_wrapped_total():
    report = parse_nightly_email(
        "We finished\nseating 325 guests.\nTotal: 326",
        service_date=date(2026, 9, 3),
    )
    assert report.narrative_total_covers == 325
    assert report.total_covers == 326
    assert report.effective_total_covers == 326
    assert "narrative_total_mismatch" in report.quality_flags
