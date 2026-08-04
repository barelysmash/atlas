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
    assert len(_observation().observation_id) == 30


def test_identifier_carries_the_contract_prefix() -> None:
    assert _observation().observation_id.startswith("obs_")


def test_identifier_is_schema_valid() -> None:
    _, _, ulid = _observation().observation_id.partition("_")
    assert len(ulid) == 26
    assert set(ulid) <= CROCKFORD


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
        observation_id="obs_01JQZX3T8KMNPQRSTVWXYZ0123",
    )
    assert pinned.observation_id == "obs_01JQZX3T8KMNPQRSTVWXYZ0123"
