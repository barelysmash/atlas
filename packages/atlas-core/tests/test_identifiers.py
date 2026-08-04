from datetime import datetime, timezone

import pytest
from atlas_core.identifiers import new_ulid

CROCKFORD = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
EXCLUDED = set("ILOU")


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
