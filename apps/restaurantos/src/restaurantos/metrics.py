from atlas_core.derived_metric import (
    DEFAULT_DERIVED_METRICS,
    DIFFERENCE,
    DerivedMetric,
)
from atlas_core.grain import RATE, SUM

WALK_IN_COVERS = DerivedMetric(
    metric="walk_in_covers",
    left="guest_count",
    right="reservation_covers",
    operation=DIFFERENCE,
    category="demand",
    aggregation=SUM,
)
RESERVATION_SHARE = DerivedMetric(
    metric="reservation_share",
    left="reservation_covers",
    right="guest_count",
    category="demand",
    aggregation=RATE,
    scale=100.0,
)
WALK_IN_SHARE = DerivedMetric(
    metric="walk_in_share",
    left="walk_in_covers",
    right="guest_count",
    category="demand",
    aggregation=RATE,
    scale=100.0,
)
COVERS_PER_LABOR_HOUR = DerivedMetric(
    metric="covers_per_labor_hour",
    left="guest_count",
    right="labor_hours",
    category="productivity",
    aggregation=RATE,
)
LABOR_COST_PCT = DerivedMetric(
    metric="labor_cost_pct",
    left="labor_cost",
    right="net_sales",
    category="labor",
    aggregation=RATE,
    scale=100.0,
)
LABOR_COST_PER_COVER = DerivedMetric(
    metric="labor_cost_per_cover",
    left="labor_cost",
    right="guest_count",
    category="labor",
    aggregation=RATE,
)
LABOR_COST_VARIANCE = DerivedMetric(
    metric="labor_cost_variance",
    left="labor_cost_actual",
    right="labor_cost_scheduled",
    operation=DIFFERENCE,
    category="labor",
    aggregation=SUM,
)
LABOR_COST_TO_SCHEDULE_PCT = DerivedMetric(
    metric="labor_cost_to_schedule_pct",
    left="labor_cost_actual",
    right="labor_cost_scheduled",
    category="labor",
    aggregation=RATE,
    scale=100.0,
)
LABOR_HOURS_VARIANCE = DerivedMetric(
    metric="labor_hours_variance",
    left="labor_hours_actual",
    right="labor_hours_scheduled",
    operation=DIFFERENCE,
    category="labor",
    aggregation=SUM,
)
LABOR_HOURS_TO_SCHEDULE_PCT = DerivedMetric(
    metric="labor_hours_to_schedule_pct",
    left="labor_hours_actual",
    right="labor_hours_scheduled",
    category="labor",
    aggregation=RATE,
    scale=100.0,
)
DINING_ROOM_SHARE = DerivedMetric(
    metric="dining_room_share",
    left="dining_room_covers",
    right="guest_count",
    category="demand",
    aggregation=RATE,
    scale=100.0,
)
BAR_ATRIUM_SHARE = DerivedMetric(
    metric="bar_atrium_share",
    left="bar_atrium_covers",
    right="guest_count",
    category="demand",
    aggregation=RATE,
    scale=100.0,
)
COMP_PCT = DerivedMetric(
    metric="comp_pct",
    left="comps",
    right="net_sales",
    category="hospitality",
    aggregation=RATE,
    scale=100.0,
)
VOID_PCT = DerivedMetric(
    metric="void_pct",
    left="voids",
    right="net_sales",
    category="controls",
    aggregation=RATE,
    scale=100.0,
)

NIGHTLY_DERIVED_METRICS = (
    *DEFAULT_DERIVED_METRICS,
    WALK_IN_COVERS,
    RESERVATION_SHARE,
    WALK_IN_SHARE,
    COVERS_PER_LABOR_HOUR,
    LABOR_COST_PCT,
    LABOR_COST_PER_COVER,
    LABOR_COST_VARIANCE,
    LABOR_COST_TO_SCHEDULE_PCT,
    LABOR_HOURS_VARIANCE,
    LABOR_HOURS_TO_SCHEDULE_PCT,
    DINING_ROOM_SHARE,
    BAR_ATRIUM_SHARE,
    COMP_PCT,
    VOID_PCT,
)
