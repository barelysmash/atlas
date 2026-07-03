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