from datetime import datetime, timezone

from atlas_core import Metric, Observation
from atlas_core.insight_engine import generate_insights

OBSERVED_AT = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


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
    insights = generate_insights([observation])
    assert len(insights) == 1
    assert insights[0].summary == "Wine remains an active revenue contributor."
    assert insights[0].confidence == 0.80
    assert insights[0].observations == [observation]


def test_generate_insights_ignores_unknown_metrics():
    assert generate_insights([_observation("unknown_metric", 1.0)]) == []


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
    assert len(generate_insights([observation])) == 1
