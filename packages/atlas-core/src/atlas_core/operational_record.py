from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from atlas_core.grain import AGGREGATIONS, GRAINS, MONTHLY, SUM


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
    grain: str = MONTHLY
    aggregation: str = SUM

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
        grain: str = MONTHLY,
        aggregation: str = SUM,
    ) -> "OperationalRecord":
        if not source:
            raise ValueError("source is required")
        if not entity:
            raise ValueError("entity is required")
        if not period:
            raise ValueError("period is required")
        if not metric:
            raise ValueError("metric is required")
        if grain not in GRAINS:
            raise ValueError(f"grain must be one of {GRAINS}")
        if aggregation not in AGGREGATIONS:
            raise ValueError(f"aggregation must be one of {AGGREGATIONS}")

        return cls(
            id=uuid4(),
            source=source,
            entity=entity,
            period=period,
            category=category,
            metric=metric,
            value=float(value),
            timestamp=datetime.now(UTC),
            dimensions=dimensions or {},
            grain=grain,
            aggregation=aggregation,
        )
