from dataclasses import dataclass
from datetime import UTC, datetime
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
            timestamp=datetime.now(UTC),
            summary=summary,
            rationale=rationale,
        )
