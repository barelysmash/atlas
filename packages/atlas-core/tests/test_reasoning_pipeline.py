from atlas_core import OperationalRecord
from atlas_core.reasoning_pipeline import ReasoningPipeline


def test_reasoning_pipeline_returns_decisions():
    record = OperationalRecord.create(
        source="tabc",
        entity="Fonda San Miguel",
        period="2026-06",
        category="sales",
        metric="wine_receipts",
        value=50000.0,
        dimensions={"permit_number": "MB091654"},
    )

    pipeline = ReasoningPipeline()
    decisions = pipeline.run(record)

    assert len(decisions) == 1
    assert decisions[0].summary == "Continue promoting premium wine."
    assert decisions[0].recommendations == [
        "Continue premium wine sampling."
    ]