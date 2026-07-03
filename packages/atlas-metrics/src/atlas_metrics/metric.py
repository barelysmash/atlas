from dataclasses import dataclass
from typing import Callable, Any


@dataclass(frozen=True)
class Metric:
    """Reusable metric definition."""

    name: str
    description: str
    calculation: Callable[..., Any]