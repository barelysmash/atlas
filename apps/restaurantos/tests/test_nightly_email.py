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
