from datetime import UTC, date, datetime

from restaurantos.nightly_backfill import NightlyEmailMessage, backfill_nightly_emails
from restaurantos.nightly_email import parse_nightly_email


def message(message_id: str, subject: str, body: str) -> NightlyEmailMessage:
    return NightlyEmailMessage(
        message_id=message_id,
        subject=subject,
        body=body,
        sent_at=datetime(2026, 7, 22, 23, 45, tzinfo=UTC),
    )


def test_narrative_cover_block_parses_all_cover_fields():
    report = parse_nightly_email(
        """
        Numbers started low—213 on the books with no party size above 7.
        We built up to 247 in main dining and 157 in the bar and atrium
        for a total of 404 guests served.

        SPLH: $82.28
        Labor (Scheduled): $4701.12
        Labor (Actual): $4025.40
        Horas (Scheduled): 300.25
        Horas (Actual): 270.16
        """,
        service_date=date(2026, 7, 22),
    )

    assert report.reservation_covers == 213
    assert report.dining_room_covers == 247
    assert report.bar_atrium_covers == 157
    assert report.total_covers == 404


def test_narrative_seated_language_parses_and_sums_rooms():
    report = parse_nightly_email(
        """
        We started with 283 on the books.
        We finished the night seating 301 in dining including a set menu
        and 206 in the bar and atrium.
        SPLH: $101.45
        """,
        service_date=date(2026, 7, 18),
    )

    assert report.reservation_covers == 283
    assert report.dining_room_covers == 301
    assert report.bar_atrium_covers == 206
    assert report.total_covers == 507


def test_duplicate_labor_actual_label_can_recover_actual_hours():
    report = parse_nightly_email(
        """
        SPLH: $101.45
        Labor (Scheduled): $5298.25
        Labor (Actual): $4356.06
        Horas (Scheduled): 355.50
        Labor (Actual): 299.55
        Reservations: 283
        Total: 507
        """,
        service_date=date(2026, 7, 18),
    )

    assert report.labor_cost_actual == 4356.06
    assert report.labor_hours_actual == 299.55


def test_narrative_only_report_is_retained_and_flagged_incomplete():
    result = backfill_nightly_emails(
        (
            message(
                "narrative-only",
                "Fonda SM EOD Report, 6/6/2026",
                """
                We started the night with 273 reserved covers, built up to
                309 covers in the Dining Room, and finished with 577 covers all day.
                """,
            ),
        )
    )

    assert len(result.entries) == 1
    entry = result.entries[0]
    assert entry.report.reservation_covers == 273
    assert entry.report.dining_room_covers == 309
    assert entry.report.total_covers == 577
    assert "missing_sales_or_splh" in entry.warnings
    assert "missing_labor_cost_actual" in entry.warnings
    assert "missing_labor_hours_actual" in entry.warnings
    assert result.review[0].reasons == (
        "missing_sales_or_splh",
        "missing_labor_cost_actual",
        "missing_labor_hours_actual",
    )


def test_splh_only_report_surfaces_missing_labor_and_cover_fields():
    result = backfill_nightly_emails(
        (
            message(
                "splh-only",
                "EOD 7/11",
                """
                SPLH: $91.50
                Total Comps: $902.50
                Total Voids: $141.65
                """,
            ),
        )
    )

    assert len(result.entries) == 1
    assert result.review[0].reasons == (
        "missing_labor_cost_actual",
        "missing_labor_hours_actual",
        "missing_reservation_covers",
        "missing_total_covers",
    )


def test_net_sales_narrative_cover_report_only_flags_missing_labor():
    result = backfill_nightly_emails(
        (
            message(
                "sales-no-labor",
                "Fonda SM EOD Report, 7/30/2026",
                """
                We started service with 261 reserved covers.
                We finished with 270 covers in the main dining room
                and 421 covers for the day.
                Net Sales: $24,416.22
                SPLH: $80.70
                """,
            ),
        )
    )

    entry = result.entries[0]
    assert entry.report.reservation_covers == 261
    assert entry.report.dining_room_covers == 270
    assert entry.report.total_covers == 421
    assert result.review[0].reasons == (
        "missing_labor_cost_actual",
        "missing_labor_hours_actual",
    )
