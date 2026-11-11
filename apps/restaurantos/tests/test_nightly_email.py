from datetime import date

from restaurantos.nightly_email import parse_nightly_email

AUG_10 = """
Net Sales: $ 19,335.56 SPLH: $
77.38 Labor: $ 3,698.87 Hours: $
249.89 Anniversary: $ 82.00 Birthday: $
196.00 Manager: $ 86.90 Voids: $
- Reservations: 205 Dining Room: 227 Bar / Atrium:
133 Total 360
"""

AUG_11 = """
Sales and Labor
SPLH: $75.47
Labor (projected): $5,249.67
Labor (actual): $4930.98
Horas (projected): 350.75
Horas (actual): 329.91

Covers
Starting Reservations: 230
Dining Room: 298
Bar/Atrium: 165
Total: 463

Feature Sales
Camarones: $720.57 (19)
Tlocoyo: $120 (11)
Tart: $96 (6)

Comps and Voids
Total Comps: $968.13
Birthday: $380
Anniversary/Congrats: $94 (7)
Employee: $19.48 (1)
Manager Meal: $98.85 (3)
Tom Tab: $250.40 (1)
Training Meal: $111.40 (Taylor)
Total Voids: $109.95 (6)
"""

AUG_03 = """
Tonight we began service with 203 on the books and ended the evening with
235 seated including 2 set menu groups.

SPLH: $77.27
Labor (actual): $3840.93
Labor (scheduled): $4629.40
Horas (actual): 253.48
Horas (scheduled): $295.25

Total Comps: $399.50
Birthday: $200 (15)
Anniversary: $76 (5)
Manager Meal: $15.95 (1)
Employee: $13.75 (1)
DNL: $93.80 (4)
Total Voids: $165.40

Starting Reservations: 203
Dining Room EOD Covers: 235
Atrium/Bar: 106

Features Sold:
Pork Belly Tlacoyo: $96 (8)
Camarones Ajillo: $311.60 (8)
Tart: $144 (10)
Ensalada: $185 (10)
"""


def test_compact_outlook_format_parses_and_dash_is_zero():
    report = parse_nightly_email(AUG_10, service_date=date(2026, 8, 10))

    assert report.net_sales == 19335.56
    assert report.reported_splh == 77.38
    assert report.labor_cost_actual == 3698.87
    assert report.labor_hours_actual == 249.89
    assert report.reservation_covers == 205
    assert report.dining_room_covers == 227
    assert report.bar_atrium_covers == 133
    assert report.total_covers == 360
    assert report.voids == 0.0


def test_projected_actual_labor_dynamic_comps_and_features_parse():
    report = parse_nightly_email(AUG_11, service_date=date(2026, 8, 11))

    assert report.labor_cost_actual == 4930.98
    assert report.labor_cost_scheduled == 5249.67
    assert report.labor_hours_actual == 329.91
    assert report.labor_hours_scheduled == 350.75
    assert report.reported_total_comps == 968.13
    assert {line.category for line in report.comps} >= {
        "Birthday",
        "Anniversary/Congrats",
        "Employee",
        "Manager Meal",
        "Tom Tab",
        "Training Meal",
    }
    parsed_features = [
        (sale.item, sale.sales, sale.quantity) for sale in report.feature_sales
    ]
    assert parsed_features == [
        ("Camarones", 720.57, 19),
        ("Tlocoyo", 120.0, 11),
        ("Tart", 96.0, 6),
    ]


def test_missing_total_uses_rooms_and_preserves_narrative_ambiguity():
    report = parse_nightly_email(AUG_03, service_date=date(2026, 8, 3))

    assert report.total_covers is None
    assert report.dining_room_covers == 235
    assert report.bar_atrium_covers == 106
    assert report.effective_total_covers == 341
    assert report.narrative_total_covers == 235
    assert "narrative_total_mismatch" in report.quality_flags
    assert len(report.feature_sales) == 4


def test_cover_counts_parse_when_source_formats_them_as_currency():
    report = parse_nightly_email(
        """
        Reservations: $ 240.00
        Dining Room: $ 263.00
        Bar / Atrium: $
        126.00 Total: $ 389.00
        """,
        service_date=date(2026, 7, 1),
    )

    assert report.reservation_covers == 240
    assert report.dining_room_covers == 263
    assert report.bar_atrium_covers == 126
    assert report.total_covers == 389


# Shapes taken from three November 2026 reports Atlas could not fully read.
# The figures are invented; only the layout is real.

DASH_STYLE = """
Good evening, everyone!!!

Tonight at Fonda San Miguel we started with 240 covers and finished seating
410 guests.
In the dining room we hosted 3 set menus: 12 for a business dinner, 14 for a
wedding dinner, and a 10-top birthday dinner. Our team helped celebrate
4 anniversaries and 11 birthdays tonight, reaching a full house by 7 pm.

Ensalada de Sandía — 14
Tetela — 6

SPLH -$71.25
LABOR- $3650.40
HOURS- 251.75
ANNI- $120
BDAY- $240
MANAGER- $0
VOIDS-$45
RES- 240
DIN ROOM- 285
BAR- 125
TOTAL- 410
"""

HOUSE_TOTAL = """
We started with 210 reservations on the books including 3 set menus.

Net Sales: $21,450.75
SPLH: $101.20
Labor (scheduled): $3900.00
Labor (actual): $3725.50
Hours (scheduled): 220.00
Hours (actual): 211.96
Total Comps: $512.40
Birthday: $180 (12)
Anniversary: $60 (4)
Manager Meal: $112.40 (3)
Voids: $131.25
Reservations: 210
Total in Dining: 268
Total in Atrium/Bar: 139
Total in House: 407
Poussin: $640 (16)
Set menu sales: $2,310 (33)
"""


def test_dash_separated_figures_block_is_read():
    report = parse_nightly_email(DASH_STYLE, service_date=date(2026, 10, 29))

    assert report.reported_splh == 71.25
    assert report.labor_cost_actual == 3650.40
    assert report.labor_hours_actual == 251.75
    assert report.voids == 45.0
    assert report.reservation_covers == 240
    assert report.dining_room_covers == 285
    assert report.bar_atrium_covers == 125
    assert report.total_covers == 410
    assert report.effective_total_covers == 410
    assert {(line.category, line.amount) for line in report.comps} == {
        ("ANNI", 120.0),
        ("BDAY", 240.0),
        ("MANAGER", 0.0),
    }


def test_dash_rules_do_not_read_menu_counts_or_narrative():
    report = parse_nightly_email(DASH_STYLE, service_date=date(2026, 10, 29))

    # "Ensalada de Sandía — 14" is a sold count, not a comp or a cover figure.
    assert all("Ensalada" not in line.category for line in report.comps)
    assert all("Tetela" not in line.category for line in report.comps)


def test_house_total_template_is_read():
    report = parse_nightly_email(HOUSE_TOTAL, service_date=date(2026, 11, 6))

    assert report.net_sales == 21450.75
    assert report.labor_cost_actual == 3725.50
    assert report.labor_hours_actual == 211.96
    assert report.reservation_covers == 210
    assert report.dining_room_covers == 268
    assert report.bar_atrium_covers == 139
    assert report.total_covers == 407
    assert report.effective_total_covers == 407


def test_colon_style_reports_are_unchanged_by_the_dash_rules():
    # A hyphenated narrative line must not override or add to colon figures.
    body = AUG_11 + "\nLABOR- $9.99\nTOTAL- 1\nBDAY- $5\n"
    baseline = parse_nightly_email(AUG_11, service_date=date(2026, 8, 11))
    report = parse_nightly_email(body, service_date=date(2026, 8, 11))

    assert report == baseline
