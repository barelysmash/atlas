from dataclasses import dataclass
from datetime import date

from atlas_core.operational_record import OperationalRecord

BASE_METRICS = (
    "net_sales",
    "labor_cost",
    "labor_hours",
    "reservation_covers",
    "guest_count",
    "dining_room_covers",
    "bar_atrium_covers",
    "comps",
    "voids",
)


@dataclass(frozen=True, slots=True)
class OperatingPeriodSummary:
    entity: str
    label: str
    start_date: date
    end_date: date
    service_nights: int
    totals: tuple[tuple[str, float], ...]
    coverage: tuple[tuple[str, int], ...]
    derived: tuple[tuple[str, float], ...]
    derived_coverage: tuple[tuple[str, int], ...]
    estimated_sales_nights: int = 0

    def total(self, metric: str) -> float | None:
        return dict(self.totals).get(metric)

    def nights_with(self, metric: str) -> int:
        return dict(self.coverage).get(metric, 0)

    def per_night(self, metric: str) -> float | None:
        total = self.total(metric)
        nights = self.nights_with(metric)
        if total is None or nights == 0:
            return None
        return total / nights

    def metric(self, metric: str) -> float | None:
        return dict(self.derived).get(metric)

    def metric_nights(self, metric: str) -> int:
        return dict(self.derived_coverage).get(metric, 0)


def _period_date(record: OperationalRecord) -> date | None:
    try:
        return date.fromisoformat(record.period)
    except ValueError:
        return None


def _selected_records(
    records: list[OperationalRecord],
    start_date: date,
    end_date: date,
    entity: str | None,
) -> list[OperationalRecord]:
    selected = [
        record
        for record in records
        if (period := _period_date(record)) is not None
        and start_date <= period <= end_date
        and (entity is None or record.entity == entity)
    ]
    if not selected:
        raise ValueError("no daily records found in the requested period")

    entities = {record.entity for record in selected}
    if entity is None and len(entities) != 1:
        raise ValueError("entity is required when records contain multiple entities")

    return selected


def _metric_by_period(
    records: list[OperationalRecord], metric: str
) -> dict[str, OperationalRecord]:
    values: dict[str, OperationalRecord] = {}
    for record in records:
        if record.metric != metric:
            continue
        if record.period in values:
            raise ValueError(
                f"duplicate {metric} record for {record.entity} {record.period}"
            )
        values[record.period] = record
    return values


def _ratio(
    records: list[OperationalRecord],
    left_metric: str,
    right_metric: str,
    *,
    scale: float = 1.0,
) -> tuple[float | None, int]:
    left = _metric_by_period(records, left_metric)
    right = _metric_by_period(records, right_metric)
    periods = sorted(left.keys() & right.keys())
    if not periods:
        return None, 0

    numerator = sum(left[period].value for period in periods)
    denominator = sum(right[period].value for period in periods)
    if denominator == 0:
        return None, len(periods)
    return numerator / denominator * scale, len(periods)


def _difference(
    records: list[OperationalRecord],
    left_metric: str,
    right_metric: str,
) -> tuple[float | None, int]:
    left = _metric_by_period(records, left_metric)
    right = _metric_by_period(records, right_metric)
    periods = sorted(left.keys() & right.keys())
    if not periods:
        return None, 0
    value = sum(left[period].value - right[period].value for period in periods)
    return value, len(periods)


def _derived_metrics(
    records: list[OperationalRecord],
) -> tuple[dict[str, float], dict[str, int]]:
    values: dict[str, float] = {}
    coverage: dict[str, int] = {}

    definitions = {
        "splh": ("net_sales", "labor_hours", 1.0),
        "average_check": ("net_sales", "guest_count", 1.0),
        "reservation_share": ("reservation_covers", "guest_count", 100.0),
        "covers_per_labor_hour": ("guest_count", "labor_hours", 1.0),
        "labor_cost_pct": ("labor_cost", "net_sales", 100.0),
        "labor_cost_per_cover": ("labor_cost", "guest_count", 1.0),
        "dining_room_share": ("dining_room_covers", "guest_count", 100.0),
        "bar_atrium_share": ("bar_atrium_covers", "guest_count", 100.0),
        "comp_pct": ("comps", "net_sales", 100.0),
        "void_pct": ("voids", "net_sales", 100.0),
    }
    for name, (left, right, scale) in definitions.items():
        value, nights = _ratio(records, left, right, scale=scale)
        if value is not None:
            values[name] = value
        coverage[name] = nights

    walk_ins, nights = _difference(records, "guest_count", "reservation_covers")
    if walk_ins is not None:
        values["walk_in_covers"] = walk_ins
    coverage["walk_in_covers"] = nights

    reservations = _metric_by_period(records, "reservation_covers")
    guests = _metric_by_period(records, "guest_count")
    shared = sorted(reservations.keys() & guests.keys())
    if shared:
        total_guests = sum(guests[period].value for period in shared)
        walk_ins = sum(
            guests[period].value - reservations[period].value for period in shared
        )
        if total_guests:
            values["walk_in_share"] = walk_ins / total_guests * 100.0
    coverage["walk_in_share"] = len(shared)

    return values, coverage


def summarize_operating_period(
    records: list[OperationalRecord],
    start_date: date,
    end_date: date,
    *,
    entity: str | None = None,
    label: str | None = None,
) -> OperatingPeriodSummary:
    """Summarize daily operating facts without averaging nightly rates."""
    if end_date < start_date:
        raise ValueError("end_date cannot be before start_date")

    selected = _selected_records(records, start_date, end_date, entity)
    resolved_entity = entity or selected[0].entity
    service_nights = len({record.period for record in selected})

    totals: dict[str, float] = {}
    coverage: dict[str, int] = {}
    for metric in BASE_METRICS:
        by_period = _metric_by_period(selected, metric)
        coverage[metric] = len(by_period)
        if by_period:
            totals[metric] = sum(record.value for record in by_period.values())

    net_sales = _metric_by_period(selected, "net_sales")
    estimated_sales_nights = sum(
        bool(record.dimensions.get("estimated")) for record in net_sales.values()
    )
    derived, derived_coverage = _derived_metrics(selected)

    return OperatingPeriodSummary(
        entity=resolved_entity,
        label=label or f"{start_date.isoformat()} to {end_date.isoformat()}",
        start_date=start_date,
        end_date=end_date,
        service_nights=service_nights,
        totals=tuple(sorted(totals.items())),
        coverage=tuple(sorted(coverage.items())),
        derived=tuple(sorted(derived.items())),
        derived_coverage=tuple(sorted(derived_coverage.items())),
        estimated_sales_nights=estimated_sales_nights,
    )


def percentage_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous * 100.0


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


def _number(value: float | None, decimals: int = 1) -> str:
    return "n/a" if value is None else f"{value:,.{decimals}f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _change_line(
    label: str,
    current: float | None,
    previous: float | None,
    *,
    percentage_points: bool = False,
) -> str:
    if current is None or previous is None:
        return f"- {label}: n/a"
    if percentage_points:
        delta = current - previous
        return f"- {label}: {delta:+.1f} pp"
    change = percentage_change(current, previous)
    return f"- {label}: {'n/a' if change is None else f'{change:+.1f}%'}"


def _volume_change_line(
    label: str,
    metric: str,
    current: OperatingPeriodSummary,
    previous: OperatingPeriodSummary,
) -> str:
    current_nights = current.nights_with(metric)
    previous_nights = previous.nights_with(metric)
    if current_nights == previous_nights:
        return _change_line(label, current.total(metric), previous.total(metric))

    change = percentage_change(
        current.per_night(metric),
        previous.per_night(metric),
    )
    change_text = "n/a" if change is None else f"{change:+.1f}%"
    return (
        f"- {label} / covered night: {change_text} "
        f"({current_nights} vs {previous_nights} nights)"
    )


def generate_operating_brief(
    current: OperatingPeriodSummary,
    previous: OperatingPeriodSummary | None = None,
) -> str:
    """Render a compact executive brief from one or two period summaries."""
    sales = current.total("net_sales")
    covers = current.total("guest_count")
    labor = current.total("labor_cost")
    labor_pct = _pct(current.metric("labor_cost_pct"))

    lines = [
        f"# {current.entity} Operating Brief",
        "",
        f"## {current.label}",
        f"- Service nights represented: {current.service_nights}",
        f"- Net sales: {_money(sales)}",
        f"- Covers: {_number(covers, 0)}",
        f"- Average check: {_money(current.metric('average_check'))}",
        f"- SPLH: {_money(current.metric('splh'))}",
        f"- Labor cost: {_money(labor)} ({labor_pct})",
        f"- Reservation share: {_pct(current.metric('reservation_share'))}",
        f"- Comp rate: {_pct(current.metric('comp_pct'))}",
        f"- Void rate: {_pct(current.metric('void_pct'))}",
        "",
        "## Data Coverage",
        (
            f"- Sales {current.nights_with('net_sales')}/{current.service_nights}; "
            f"covers {current.nights_with('guest_count')}/{current.service_nights}; "
            f"labor {current.nights_with('labor_hours')}/{current.service_nights}"
        ),
        f"- Estimated sales nights: {current.estimated_sales_nights}",
    ]

    if previous is not None:
        if previous.entity != current.entity:
            raise ValueError("comparison summaries must describe the same entity")
        lines.extend(
            [
                "",
                f"## vs {previous.label}",
                _volume_change_line("Net sales", "net_sales", current, previous),
                _volume_change_line("Covers", "guest_count", current, previous),
                _change_line(
                    "Average check",
                    current.metric("average_check"),
                    previous.metric("average_check"),
                ),
                _change_line(
                    "SPLH",
                    current.metric("splh"),
                    previous.metric("splh"),
                ),
                _change_line(
                    "Labor cost %",
                    current.metric("labor_cost_pct"),
                    previous.metric("labor_cost_pct"),
                    percentage_points=True,
                ),
                _change_line(
                    "Reservation share",
                    current.metric("reservation_share"),
                    previous.metric("reservation_share"),
                    percentage_points=True,
                ),
                _change_line(
                    "Comp rate",
                    current.metric("comp_pct"),
                    previous.metric("comp_pct"),
                    percentage_points=True,
                ),
                _change_line(
                    "Void rate",
                    current.metric("void_pct"),
                    previous.metric("void_pct"),
                    percentage_points=True,
                ),
            ]
        )

    return "\n".join(lines) + "\n"
