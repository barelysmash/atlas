from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class Experiment:
    """A structured operational test."""

    id: UUID
    name: str
    hypothesis: str
    start_time: datetime
    evidence: dict[str, Any]

    @classmethod
    def create(
        cls,
        name: str,
        hypothesis: str,
        evidence: dict[str, Any] | None = None,
    ) -> "Experiment":
        if not name:
            raise ValueError("name is required")

        if not hypothesis:
            raise ValueError("hypothesis is required")

        return cls(
            id=uuid4(),
            name=name,
            hypothesis=hypothesis,
            start_time=datetime.now(timezone.utc),
            evidence=evidence or {},
        )