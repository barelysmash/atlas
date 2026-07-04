from pathlib import Path

from restaurantos.cli import morning_brief


def test_morning_brief(tmp_path: Path):
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

    brief = morning_brief(csv_path, "Fonda San Miguel")

    assert "# Fonda San Miguel TABC Brief" in brief
    assert "2026-06" in brief
    assert "$175,000" in brief