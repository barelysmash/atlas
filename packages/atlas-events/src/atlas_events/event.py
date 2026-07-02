from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Event:
    """Immutable Atlas event."""

    id: UUID
    type: str
    timestamp: datetime
    payload: dict[str, Any]

    @classmethod
    def create(cls, event_type: str, payload: dict[str, Any]) -> "Event":
        if not event_type:
            raise ValueError("event_type is required")

        return cls(
            id=uuid4(),
            type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
        )
