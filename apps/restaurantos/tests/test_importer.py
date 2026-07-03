from pathlib import Path

from restaurantos import import_restaurant_csv


def test_import_restaurant_csv(tmp_path: Path):
    csv_path = tmp_path / "restaurant.csv"

    csv_path.write_text(
        "restaurant,period,revenue\n"
        "Fonda San Miguel,2026-03,236568\n",
        encoding="utf-8",
    )

    records = import_restaurant_csv(csv_path)

    assert len(records) == 1
    assert records[0].restaurant == "Fonda San Miguel"
    assert records[0].period == "2026-03"
    assert records[0].revenue == 236568.0