import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TABCRecord:
    taxpayer_name: str
    permit_number: str
    location_name: str
    city: str
    report_month: str
    liquor_receipts: float
    wine_receipts: float
    beer_receipts: float
    total_receipts: float


def _money(value: str) -> float:
    if value is None or value == "":
        return 0.0

    cleaned = value.replace("$", "").replace(",", "").strip()
    return float(cleaned or 0)


def import_tabc_csv(path: str | Path) -> list[TABCRecord]:
    records: list[TABCRecord] = []

    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:
            records.append(
                TABCRecord(
                    taxpayer_name=row.get("Taxpayer Name", ""),
                    permit_number=row.get("TABC Permit Number", ""),
                    location_name=row.get("Location Name", ""),
                    city=row.get("City", ""),
                    report_month=row.get("Obligation End Date", ""),
                    liquor_receipts=_money(row.get("Liquor Receipts", "")),
                    wine_receipts=_money(row.get("Wine Receipts", "")),
                    beer_receipts=_money(row.get("Beer Receipts", "")),
                    total_receipts=_money(row.get("Total Receipts", "")),
                )
            )

    return records