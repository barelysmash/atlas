from restaurantos.brief import generate_tabc_brief
from restaurantos.tabc_importer import TABCRecord


def test_generate_tabc_brief():
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

    brief = generate_tabc_brief(records, "Fonda San Miguel")

    assert "# Fonda San Miguel TABC Brief" in brief
    assert "2026-06" in brief
    assert "Total: $175,000" in brief