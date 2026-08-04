"""ULID generation for platform contract identifiers.

JAM's contracts identify Observations, Insights, and Decisions by ULID,
encoded in Crockford base32. That alphabet excludes I, L, O, and U, so a
naive base32 encoder produces identifiers the JAM schemas reject.

This module is deliberately dependency-free and belongs in Foundation once
Foundation carries shared code. Moving it is an import change and nothing
more.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_TIMESTAMP_BITS = 48
_RANDOM_BITS = 80
_ENCODED_LENGTH = 26

__all__ = ["new_ulid"]


def new_ulid(now: datetime | None = None) -> str:
    """Return a 26-character Crockford base32 ULID.

    The first ten characters encode milliseconds since the Unix epoch, so
    lexicographic order matches creation order. Pass ``now`` to make the
    timestamp component deterministic in tests.
    """
    moment = now if now is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    milliseconds = int(moment.timestamp() * 1000)
    if not 0 <= milliseconds < (1 << _TIMESTAMP_BITS):
        raise ValueError(f"timestamp out of ULID range: {milliseconds}")

    value = (milliseconds << _RANDOM_BITS) | secrets.randbits(_RANDOM_BITS)

    characters = []
    for _ in range(_ENCODED_LENGTH):
        characters.append(_ALPHABET[value & 0x1F])
        value >>= 5
    return "".join(reversed(characters))
