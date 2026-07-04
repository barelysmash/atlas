from restaurantos.comparisons import month_over_month, total_receipts
from restaurantos.tabc_importer import TABCRecord


def test_total_receipts():
    records = [
        TABCRecord(
            taxpayer_name="Fonda San Miguel",
            permit_number="MB091654",
            location_name="Fonda San Miguel",
            city="Austin",
            report_month="2026-05",
            liquor_receipts=100,
            wine_receipts=50,
            beer_receipts=25,
            total_receipts=175,
        ),
        TABCRecord(
            taxpayer_name="Fonda San Miguel",
            permit_number="MB091654",
            location_name="Fonda San Miguel",
            city="Austin",
            report_month="2026-06",
            liquor_receipts=200,
            wine_receipts=100,
            beer_receipts=50,
            total_receipts=350,
        ),
    ]

    assert total_receipts(records) == 525


def test_month_over_month():
    assert month_over_month(current=350, previous=175) == 100.0


def test_month_over_month_zero_previous():
    assert month_over_month(current=350, previous=0) == 0.0