from atlas_core import OperationalRecord, ReasoningResult
from atlas_core.reasoning_pipeline import ReasoningPipeline


def test_reasoning_pipeline_returns_reasoning_result():
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
    result = pipeline.run(record)

    assert isinstance(result, ReasoningResult)
    assert len(result.observations) == 1
    assert len(result.insights) == 1
    assert len(result.decisions) == 1
    assert result.decisions[0].summary == "Continue promoting premium wine."