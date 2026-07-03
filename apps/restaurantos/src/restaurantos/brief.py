from restaurantos.tabc_importer import TABCRecord


def generate_tabc_brief(records: list[TABCRecord], restaurant: str) -> str:
    if not records:
        raise ValueError("records are required")

    matching_records = [
        record for record in records
        if restaurant.lower() in record.location_name.lower()
        or restaurant.lower() in record.taxpayer_name.lower()
    ]

    if not matching_records:
        raise ValueError(f"no records found for restaurant: {restaurant}")

    latest = matching_records[-1]

    return (
        f"# {restaurant} TABC Brief\n\n"
        f"## Latest Period\n"
        f"{latest.report_month}\n\n"
        f"## Receipts\n"
        f"- Liquor: ${latest.liquor_receipts:,.0f}\n"
        f"- Wine: ${latest.wine_receipts:,.0f}\n"
        f"- Beer: ${latest.beer_receipts:,.0f}\n"
        f"- Total: ${latest.total_receipts:,.0f}\n"
    )