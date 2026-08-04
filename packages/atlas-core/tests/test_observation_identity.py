from datetime import datetime, timezone

from atlas_core import Metric, Observation

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _observation() -> Observation:
    return Observation(
        domain="revenue",
        summary="Weekly revenue was 48210.",
        metrics=(Metric(name="weekly_total", value=48210.0, unit="usd"),),
        observed_at=OBSERVED_AT,
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
        domain="revenue",
        summary="Weekly revenue was 48210.",
        metrics=(Metric(name="weekly_total", value=48210.0),),
        observed_at=OBSERVED_AT,
        observation_id="obs_01JQZX3T8KMNPQRSTVWXYZ0123",
    )
    assert pinned.observation_id == "obs_01JQZX3T8KMNPQRSTVWXYZ0123"
