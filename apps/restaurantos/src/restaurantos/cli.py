from pathlib import Path

from restaurantos.brief import generate_tabc_brief
from restaurantos.tabc_importer import import_tabc_csv


def morning_brief(csv_path: str | Path, restaurant: str) -> str:
    records = import_tabc_csv(csv_path)
    return generate_tabc_brief(records, restaurant)