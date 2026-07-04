from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class OperationalRecord:
    """Canonical operational measurement used across Atlas."""

    id: UUID
    source: str
    entity: str
    period: str
    category: str
    metric: str
    value: float
    timestamp: datetime
    dimensions: dict[str, Any]

    @classmethod
    def create(
        cls,
        source: str,
        entity: str,
        period: str,
        category: str,
        metric: str,
        value: float,
        dimensions: dict[str, Any] | None = None,
    ) -> "OperationalRecord":
        if not source:
            raise ValueError("source is required")
        if not entity:
            raise ValueError("entity is required")
        if not period:
            raise ValueError("period is required")
        if not metric:
            raise ValueError("metric is required")

        return cls(
            id=uuid4(),
            source=source,
            entity=entity,
            period=period,
            category=category,
            metric=metric,
            value=float(value),
            timestamp=datetime.now(timezone.utc),
            dimensions=dimensions or {},
        )