from datetime import UTC, datetime

from restaurantos.nightly_backfill import (
    NightlyEmailMessage,
    backfill_nightly_emails,
    infer_service_date,
)


def message(
    message_id: str,
    subject: str,
    body: str,
    sent_at: datetime,
) -> NightlyEmailMessage:
    return NightlyEmailMessage(
        message_id=message_id,
        subject=subject,
        body=body,
        sent_at=sent_at,
    )


def test_subject_date_handles_after_midnight_delivery():
    service_date, warnings = infer_service_date(
        "EOD 07.31.26",
        datetime(2026, 8, 1, 0, 16, tzinfo=UTC),
    )

    assert service_date.isoformat() == "2026-07-31"
    assert warnings == ()


def test_implausible_subject_date_falls_back_to_sent_date_and_flags():
    service_date, warnings = infer_service_date(
        "EOD 06.01.26",
        datetime(2026, 7, 1, 23, 17, tzinfo=UTC),
    )

    assert service_date.isoformat() == "2026-07-01"
    assert warnings == ("subject_sent_date_mismatch",)


def test_yearless_subject_uses_nearest_calendar_year():
    service_date, warnings = infer_service_date(
        "EOD 12/31",
        datetime(2027, 1, 1, 0, 10, tzinfo=UTC),
    )

    assert service_date.isoformat() == "2026-12-31"
    assert warnings == ()


def test_correction_reply_amends_primary_without_becoming_duplicate_night():
    primary = message(
        "primary",
        "EOD 6/22",
        """
        Happy Monday.
        SPLH: $ 72.00
        Labor: $ 3,500.00
        Hours: $ 250.00
        Reservations: 230
        """,
        datetime(2026, 6, 22, 23, 11, tzinfo=UTC),
    )
    correction = message(
        "correction",
        "Re: EOD 6/22",
        """
        Forgot covers!
        Starting: 240 End: 260 Atrium: 114

        On Mon, Jun 22, 2026 at 11:11 PM Liv wrote:
        SPLH: $ 72.00
        Reservations: 230
        """,
        datetime(2026, 6, 22, 23, 15, tzinfo=UTC),
    )

    result = backfill_nightly_emails((primary, correction))

    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.report.reservation_covers == 240
    assert entry.report.dining_room_covers == 260
    assert entry.report.bar_atrium_covers == 114
    assert entry.report.total_covers == 374
    assert entry.source_message_ids == ("primary", "correction")
    assert "amended_from_reply" in entry.warnings


def test_plain_reply_and_reaction_are_skipped():
    primary = message(
        "primary",
        "EOD 08.14.26",
        "SPLH: $ 80.00\nLabor: $ 4000\nHours: $ 250\nTotal: 400\n",
        datetime(2026, 8, 14, 23, 55, tzinfo=UTC),
    )
    reply = message(
        "reply",
        "Re: EOD 08.14.26",
        "Gracias Paul\n\nOn Fri, Aug 14, 2026 at 11:55 PM Paul wrote:\nSPLH: $ 80",
        datetime(2026, 8, 15, 0, 5, tzinfo=UTC),
    )
    reaction = message(
        "reaction",
        "Re: EOD 08.14.26",
        "💖 Carlos Diaz reacted via Gmail",
        datetime(2026, 8, 15, 0, 6, tzinfo=UTC),
    )

    result = backfill_nightly_emails((primary, reply, reaction))

    assert len(result.entries) == 1
    assert set(result.skipped_message_ids) == {"reply", "reaction"}


def test_forward_is_primary_fallback_when_original_is_missing():
    forwarded = message(
        "forwarded",
        "Fwd: EOD 7/22",
        """
        ---------- Forwarded message ---------
        EOD 7/22
        SPLH: $ 76.50
        Labor: $ 3,400.00
        Hours: $ 240.00
        Reservations: 220
        Dining Room: 260
        Bar / Atrium: 110
        Total: 370
        """,
        datetime(2026, 7, 23, 7, 49, tzinfo=UTC),
    )

    result = backfill_nightly_emails((forwarded,))

    assert len(result.entries) == 1
    assert result.entries[0].report.total_covers == 370
    assert result.entries[0].report.service_date.isoformat() == "2026-07-22"


def test_multiple_direct_reports_choose_latest_and_request_review():
    early = message(
        "early",
        "Fonda SM EOD Report, 7/15/2026",
        "SPLH: $ 70\nLabor: $ 3000\nHours: $ 200\nTotal: 300\n",
        datetime(2026, 7, 15, 0, 35, tzinfo=UTC),
    )
    late = message(
        "late",
        "EOD 07.15.26",
        "SPLH: $ 90\nLabor: $ 4500\nHours: $ 300\nTotal: 450\n",
        datetime(2026, 7, 15, 23, 0, tzinfo=UTC),
    )

    result = backfill_nightly_emails((early, late))

    assert len(result.entries) == 1
    assert result.entries[0].report.total_covers == 450
    assert "multiple_primary_reports" in result.entries[0].warnings
    assert result.review[0].reasons == ("multiple_primary_reports",)


def test_reply_with_metric_block_updates_only_present_fields():
    primary = message(
        "primary",
        "EOD 07.26.26",
        """
        SPLH: $ 100.00
        Labor: $ 4,500.00
        Hours: $ 320.00
        Reservations: 300
        Dining Room: 346
        Bar / Atrium: 276
        Total: 622
        """,
        datetime(2026, 7, 26, 0, 30, tzinfo=UTC),
    )
    correction = message(
        "correction",
        "Re: EOD 07.26.26",
        """
        SPLH: $ 109.83
        Labor: $ 4535.46
        Hours: $ 324.18
        Voids: $ 190.50

        On Sun, Jul 26, 2026 at 12:30 AM Paul wrote:
        SPLH: $ 100.00
        Total: 622
        """,
        datetime(2026, 7, 26, 0, 36, tzinfo=UTC),
    )

    result = backfill_nightly_emails((primary, correction))
    report = result.entries[0].report

    assert report.reported_splh == 109.83
    assert report.labor_cost_actual == 4535.46
    assert report.labor_hours_actual == 324.18
    assert report.voids == 190.50
    assert report.total_covers == 622


def test_obvious_labor_hour_transposition_is_repaired_and_flagged():
    primary = message(
        "primary",
        "EOD 6/22",
        """
        SPLH: $69.98
        Labor: $227.54
        Horas: $3557.97
        Total: 374
        """,
        datetime(2026, 6, 22, 23, 11, tzinfo=UTC),
    )

    result = backfill_nightly_emails((primary,))
    entry = result.entries[0]

    assert entry.report.labor_cost_actual == 3557.97
    assert entry.report.labor_hours_actual == 227.54
    assert "labor_hours_probably_swapped" in entry.warnings
