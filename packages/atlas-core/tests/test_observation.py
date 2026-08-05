from datetime import UTC, datetime

from atlas_core import Metric, Observation

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _observation() -> Observation:
    return Observation(
        domain="operations",
        subject="Fonda San Miguel",
        summary="Wine receipts were $50,000.",
        metrics=(Metric(name="wine_receipts", value=50000.0, unit="usd"),),
        source_ref="TABC June 2026",
        observed_at=OBSERVED_AT,
    )


def test_create_observation():
    observation = _observation()
    assert observation.domain == "operations"
    assert observation.subject == "Fonda San Miguel"
    assert observation.summary == "Wine receipts were $50,000."
    assert observation.source_ref == "TABC June 2026"
    assert observation.observed_at == OBSERVED_AT


def test_metrics_are_carried_as_a_tuple():
    observation = _observation()
    assert isinstance(observation.metrics, tuple)
    assert len(observation.metrics) == 1
    assert observation.metrics[0].name == "wine_receipts"
    assert observation.metrics[0].value == 50000.0
    assert observation.metrics[0].unit == "usd"


def test_has_metric_finds_a_present_metric():
    assert _observation().has_metric("wine_receipts")


def test_has_metric_rejects_an_absent_metric():
    assert not _observation().has_metric("beer_receipts")


def test_get_metric_returns_the_named_metric():
    metric = _observation().get_metric("wine_receipts")
    assert metric is not None
    assert metric.value == 50000.0


def test_get_metric_returns_none_when_absent():
    assert _observation().get_metric("beer_receipts") is None


def test_optional_fields_default_to_none():
    observation = Observation(
        domain="operations",
        summary="Wine receipts were $50,000.",
        metrics=(Metric(name="wine_receipts", value=50000.0),),
        observed_at=OBSERVED_AT,
    )
    assert observation.subject is None
    assert observation.source_ref is None


def test_several_metrics_are_carried_together():
    observation = Observation(
        domain="beverage",
        subject="Casa Madero",
        summary="Casa Madero moved 214 bottles at a 21% attachment rate.",
        metrics=(
            Metric(name="units_sold", value=214, unit="bottles", period="P4W"),
            Metric(name="wine_attachment", value=0.21, unit="ratio", period="P4W"),
        ),
        observed_at=OBSERVED_AT,
    )
    assert observation.has_metric("units_sold")
    assert observation.has_metric("wine_attachment")
    assert len(observation.metrics) == 2
