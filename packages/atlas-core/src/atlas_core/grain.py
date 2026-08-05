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

# How a metric's values combine when several periods are rolled up.
SUM = "sum"
MEAN = "mean"

# A ratio that cannot be recovered from its own values. A week's sales per
# labour hour is total sales over total hours, not the average of seven
# nightly figures, so a rate must be derived from components that can
# themselves be summed.
RATE = "rate"

AGGREGATIONS = (SUM, MEAN, RATE)
