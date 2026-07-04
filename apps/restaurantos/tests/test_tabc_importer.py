from pathlib import Path

from restaurantos.tabc_importer import import_tabc_csv


def test_import_tabc_csv(tmp_path: Path):
    csv_path = tmp_path / "tabc.csv"

    csv_path.write_text(
        (
            "Taxpayer Name,"
            "TABC Permit Number,"
            "Location Name,"
            "City,"
            "Obligation End Date,"
            "Liquor Receipts,"
            "Wine Receipts,"
            "Beer Receipts,"
            "Total Receipts\n"
            "Fonda San Miguel,"
            "MB091654,"
            "Fonda San Miguel,"
            "Austin,"
            "2026-06,"
            "100000,"
            "50000,"
            "25000,"
            "175000\n"
        ),
        encoding="utf-8",
    )

    records = import_tabc_csv(csv_path)

    assert len(records) == 1

    record = records[0]

    assert record.taxpayer_name == "Fonda San Miguel"
    assert record.permit_number == "MB091654"
    assert record.location_name == "Fonda San Miguel"
    assert record.city == "Austin"
    assert record.report_month == "2026-06"

    assert record.liquor_receipts == 100000.0
    assert record.wine_receipts == 50000.0
    assert record.beer_receipts == 25000.0
    assert record.total_receipts == 175000.0

from restaurantos.tabc_importer import TABCRecord, normalize_tabc_records

def test_normalize_tabc_records():
    records = [
        TABCRecord(
            taxpayer_name="Fonda San Miguel",
            permit_number="MB091654",
            location_name="Fonda San Miguel",
            city="Austin",
            report_month="2026-06",
            liquor_receipts=100000,
            wine_receipts=50000,
            beer_receipts=25000,
            total_receipts=175000,
        )
    ]

    normalized = normalize_tabc_records(records)

    assert len(normalized) == 4
    assert normalized[0].source == "tabc"
    assert normalized[0].entity == "Fonda San Miguel"
    assert normalized[0].period == "2026-06"
    assert normalized[0].dimensions["permit_number"] == "MB091654"

    metrics = [record.metric for record in normalized]

    assert metrics == [
        "liquor_receipts",
        "wine_receipts",
        "beer_receipts",
        "total_receipts",
    ]