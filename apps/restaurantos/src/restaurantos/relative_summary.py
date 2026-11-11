"""Relative-only comparison of two operating periods.

This is the shape RestaurantOS hands to a consumer outside the private data
boundary (JARVIS, through the peer API). It carries how the business moved,
never how big it is: percent changes, percentage-point deltas, directions and
night counts. No dollar amount, cover count, labor hour total or rate level
appears in it, so nothing here lets a reader reconstruct an absolute figure.

The arithmetic mirrors ``operating_brief``: volumes compare on totals when both
periods cover the same number of nights and per covered night otherwise; rates
are period rates built from summed components, never means of nightly rates.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from restaurantos.operating_brief import (
    BASE_METRICS,
    OperatingPeriodSummary,
    percentage_change,
)

FIGURES_POLICY = "relative_only"

# Dollar- or count-denominated rates: compared as a percent change.
RATE_METRICS = (
    "average_check",
    "splh",
    "covers_per_labor_hour",
    "labor_cost_per_cover",
)

# Already percentages: compared as a percentage-point delta.
SHARE_METRICS = (
    "labor_cost_pct",
    "reservation_share",
    "walk_in_share",
    "dining_room_share",
    "bar_atrium_share",
    "comp_pct",
    "void_pct",
)

# The coverage a reader needs to judge how much weight a change can bear.
_COVERAGE_METRICS = ("net_sales", "guest_count", "labor_hours")

_FLAT_THRESHOLD = 0.05


def preceding_window(start_date: date, end_date: date) -> tuple[date, date]:
    """The window of equal length that ends the day before ``start_date``."""
    if end_date < start_date:
        raise ValueError("end_date cannot be before start_date")
    previous_end = start_date - timedelta(days=1)
    return previous_end - (end_date - start_date), previous_end


def _direction(change: float | None) -> str | None:
    if change is None:
        return None
    if abs(change) < _FLAT_THRESHOLD:
        return "flat"
    return "up" if change > 0 else "down"


def _rounded(change: float | None) -> float | None:
    return None if change is None else round(change, 1)


def _entry(
    metric: str,
    *,
    unit: str,
    basis: str,
    change: float | None,
    current_nights: int,
    previous_nights: int,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "unit": unit,
        "basis": basis,
        "change": _rounded(change),
        "direction": _direction(change),
        "current_nights": current_nights,
        "previous_nights": previous_nights,
    }


def _volume_change(
    metric: str,
    current: OperatingPeriodSummary,
    previous: OperatingPeriodSummary,
) -> dict[str, Any]:
    current_nights = current.nights_with(metric)
    previous_nights = previous.nights_with(metric)
    if current_nights == previous_nights:
        basis = "total"
        change = percentage_change(current.total(metric), previous.total(metric))
    else:
        basis = "per_covered_night"
        change = percentage_change(
            current.per_night(metric), previous.per_night(metric)
        )
    return _entry(
        metric,
        unit="percent",
        basis=basis,
        change=change,
        current_nights=current_nights,
        previous_nights=previous_nights,
    )


def _rate_change(
    metric: str,
    current: OperatingPeriodSummary,
    previous: OperatingPeriodSummary,
) -> dict[str, Any]:
    return _entry(
        metric,
        unit="percent",
        basis="period_rate",
        change=percentage_change(current.metric(metric), previous.metric(metric)),
        current_nights=current.metric_nights(metric),
        previous_nights=previous.metric_nights(metric),
    )


def _share_change(
    metric: str,
    current: OperatingPeriodSummary,
    previous: OperatingPeriodSummary,
) -> dict[str, Any]:
    now = current.metric(metric)
    before = previous.metric(metric)
    delta = None if now is None or before is None else now - before
    return _entry(
        metric,
        unit="percentage_points",
        basis="period_rate",
        change=delta,
        current_nights=current.metric_nights(metric),
        previous_nights=previous.metric_nights(metric),
    )


def _period(summary: OperatingPeriodSummary) -> dict[str, Any]:
    return {
        "label": summary.label,
        "start_date": summary.start_date.isoformat(),
        "end_date": summary.end_date.isoformat(),
        "service_nights": summary.service_nights,
        "estimated_sales_nights": summary.estimated_sales_nights,
        "nights_with": {
            metric: summary.nights_with(metric) for metric in _COVERAGE_METRICS
        },
    }


def relative_operating_summary(
    current: OperatingPeriodSummary,
    previous: OperatingPeriodSummary,
) -> dict[str, Any]:
    """Compare two period summaries without disclosing an absolute figure."""
    if previous.entity != current.entity:
        raise ValueError("comparison summaries must describe the same entity")

    changes = [_volume_change(metric, current, previous) for metric in BASE_METRICS]
    changes += [_rate_change(metric, current, previous) for metric in RATE_METRICS]
    changes += [_share_change(metric, current, previous) for metric in SHARE_METRICS]

    return {
        "entity": current.entity,
        "figures": FIGURES_POLICY,
        "current": _period(current),
        "previous": _period(previous),
        "changes": changes,
        "notes": [
            "Atlas withholds absolute dollar amounts, cover counts, labor "
            "totals and rate levels. Only changes between the two periods "
            "are reported.",
            "A change of null means one of the periods has no data for that metric.",
        ],
    }
