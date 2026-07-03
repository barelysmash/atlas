from atlas_metrics.metric import Metric


class MetricEngine:
    """Executes registered metric calculations."""

    def calculate(self, metric: Metric, **kwargs):
        return metric.calculation(**kwargs)