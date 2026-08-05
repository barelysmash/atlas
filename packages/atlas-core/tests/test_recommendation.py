import pytest
from atlas_core import Recommendation

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def test_recommendation_is_identified_on_construction():
    rec = Recommendation(statement="Continue premium wine sampling.")
    assert rec.recommendation_id.startswith("rec_")
    _, _, ulid = rec.recommendation_id.partition("_")
    assert len(ulid) == 26
    assert set(ulid) <= CROCKFORD


def test_identity_is_excluded_from_equality():
    assert Recommendation(statement="Do the thing.") == Recommendation(
        statement="Do the thing."
    )


def test_reversible_defaults_to_false():
    assert Recommendation(statement="Do the thing.").reversible is False


def test_advisory_recommendation_has_no_action_type():
    assert Recommendation(statement="Watch this closely.").action_type is None


def test_parameters_require_an_action_type():
    with pytest.raises(ValueError, match="action_type"):
        Recommendation(statement="Do it.", parameters={"item": "wine"})


def test_parameters_are_accepted_alongside_an_action_type():
    rec = Recommendation(
        statement="Launch the promotion.",
        action_type="launch_promotion",
        parameters={"item": "Casa Madero"},
    )
    assert rec.parameters == {"item": "Casa Madero"}
