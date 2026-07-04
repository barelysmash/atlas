from atlas_core import OperationalRecord


def test_create_operational_record():
    record = OperationalRecord.create(
        source="tabc",
        entity="Fonda San Miguel",
        period="2026-06",
        category="wine",
        metric="receipts",
        value=50000,
        dimensions={"city": "Austin"},
    )

    assert record.source == "tabc"
    assert record.entity == "Fonda San Miguel"
    assert record.period == "2026-06"
    assert record.category == "wine"
    assert record.metric == "receipts"
    assert record.value == 50000.0
    assert record.dimensions["city"] == "Austin"


def test_operational_record_requires_source():
    try:
        OperationalRecord.create(
            source="",
            entity="Fonda San Miguel",
            period="2026-06",
            category="wine",
            metric="receipts",
            value=50000,
        )
    except ValueError as error:
        assert "source is required" in str(error)
    else:
        raise AssertionError("Expected ValueError")