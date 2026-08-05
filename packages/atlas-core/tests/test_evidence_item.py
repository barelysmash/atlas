from datetime import datetime, timezone

import pytest
from atlas_core import EvidenceItem, Metric, Observation

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _observation() -> Observation:
    return Observation(
        domain="beverage",
        subject="Casa Madero",
        summary="Casa Madero moved 214 bottles at a 21% attachment rate.",
        metrics=(
            Metric(name="units_sold", value=214, unit="bottles", period="P4W"),
            Metric(name="wine_attachment", value=0.21, unit="ratio", period="P4W"),
        ),
        source_ref="restaurantos://reports/beverage/weekly/2026-W30",
        observed_at=OBSERVED_AT,
    )


def test_citing_copies_the_named_metric():
    item = EvidenceItem.citing(_observation(), "units_sold")
    assert item.metric is not None
    assert item.metric.name == "units_sold"
    assert item.metric.value == 214


def test_citing_selects_among_several_metrics():
    item = EvidenceItem.citing(_observation(), "wine_attachment")
    assert item.metric is not None
    assert item.metric.value == 0.21


def test_citing_carries_the_observation_identity():
    observation = _observation()
    item = EvidenceItem.citing(observation, "units_sold")
    assert item.observation_id == observation.observation_id
    assert item.observation_id.startswith("obs_")


def test_citing_defaults_the_statement_to_the_summary():
    observation = _observation()
    assert (
        EvidenceItem.citing(observation, "units_sold").statement == observation.summary
    )


def test_citing_accepts_a_narrower_statement():
    item = EvidenceItem.citing(
        _observation(), "units_sold", "Casa Madero units sold rose over four weeks."
    )
    assert item.statement == "Casa Madero units sold rose over four weeks."


def test_citing_carries_provenance():
    item = EvidenceItem.citing(_observation(), "units_sold")
    assert item.source_ref == "restaurantos://reports/beverage/weekly/2026-W30"


def test_citing_an_absent_metric_is_refused():
    with pytest.raises(ValueError, match="no metric named"):
        EvidenceItem.citing(_observation(), "beer_receipts")


def test_the_copied_metric_matches_its_source():
    observation = _observation()
    item = EvidenceItem.citing(observation, "units_sold")
    assert item.metric == observation.get_metric("units_sold")
