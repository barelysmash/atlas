import pytest

from atlas_metrics import Metric, MetricEngine


def test_metric_engine_calculates_ratio():
    def ratio(a: float, b: float) -> float:
        return a / b

    metric = Metric(
        name="Ratio",
        description="Simple ratio calculation.",
        calculation=ratio,
    )

    engine = MetricEngine()

    assert engine.calculate(metric, a=20, b=5) == 4


def test_metric_engine_raises_calculation_errors():
    def divide(a: float, b: float) -> float:
        return a / b

    metric = Metric(
        name="Divide",
        description="Division calculation.",
        calculation=divide,
    )

    engine = MetricEngine()

    with pytest.raises(ZeroDivisionError):
        engine.calculate(metric, a=20, b=0)