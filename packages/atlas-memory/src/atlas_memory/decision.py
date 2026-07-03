from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Decision:
    """A documented decision derived from evidence."""

    id: UUID
    timestamp: datetime
    summary: str
    rationale: str

    @classmethod
    def create(cls, summary: str, rationale: str) -> "Decision":
        if not summary:
            raise ValueError("summary is required")

        if not rationale:
            raise ValueError("rationale is required")

        return cls(
            id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            summary=summary,
            rationale=rationale,
        )