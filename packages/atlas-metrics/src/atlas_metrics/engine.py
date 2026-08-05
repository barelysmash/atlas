from typing import Any

from atlas_metrics.metric import Metric


class MetricEngine:
    """Executes registered metric calculations."""

    def calculate(self, metric: Metric, **kwargs: Any) -> Any:
        return metric.calculation(**kwargs)
