from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Observation:
    """A factual note about something that happened."""

    id: UUID
    timestamp: datetime
    summary: str
    evidence: dict[str, Any]

    @classmethod
    def create(cls, summary: str, evidence: dict[str, Any]) -> "Observation":
        if not summary:
            raise ValueError("summary is required")

        return cls(
            id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            summary=summary,
            evidence=evidence,
        )