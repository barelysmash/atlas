from datetime import UTC, datetime

import pytest
from atlas_core import (
    Decision,
    EvidenceItem,
    Insight,
    Metric,
    Observation,
    Recommendation,
)

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
CREATED_AT = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)


def _observation() -> Observation:
    return Observation(
        domain="operations",
        subject="Fonda San Miguel",
        summary="Wine receipts were $50,000.",
        metrics=(Metric(name="wine_receipts", value=50000.0),),
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
    )


def _decision(insight: Insight, **overrides) -> Decision:
    kwargs = {
        "domain": "operations",
        "category": "atlas.marketing",
        "priority": "low",
        "confidence": 0.75,
        "summary": "Continue monitoring wine performance.",
        "evidence": insight.evidence,
        "derived_from": (insight.insight_id,),
        "recommendations": (
            Recommendation(statement="Review wine receipts again next month."),
        ),
        "created_at": CREATED_AT,
    }
    kwargs.update(overrides)
    return Decision(**kwargs)


def test_create_decision_from_insights():
    decision = _decision(_insight(_observation()))
    assert decision.summary == "Continue monitoring wine performance."
    assert decision.confidence == 0.75
    assert decision.category == "atlas.marketing"
    assert decision.priority == "low"


def test_decision_is_identified_on_construction():
    assert _decision(_insight(_observation())).decision_id.startswith("dec_")


def test_decision_cites_its_observation():
    observation = _observation()
    decision = _decision(_insight(observation))
    assert decision.cites(observation.observation_id)


def test_decision_rests_on_its_insight():
    insight = _insight(_observation())
    assert _decision(insight).rests_on(insight.insight_id)


def test_evidence_and_derived_from_answer_different_questions():
    observation = _observation()
    insight = _insight(observation)
    decision = _decision(insight)
    assert decision.evidence[0].observation_id == observation.observation_id
    assert decision.derived_from == (insight.insight_id,)


def test_approval_is_required_by_default():
    assert _decision(_insight(_observation())).requires_approval is True


def test_skipping_approval_needs_every_recommendation_reversible():
    insight = _insight(_observation())
    with pytest.raises(ValueError, match="not reversible"):
        _decision(insight, requires_approval=False)


def test_approval_may_be_skipped_when_all_are_reversible():
    insight = _insight(_observation())
    decision = _decision(
        insight,
        requires_approval=False,
        recommendations=(
            Recommendation(statement="Adjust the par level.", reversible=True),
        ),
    )
    assert decision.requires_approval is False


def test_a_decision_with_no_evidence_is_refused():
    insight = _insight(_observation())
    with pytest.raises(ValueError, match="opinion"):
        _decision(insight, evidence=())


def test_a_decision_with_no_recommendation_is_refused():
    insight = _insight(_observation())
    with pytest.raises(ValueError, match="at least one action"):
        _decision(insight, recommendations=())
