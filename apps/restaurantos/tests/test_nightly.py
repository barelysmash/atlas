from datetime import date

import pytest
from atlas_core.derived_metric_engine import derive_metrics

from restaurantos.metrics import NIGHTLY_DERIVED_METRICS
from restaurantos.nightly import (
    CompLine,
    FeatureSale,
    NightlyReport,
    normalize_nightly_report,
)


def by_metric(records):
    return {record.metric: record for record in records}


def sample(**overrides):
    values = dict(
        restaurant="Fonda San Miguel",
        service_date=date(2026, 8, 19),
        reported_splh=78.01,
        labor_cost_actual=4054.15,
        labor_hours_actual=275.74,
        reservation_covers=232,
        dining_room_covers=262,
        bar_atrium_covers=135,
        total_covers=397,
        comps=(
            CompLine("Anniversary", 52.0),
            CompLine("Birthday", 278.0),
            CompLine("Manager", 13.74),
        ),
        voids=23.50,
        source_message_id="gmail-0819",
    )
    values.update(overrides)
    return NightlyReport(**values)


def test_sample_normalizes_and_marks_implied_sales():
    records = by_metric(normalize_nightly_report(sample()))

    assert records["net_sales"].value == pytest.approx(21510.4774)
    assert records["net_sales"].dimensions["estimated"] is True
    assert records["net_sales"].dimensions["reported_splh"] == 78.01
    assert records["net_sales"].dimensions["source_message_id"] == "gmail-0819"
    assert records["comps"].value == pytest.approx(343.74)
    assert records["guest_count"].value == 397


def test_reported_sales_wins_over_implied_sales():
    records = by_metric(normalize_nightly_report(sample(net_sales=22000.0)))

    assert records["net_sales"].value == 22000.0
    assert records["net_sales"].dimensions["estimated"] is False


def test_dynamic_comp_and_feature_lines_are_preserved_as_dimensions():
    report = sample(
        comps=(CompLine("Training Meal", 111.40, 1),),
        reported_total_comps=111.40,
        feature_sales=(FeatureSale("Camarones", 720.57, 19),),
    )
    records = normalize_nightly_report(report)

    comp = next(record for record in records if record.metric == "comp_amount")
    feature = next(record for record in records if record.metric == "feature_sales")

    assert comp.dimensions["comp_category"] == "Training Meal"
    assert comp.dimensions["count"] == 1
    assert feature.dimensions["item"] == "Camarones"
    assert feature.dimensions["quantity"] == 19


def test_derived_metrics_match_sample():
    records = derive_metrics(
        normalize_nightly_report(sample()),
        NIGHTLY_DERIVED_METRICS,
    )
    metrics = by_metric(records)

    assert metrics["splh"].value == pytest.approx(78.01)
    assert metrics["walk_in_covers"].value == 165
    assert metrics["reservation_share"].value == pytest.approx(58.43828715)
    assert metrics["covers_per_labor_hour"].value == pytest.approx(1.4397620947)
    assert metrics["labor_cost_pct"].value == pytest.approx(18.8473269310)
    assert metrics["comp_pct"].value == pytest.approx(1.5980119530)
    assert metrics["void_pct"].value == pytest.approx(0.1092490862)


def test_actual_vs_scheduled_labor_produces_variances():
    report = sample(
        net_sales=24899.0,
        labor_cost_actual=4930.98,
        labor_cost_scheduled=5249.67,
        labor_hours_actual=329.91,
        labor_hours_scheduled=350.75,
    )
    metrics = by_metric(
        derive_metrics(
            normalize_nightly_report(report),
            NIGHTLY_DERIVED_METRICS,
        )
    )

    assert metrics["labor_cost_variance"].value == pytest.approx(-318.69)
    assert metrics["labor_cost_to_schedule_pct"].value == pytest.approx(
        93.9298,
        rel=1e-4,
    )
    assert metrics["labor_hours_variance"].value == pytest.approx(-20.84)
    assert metrics["labor_hours_to_schedule_pct"].value == pytest.approx(
        94.0584,
        rel=1e-4,
    )


def test_room_mismatch_is_flagged_but_not_rejected():
    report = sample(total_covers=400)

    assert "room_total_mismatch" in report.quality_flags
    records = normalize_nightly_report(report)
    guest_count = next(
        record for record in records if record.metric == "guest_count"
    )
    assert "room_total_mismatch" in guest_count.dimensions["quality_flags"]


def test_missing_structured_total_uses_rooms_and_flags_narrative_disagreement():
    report = sample(
        total_covers=None,
        dining_room_covers=235,
        bar_atrium_covers=106,
        narrative_total_covers=235,
    )

    assert report.effective_total_covers == 341
    assert "narrative_total_mismatch" in report.quality_flags


def test_reservations_cannot_exceed_effective_total():
    with pytest.raises(ValueError, match="reservation_covers"):
        sample(reservation_covers=398, total_covers=397)
