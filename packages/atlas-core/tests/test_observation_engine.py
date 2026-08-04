from atlas_core import OperationalRecord
from atlas_core.observation_engine import generate_observations


def _record() -> OperationalRecord:
    return OperationalRecord.create(
        source="tabc",
        entity="Fonda San Miguel",
        period="2026-06",
        category="sales",
        metric="wine_receipts",
        value=50000.0,
        dimensions={"permit_number": "MB091654"},
    )


def test_generate_observations():
    observations = generate_observations(_record())
    assert len(observations) == 1
    assert observations[0].summary == "wine_receipts was 50,000."


def test_category_becomes_domain():
    assert generate_observations(_record())[0].domain == "sales"


def test_entity_becomes_subject():
    assert generate_observations(_record())[0].subject == "Fonda San Miguel"


def test_metric_and_value_become_a_metrics_entry():
    metrics = generate_observations(_record())[0].metrics
    assert len(metrics) == 1
    assert metrics[0].name == "wine_receipts"
    assert metrics[0].value == 50000.0


def test_provenance_becomes_source_ref():
    observation = generate_observations(_record())[0]
    assert observation.source_ref == "tabc:Fonda San Miguel:2026-06"


def test_record_timestamp_becomes_observed_at():
    record = _record()
    assert generate_observations(record)[0].observed_at == record.timestamp


def test_dimensions_do_not_cross_the_boundary():
    observation = generate_observations(_record())[0]
    assert "MB091654" not in str(observation)
