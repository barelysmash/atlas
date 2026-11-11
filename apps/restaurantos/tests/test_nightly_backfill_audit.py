from datetime import UTC, date, datetime

from restaurantos.nightly_backfill import NightlyEmailMessage, backfill_nightly_emails


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


def test_non_report_eod_chatter_is_skipped_before_grouping():
    chatter = message(
        "chatter",
        "EOD",
        "I got left out?",
        datetime(2026, 7, 23, 5, 28, tzinfo=UTC),
    )

    result = backfill_nightly_emails((chatter,))

    assert result.entries == ()
    assert result.review == ()
    assert result.skipped_message_ids == ("chatter",)


def test_explicit_service_date_override_is_audited():
    report = message(
        "after-midnight",
        "EOD 07.26.26",
        "SPLH: $ 100\nLabor: $ 4000\nHours: $ 300\nTotal: 500\n",
        datetime(2026, 7, 26, 0, 30, tzinfo=UTC),
    )

    result = backfill_nightly_emails(
        (report,),
        service_date_overrides={"after-midnight": date(2026, 7, 25)},
    )

    entry = result.entries[0]
    assert entry.report.service_date == date(2026, 7, 25)
    assert "service_date_overridden" in entry.warnings


def test_override_separates_two_reports_with_same_subject_date():
    prior_night = message(
        "prior",
        "Fonda SM EOD Report, 7/15/2026",
        "SPLH: $ 76.90\nDining Room: 286\nTotal: 168\nBar / Atrium: 454\n",
        datetime(2026, 7, 15, 0, 35, tzinfo=UTC),
    )
    current_night = message(
        "current",
        "EOD 07.15.26",
        "SPLH: $ 80\nDining Room: 222\nBar / Atrium: 119\nTotal: 341\n",
        datetime(2026, 7, 15, 23, 0, tzinfo=UTC),
    )

    result = backfill_nightly_emails(
        (prior_night, current_night),
        service_date_overrides={"prior": date(2026, 7, 14)},
    )

    assert [entry.report.service_date for entry in result.entries] == [
        date(2026, 7, 14),
        date(2026, 7, 15),
    ]
    expected_reasons = (
        "missing_labor_cost_actual",
        "missing_labor_hours_actual",
        "missing_reservation_covers",
    )
    assert [(review.service_date, review.reasons) for review in result.review] == [
        (date(2026, 7, 14), expected_reasons),
        (date(2026, 7, 15), expected_reasons),
    ]


def test_deterministic_bar_atrium_total_transposition_is_repaired():
    report = message(
        "swapped",
        "EOD 07.14.26",
        """
        SPLH: $ 76.90
        Reservations: 261
        Dining Room: 286
        Total: 168
        Bar / Atrium: 454
        """,
        datetime(2026, 7, 15, 0, 35, tzinfo=UTC),
    )

    result = backfill_nightly_emails((report,))
    entry = result.entries[0]

    assert entry.report.dining_room_covers == 286
    assert entry.report.bar_atrium_covers == 168
    assert entry.report.total_covers == 454
    assert "bar_atrium_total_probably_swapped" in entry.warnings


def test_dated_report_without_figures_is_reviewed_not_lost():
    photo_only = message(
        "photo-only",
        "EOD 11.05.26",
        "Good evening everyone! It was busy!! We had a backroom buyout.\n"
        "Cocktail received an influx of people, with 30 guests arriving late.",
        datetime(2026, 11, 6, 5, 32, tzinfo=UTC),
    )

    result = backfill_nightly_emails((photo_only,))

    assert result.entries == ()
    assert result.skipped_message_ids == ("photo-only",)
    assert len(result.review) == 1
    assert result.review[0].service_date == date(2026, 11, 5)
    assert result.review[0].reasons == ("primary_without_operational_data",)
    assert result.review[0].source_message_ids == ("photo-only",)


def test_figureless_report_is_not_reviewed_when_another_covers_the_night():
    photo_only = message(
        "photo-only",
        "EOD 11.05.26",
        "See the attached photo for tonight.",
        datetime(2026, 11, 6, 5, 32, tzinfo=UTC),
    )
    resend = message(
        "resend",
        "EOD 11.05.26",
        "SPLH: $ 100\nLabor: $ 4000\nHours: $ 300\nReservations: 200\nTotal: 500\n",
        datetime(2026, 11, 6, 6, 10, tzinfo=UTC),
    )

    result = backfill_nightly_emails((photo_only, resend))

    assert [entry.report.service_date for entry in result.entries] == [
        date(2026, 11, 5)
    ]
    assert result.review == ()


def test_dash_style_report_passes_the_operational_gate_without_narrative():
    dash_only = message(
        "dash-only",
        "EOD 10.29.26",
        "SPLH -$71.25\nLABOR- $3650.40\nHOURS- 251.75\nRES- 240\nTOTAL- 410\n",
        datetime(2026, 10, 30, 4, 49, tzinfo=UTC),
    )

    result = backfill_nightly_emails((dash_only,))

    assert result.skipped_message_ids == ()
    assert result.review == ()
    assert result.entries[0].report.labor_cost_actual == 3650.40
    assert result.entries[0].report.total_covers == 410
