from datetime import datetime, timezone

import pytest
from atlas_core.identifiers import (
    PREFIXES,
    new_decision_id,
    new_insight_id,
    new_observation_id,
    new_ulid,
)

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
EXCLUDED = set("ILOU")

# The patterns JAM's schemas match on. If these drift, emission breaks.
PATTERNS = {
    "obs": new_observation_id,
    "ins": new_insight_id,
    "dec": new_decision_id,
}


def test_length_is_twenty_six() -> None:
    assert len(new_ulid()) == 26


def test_uses_only_crockford_base32() -> None:
    for _ in range(500):
        assert set(new_ulid()) <= CROCKFORD


def test_never_emits_excluded_characters() -> None:
    for _ in range(500):
        assert not set(new_ulid()) & EXCLUDED


def test_identifiers_are_unique() -> None:
    assert len({new_ulid() for _ in range(2000)}) == 2000


def test_timestamp_prefix_sorts_by_creation_order() -> None:
    earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert new_ulid(earlier)[:10] < new_ulid(later)[:10]


def test_same_instant_shares_a_timestamp_prefix() -> None:
    instant = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    assert new_ulid(instant)[:10] == new_ulid(instant)[:10]


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError):
        new_ulid(datetime(2026, 1, 1))  # noqa: DTZ001 - naive input is the point


@pytest.mark.parametrize("prefix", sorted(PATTERNS))
def test_contract_identifier_shape(prefix: str) -> None:
    identifier = PATTERNS[prefix]()
    head, _, tail = identifier.partition("_")
    assert head == prefix
    assert len(tail) == 26
    assert set(tail) <= CROCKFORD


@pytest.mark.parametrize("prefix", sorted(PATTERNS))
def test_contract_identifier_never_uses_excluded_characters(prefix: str) -> None:
    for _ in range(200):
        _, _, tail = PATTERNS[prefix]().partition("_")
        assert not set(tail) & EXCLUDED


def test_prefixes_are_distinct() -> None:
    assert len(set(PREFIXES.values())) == len(PREFIXES)


def test_prefixed_identifiers_accept_an_instant() -> None:
    instant = datetime(2026, 3, 15, 12, 30, tzinfo=timezone.utc)
    assert new_observation_id(instant)[4:14] == new_observation_id(instant)[4:14]
