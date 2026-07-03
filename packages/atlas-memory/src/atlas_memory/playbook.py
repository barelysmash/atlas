from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass(frozen=True)
class PlaybookEntry:
    """A standardized practice adopted into organizational memory."""

    id: UUID
    timestamp: datetime
    title: str
    standard: str

    @classmethod
    def create(cls, title: str, standard: str) -> "PlaybookEntry":
        if not title:
            raise ValueError("title is required")

        if not standard:
            raise ValueError("standard is required")

        return cls(
            id=uuid4(),
            timestamp=datetime.now(timezone.utc),
            title=title,
            standard=standard,
        )