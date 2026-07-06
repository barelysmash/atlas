from atlas_core import OperationalRecord
from atlas_core.observation_engine import generate_observations


def test_generate_observations():
    record = OperationalRecord.create(
        source="tabc",
        entity="Fonda San Miguel",
        period="2026-06",
        category="sales",
        metric="wine_receipts",
        value=50000.0,
        dimensions={"permit_number": "MB091654"},
    )

    observations = generate_observations(record)

    assert len(observations) == 1
    assert observations[0].category == "sales"
    assert observations[0].metric == "wine_receipts"
    assert observations[0].value == 50000.0
    assert observations[0].summary == "wine_receipts was 50,000."
    assert observations[0].evidence == ["tabc:Fonda San Miguel:2026-06"]