from datetime import datetime, timezone

from atlas_core import EvidenceItem, Insight, Metric, Observation

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)


def _observation() -> Observation:
    return Observation(
        domain="operations",
        subject="Fonda San Miguel",
        summary="Wine receipts were $50,000.",
        metrics=(Metric(name="wine_receipts", value=50000.0, unit="usd"),),
        source_ref="TABC June 2026",
        observed_at=OBSERVED_AT,
    )


def _insight(observation: Observation) -> Insight:
    return Insight(
        domain="operations",
        statement="Wine performance is meaningful enough to monitor.",
        confidence=0.8,
        evidence=(EvidenceItem.citing(observation, "wine_receipts"),),
        created_at=CREATED_AT,
        method="threshold_breach",
    )


def test_create_insight_from_observations():
    insight = _insight(_observation())
    assert insight.statement == "Wine performance is meaningful enough to monitor."
    assert insight.confidence == 0.8
    assert insight.method == "threshold_breach"
    assert insight.created_at == CREATED_AT


def test_insight_is_identified_on_construction():
    assert _insight(_observation()).insight_id.startswith("ins_")


def test_identity_is_excluded_from_equality():
    observation = _observation()
    assert _insight(observation) == _insight(observation)


def test_insight_cites_its_observation():
    observation = _observation()
    insight = _insight(observation)
    assert insight.cites(observation.observation_id)
    assert not insight.cites("obs_01JQZX3T8KMNPQRSTVWXYZ0123")


def test_evidence_names_the_metric_reasoned_from():
    insight = _insight(_observation())
    assert insight.evidence[0].metric is not None
    assert insight.evidence[0].metric.name == "wine_receipts"


def test_confidence_has_no_emission_floor():
    insight = Insight(
        domain="operations",
        statement="A tentative reading worth recording.",
        confidence=0.05,
        evidence=(EvidenceItem.citing(_observation(), "wine_receipts"),),
        created_at=CREATED_AT,
    )
    assert insight.confidence == 0.05
