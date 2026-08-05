from datetime import UTC, datetime

from atlas_core import Metric, Observation
from atlas_core.insight_engine import generate_insights

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 1, 14, 0, tzinfo=UTC)


def _observation(metric_name: str, value: float) -> Observation:
    return Observation(
        domain="sales",
        subject="Fonda San Miguel",
        summary=f"{metric_name} was {value:,.0f}.",
        metrics=(Metric(name=metric_name, value=value),),
        source_ref="tabc:Fonda San Miguel:2026-06",
        observed_at=OBSERVED_AT,
    )


def test_generate_insights_from_wine_observation():
    observation = _observation("wine_receipts", 50000.0)
    insights = generate_insights([observation], now=NOW)
    assert len(insights) == 1
    assert insights[0].statement == "Wine remains an active revenue contributor."
    assert insights[0].confidence == 0.80


def test_generated_insight_cites_the_observation():
    observation = _observation("wine_receipts", 50000.0)
    insight = generate_insights([observation], now=NOW)[0]
    assert insight.cites(observation.observation_id)
    assert insight.evidence[0].metric == observation.get_metric("wine_receipts")


def test_generated_insight_inherits_the_domain():
    insight = generate_insights([_observation("wine_receipts", 50000.0)], now=NOW)[0]
    assert insight.domain == "sales"


def test_the_clock_is_injectable():
    insight = generate_insights([_observation("wine_receipts", 50000.0)], now=NOW)[0]
    assert insight.created_at == NOW


def test_generate_insights_ignores_unknown_metrics():
    assert generate_insights([_observation("unknown_metric", 1.0)], now=NOW) == []


def test_wine_receipts_is_found_among_several_metrics():
    observation = Observation(
        domain="sales",
        summary="Receipts were recorded.",
        metrics=(
            Metric(name="beer_receipts", value=25000.0),
            Metric(name="wine_receipts", value=50000.0),
        ),
        observed_at=OBSERVED_AT,
    )
    insight = generate_insights([observation], now=NOW)[0]
    assert insight.evidence[0].metric is not None
    assert insight.evidence[0].metric.name == "wine_receipts"
