from datetime import datetime, timedelta, timezone

import pytest
from atlas_core import (
    Decision,
    EvidenceItem,
    Insight,
    Metric,
    Observation,
    Recommendation,
)
from atlas_core.documents import (
    SCHEMA_VERSIONS,
    SOURCE,
    decision_document,
    insight_document,
    observation_document,
)

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
BUILD = "0.4.1"


def _observation() -> Observation:
    return Observation(
        domain="beverage",
        subject="Casa Madero",
        summary="Casa Madero moved 214 bottles.",
        metrics=(Metric(name="units_sold", value=214, unit="bottles", period="P4W"),),
        source_ref="restaurantos://reports/beverage/weekly/2026-W30",
        observed_at=OBSERVED_AT,
    )


def _insight(observation: Observation) -> Insight:
    return Insight(
        domain="beverage",
        statement="Premium sampling is lifting wine attachment.",
        confidence=0.74,
        evidence=(EvidenceItem.citing(observation, "units_sold"),),
        created_at=CREATED_AT,
        method="cohort_contrast",
    )


def _decision(insight: Insight) -> Decision:
    return Decision(
        domain="beverage",
        category="atlas.marketing",
        priority="low",
        confidence=0.74,
        summary="Continue promoting premium wine.",
        rationale="Sampling is working and continuing costs little.",
        evidence=insight.evidence,
        derived_from=(insight.insight_id,),
        recommendations=(
            Recommendation(
                statement="Continue premium wine sampling.",
                action_type="launch_promotion",
            ),
        ),
        created_at=CREATED_AT,
    )


def test_observation_document_declares_source_and_version():
    doc = observation_document(_observation(), source_version=BUILD)
    assert doc["source"] == SOURCE
    assert doc["source_version"] == BUILD
    assert doc["schema_version"] == SCHEMA_VERSIONS["observation"]


def test_observation_document_carries_every_metric():
    doc = observation_document(_observation(), source_version=BUILD)
    assert doc["metrics"] == [
        {"name": "units_sold", "value": 214, "unit": "bottles", "period": "P4W"}
    ]


def test_absent_optional_fields_are_omitted_not_nulled():
    bare = Observation(
        domain="beverage",
        summary="Something was measured.",
        metrics=(Metric(name="units_sold", value=1),),
        observed_at=OBSERVED_AT,
    )
    doc = observation_document(bare, source_version=BUILD)
    assert "subject" not in doc
    assert "source_ref" not in doc
    assert None not in doc.values()


def test_insight_document_carries_its_citations():
    observation = _observation()
    doc = insight_document(_insight(observation), source_version=BUILD)
    assert doc["evidence"][0]["observation_id"] == observation.observation_id
    assert doc["evidence"][0]["metric"]["name"] == "units_sold"


def test_decision_document_carries_structured_recommendations():
    doc = decision_document(_decision(_insight(_observation())), source_version=BUILD)
    rec = doc["recommendations"][0]
    assert rec["recommendation_id"].startswith("rec_")
    assert rec["action_type"] == "launch_promotion"
    assert rec["reversible"] is False


def test_decision_document_records_the_insight_it_rests_on():
    insight = _insight(_observation())
    doc = decision_document(_decision(insight), source_version=BUILD)
    assert doc["derived_from"] == [insight.insight_id]


def test_empty_derived_from_is_omitted():
    insight = _insight(_observation())
    decision = Decision(
        domain="beverage",
        category="atlas.marketing",
        priority="low",
        confidence=0.74,
        summary="Continue promoting premium wine.",
        evidence=insight.evidence,
        recommendations=(Recommendation(statement="Do the thing."),),
        created_at=CREATED_AT,
    )
    assert "derived_from" not in decision_document(decision, source_version=BUILD)


def test_timestamps_are_rfc3339_utc_with_a_z_suffix():
    doc = observation_document(_observation(), source_version=BUILD)
    assert doc["observed_at"] == "2026-07-01T12:00:00Z"


def test_a_non_utc_timestamp_is_converted_not_rejected():
    shifted = Observation(
        domain="beverage",
        summary="Something was measured.",
        metrics=(Metric(name="units_sold", value=1),),
        observed_at=datetime(2026, 7, 1, 7, 0, tzinfo=timezone(timedelta(hours=-5))),
    )
    doc = observation_document(shifted, source_version=BUILD)
    assert doc["observed_at"] == "2026-07-01T12:00:00Z"


def test_a_naive_timestamp_is_refused():
    naive = Observation(
        domain="beverage",
        summary="Something was measured.",
        metrics=(Metric(name="units_sold", value=1),),
        observed_at=datetime(2026, 7, 1, 12, 0),  # noqa: DTZ001 - the point
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        observation_document(naive, source_version=BUILD)


@pytest.mark.parametrize("bad", ["0.2.0-alpha.1", "0.2.0a1", "1.2", "v1.2.3", ""])
def test_a_source_version_that_is_not_bare_semver_is_refused(bad):
    with pytest.raises(ValueError, match="bare semver"):
        observation_document(_observation(), source_version=bad)


def test_every_document_kind_has_a_declared_schema_version():
    assert set(SCHEMA_VERSIONS) == {"observation", "insight", "decision"}
