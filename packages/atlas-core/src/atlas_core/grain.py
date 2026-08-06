"""Reporting grain and how values at that grain may be combined."""

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"

GRAINS = (DAILY, WEEKLY, MONTHLY)

# The ISO 8601 duration each grain covers, so an emitted Metric can state the
# window its value describes. JAM's contracts express periods this way.
GRAIN_PERIODS = {
    DAILY: "P1D",
    WEEKLY: "P1W",
    MONTHLY: "P1M",
}

# The ISO 8601 designator for each grain, so a span of several periods can
# state the window it covers: four consecutive months is P4M, not P1M.
GRAIN_UNITS = {
    DAILY: "D",
    WEEKLY: "W",
    MONTHLY: "M",
}


def span_period(grain: str, periods: int) -> str:
    """The ISO 8601 duration covering that many periods at that grain."""
    if periods < 1:
        raise ValueError("a span covers at least one period")
    return f"P{periods}{GRAIN_UNITS[grain]}"


# How a metric's values combine when several periods are rolled up.
SUM = "sum"
MEAN = "mean"

# A ratio that cannot be recovered from its own values. A week's sales per
# labour hour is total sales over total hours, not the average of seven
# nightly figures, so a rate must be derived from components that can
# themselves be summed.
RATE = "rate"

AGGREGATIONS = (SUM, MEAN, RATE)


# Blocks moving the same way before movement counts as a streak.
MIN_STREAK_BLOCKS = 3
