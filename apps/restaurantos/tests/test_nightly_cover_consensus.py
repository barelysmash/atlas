from datetime import date

from restaurantos.nightly import normalize_nightly_report
from restaurantos.nightly_email import parse_nightly_email


def _guest_record(report):
    return next(
        record
        for record in normalize_nightly_report(report)
        if record.metric == "guest_count"
    )


def test_concise_seated_guest_narrative_is_a_total_fallback():
    report = parse_nightly_email(
        """
        Tonight we started with 232 covers. We seated 397 guests.
        SPLH: $78.01
        Labor: $4,054.15
        Hours: $275.74
        Reservations: 232
        """,
        service_date=date(2026, 8, 19),
    )

    assert report.total_covers is None
    assert report.narrative_total_covers == 397
    assert report.effective_total_covers == 397
    assert _guest_record(report).value == 397


def test_room_and_narrative_consensus_wins_over_structured_mismatch():
    report = parse_nightly_email(
        """
        We started with 238 covers and finished seating 415 guests.
        Reservations: 238
        Dining Room: 283
        Bar / Atrium: 132
        Total: 416
        """,
        service_date=date(2026, 8, 20),
    )

    assert report.total_covers == 416
    assert report.room_total_covers == 415
    assert report.narrative_total_covers == 415
    assert report.effective_total_covers == 415
    assert "room_total_mismatch" in report.quality_flags
    assert "narrative_total_mismatch" not in report.quality_flags

    guest = _guest_record(report)
    assert guest.value == 415
    assert guest.dimensions["derived_from_rooms"] is True


def test_narrative_total_is_used_when_structured_and_room_totals_are_absent():
    report = parse_nightly_email(
        """
        We started with 238 covers and finished seating 415 guests.
        SPLH: $70.74
        """,
        service_date=date(2026, 8, 20),
    )

    assert report.total_covers is None
    assert report.room_total_covers is None
    assert report.narrative_total_covers == 415
    assert report.effective_total_covers == 415
    assert _guest_record(report).value == 415
