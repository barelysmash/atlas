from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Measurement:
    """Immutable numeric observation."""

    name: str
    value: float
    timestamp: datetime
    dimensions: dict[str, Any]