import pytest
from atlas_memory import DecisionRecord

CONTRACT_ID = "dec_01JQZX3T8KMNPQRSTVWXYZ0123"


def test_a_record_captures_the_choice_and_the_reason():
    record = DecisionRecord.create(
        "Adopt wine sampling",
        "Wine attachment increased during the test.",
    )
    assert record.summary == "Adopt wine sampling"
    assert record.rationale == "Wine attachment increased during the test."


def test_a_record_without_a_link_followed_no_recommendation():
    record = DecisionRecord.create("Adopt wine sampling", "It worked.")
    assert record.decision_id is None
    assert record.followed_a_recommendation is False


def test_a_record_may_link_to_the_decision_it_followed():
    record = DecisionRecord.create(
        "Adopt wine sampling", "It worked.", decision_id=CONTRACT_ID
    )
    assert record.decision_id == CONTRACT_ID
    assert record.followed_a_recommendation is True


def test_a_link_that_is_not_a_contract_identifier_is_refused():
    with pytest.raises(ValueError, match="begin with dec_"):
        DecisionRecord.create("Adopt it", "It worked.", decision_id="12345")


def test_a_record_without_a_summary_is_refused():
    with pytest.raises(ValueError, match="summary is required"):
        DecisionRecord.create("", "It worked.")


def test_a_record_without_a_rationale_is_refused():
    with pytest.raises(ValueError, match="rationale is required"):
        DecisionRecord.create("Adopt it", "")
