import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RestaurantRecord:
    restaurant: str
    period: str
    revenue: float


def import_restaurant_csv(path: str | Path) -> list[RestaurantRecord]:
    records: list[RestaurantRecord] = []

    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:
            records.append(
                RestaurantRecord(
                    restaurant=row["restaurant"],
                    period=row["period"],
                    revenue=float(row["revenue"]),
                )
            )

    return records