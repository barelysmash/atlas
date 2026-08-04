from atlas_core.observation import Observation

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def _observation() -> Observation:
    return Observation(
        category="revenue",
        metric="weekly_total",
        value=48210.0,
        summary="Weekly revenue was 48210.",
    )


def test_observation_is_identified_on_construction() -> None:
    assert len(_observation().observation_id) == 26


def test_identifier_is_schema_valid() -> None:
    assert set(_observation().observation_id) <= CROCKFORD


def test_identifiers_are_distinct() -> None:
    assert _observation().observation_id != _observation().observation_id


def test_equality_ignores_identity() -> None:
    assert _observation() == _observation()


def test_identifier_can_be_supplied() -> None:
    pinned = Observation(
        category="revenue",
        metric="weekly_total",
        value=48210.0,
        summary="Weekly revenue was 48210.",
        observation_id="01JQZX3T8KMNPQRSTVWXYZ0123",
    )
    assert pinned.observation_id == "01JQZX3T8KMNPQRSTVWXYZ0123"
