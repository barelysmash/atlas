from dataclasses import dataclass

from atlas_core.grain import RATE, SUM

RATIO = "ratio"
DIFFERENCE = "difference"

OPERATIONS = (RATIO, DIFFERENCE)


@dataclass(frozen=True, slots=True)
class DerivedMetric:
    """A metric computed from two others.

    Defining a metric this way rather than ingesting it pre-computed is what
    lets Atlas state it correctly at any grain: a week's rate is the week's
    numerator over the week's denominator, which cannot be recovered from the
    rate's own daily values.

    Definitions may build on each other. They are applied in order, so a
    definition may name a metric an earlier one produced.
    """

    metric: str
    left: str
    right: str
    operation: str = RATIO
    category: str = "productivity"
    aggregation: str = RATE
    scale: float = 1.0

    def __post_init__(self) -> None:
        if self.operation not in OPERATIONS:
            raise ValueError(f"operation must be one of {OPERATIONS}")


SALES_PER_LABOR_HOUR = DerivedMetric(
    metric="splh",
    left="net_sales",
    right="labor_hours",
    operation=RATIO,
    category="productivity",
    aggregation=RATE,
)

# Revenue per available seat-hour. Seat-hours rather than seats because a
# ten-hour trading day offers more capacity than a six-hour one, and a
# per-seat figure would read the difference as performance.
REVENUE_PER_SEAT_HOUR = DerivedMetric(
    metric="revpash",
    left="net_sales",
    right="seat_hours",
    operation=RATIO,
    category="productivity",
    aggregation=RATE,
)

# Sales less the cost of goods. A difference of two totals is itself a total,
# so this rolls up like any other summable metric.
CONTRIBUTION_MARGIN = DerivedMetric(
    metric="contribution_margin",
    left="net_sales",
    right="cogs",
    operation=DIFFERENCE,
    category="profitability",
    aggregation=SUM,
)

CONTRIBUTION_MARGIN_PER_SEAT_HOUR = DerivedMetric(
    metric="cm_per_seat_hour",
    left="contribution_margin",
    right="seat_hours",
    operation=RATIO,
    category="profitability",
    aggregation=RATE,
)

AVERAGE_CHECK = DerivedMetric(
    metric="average_check",
    left="net_sales",
    right="guest_count",
    operation=RATIO,
    category="sales",
    aggregation=RATE,
)

COMPS_PER_GUEST = DerivedMetric(
    metric="comps_per_guest",
    left="comps",
    right="guest_count",
    operation=RATIO,
    category="hospitality",
    aggregation=RATE,
)

# Wine as a share of beverage receipts. At a room whose liquor sales run ten
# times its wine sales, growth in wine dollars is invisible inside a total;
# its share is not.
WINE_SHARE = DerivedMetric(
    metric="wine_share",
    left="wine_receipts",
    right="total_receipts",
    operation=RATIO,
    category="mix",
    aggregation=RATE,
    # Reported as a percentage, so it reads on the same scale as the other
    # shares in a brief rather than as a fraction beside them.
    scale=100.0,
)

# A tuple rather than a list: a module-level default that any caller could
# append to is a default that changes underneath the next caller.
DEFAULT_DERIVED_METRICS = (
    SALES_PER_LABOR_HOUR,
    REVENUE_PER_SEAT_HOUR,
    CONTRIBUTION_MARGIN,
    CONTRIBUTION_MARGIN_PER_SEAT_HOUR,
    AVERAGE_CHECK,
    COMPS_PER_GUEST,
    WINE_SHARE,
)
