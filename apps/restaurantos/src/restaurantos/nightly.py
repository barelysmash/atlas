from dataclasses import dataclass
from datetime import date

from atlas_core.grain import DAILY, SUM
from atlas_core.operational_record import OperationalRecord


@dataclass(frozen=True, slots=True)
class CompLine:
    category: str
    amount: float
    count: int | None = None

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("comp category is required")
        if self.amount < 0:
            raise ValueError("comp amount cannot be negative")
        if self.count is not None and self.count < 0:
            raise ValueError("comp count cannot be negative")


@dataclass(frozen=True, slots=True)
class FeatureSale:
    item: str
    sales: float
    quantity: int | None = None

    def __post_init__(self) -> None:
        if not self.item.strip():
            raise ValueError("feature item is required")
        if self.sales < 0:
            raise ValueError("feature sales cannot be negative")
        if self.quantity is not None and self.quantity < 0:
            raise ValueError("feature quantity cannot be negative")


@dataclass(frozen=True, slots=True)
class NightlyReport:
    restaurant: str
    service_date: date
    net_sales: float | None = None
    reported_splh: float | None = None
    labor_cost_actual: float | None = None
    labor_cost_scheduled: float | None = None
    labor_hours_actual: float | None = None
    labor_hours_scheduled: float | None = None
    reservation_covers: int | None = None
    dining_room_covers: int | None = None
    bar_atrium_covers: int | None = None
    total_covers: int | None = None
    narrative_total_covers: int | None = None
    comps: tuple[CompLine, ...] = ()
    reported_total_comps: float | None = None
    voids: float | None = None
    void_count: int | None = None
    feature_sales: tuple[FeatureSale, ...] = ()
    source_message_id: str | None = None

    def __post_init__(self) -> None:
        if not self.restaurant.strip():
            raise ValueError("restaurant is required")

        values = {
            "net_sales": self.net_sales,
            "reported_splh": self.reported_splh,
            "labor_cost_actual": self.labor_cost_actual,
            "labor_cost_scheduled": self.labor_cost_scheduled,
            "labor_hours_actual": self.labor_hours_actual,
            "labor_hours_scheduled": self.labor_hours_scheduled,
            "reservation_covers": self.reservation_covers,
            "dining_room_covers": self.dining_room_covers,
            "bar_atrium_covers": self.bar_atrium_covers,
            "total_covers": self.total_covers,
            "narrative_total_covers": self.narrative_total_covers,
            "reported_total_comps": self.reported_total_comps,
            "voids": self.voids,
            "void_count": self.void_count,
        }
        for name, value in values.items():
            if value is not None and value < 0:
                raise ValueError(f"{name} cannot be negative")

        validation_total = self.effective_total_covers
        room_total = self.room_total_covers
        if room_total is not None and (
            validation_total is None or room_total > validation_total
        ):
            validation_total = room_total

        if (
            self.reservation_covers is not None
            and validation_total is not None
            and self.reservation_covers > validation_total
        ):
            raise ValueError("reservation_covers cannot exceed total covers")

    @property
    def room_total_covers(self) -> int | None:
        if self.dining_room_covers is None or self.bar_atrium_covers is None:
            return None
        return self.dining_room_covers + self.bar_atrium_covers

    @property
    def effective_total_covers(self) -> int | None:
        room_total = self.room_total_covers
        narrative_total = self.narrative_total_covers

        if (
            room_total is not None
            and narrative_total is not None
            and room_total == narrative_total
        ):
            return room_total
        if self.total_covers is not None:
            return self.total_covers
        if room_total is not None:
            return room_total
        return narrative_total

    @property
    def effective_net_sales(self) -> float | None:
        if self.net_sales is not None:
            return self.net_sales
        if self.reported_splh is None or self.labor_hours_actual is None:
            return None
        return self.reported_splh * self.labor_hours_actual

    @property
    def calculated_total_comps(self) -> float:
        return sum(line.amount for line in self.comps)

    @property
    def effective_total_comps(self) -> float | None:
        if self.reported_total_comps is not None:
            return self.reported_total_comps
        if self.comps:
            return self.calculated_total_comps
        return None

    @property
    def quality_flags(self) -> tuple[str, ...]:
        flags: list[str] = []
        room_total = self.room_total_covers

        if (
            self.total_covers is not None
            and room_total is not None
            and room_total != self.total_covers
        ):
            flags.append("room_total_mismatch")
        if (
            self.narrative_total_covers is not None
            and self.effective_total_covers is not None
            and self.narrative_total_covers != self.effective_total_covers
        ):
            flags.append("narrative_total_mismatch")
        if (
            self.reported_total_comps is not None
            and self.comps
            and abs(self.reported_total_comps - self.calculated_total_comps) > 0.01
        ):
            flags.append("comp_total_mismatch")
        if self.net_sales is None and self.effective_net_sales is not None:
            flags.append("net_sales_implied")

        return tuple(flags)


def _record(
    report: NightlyReport,
    metric: str,
    value: float,
    category: str,
    *,
    source: str,
    dimensions: dict[str, object] | None = None,
) -> OperationalRecord:
    base_dimensions: dict[str, object] = {}
    if report.source_message_id:
        base_dimensions["source_message_id"] = report.source_message_id
    if report.quality_flags:
        base_dimensions["quality_flags"] = report.quality_flags
    if dimensions:
        base_dimensions.update(dimensions)

    return OperationalRecord.create(
        source=source,
        entity=report.restaurant,
        period=report.service_date.isoformat(),
        category=category,
        metric=metric,
        value=value,
        dimensions=base_dimensions,
        grain=DAILY,
        aggregation=SUM,
    )


def normalize_nightly_report(
    report: NightlyReport,
    source: str = "nightly_email",
) -> list[OperationalRecord]:
    records: list[OperationalRecord] = []

    sales = report.effective_net_sales
    if sales is not None:
        dimensions: dict[str, object] = {"estimated": report.net_sales is None}
        if report.reported_splh is not None:
            dimensions["reported_splh"] = report.reported_splh
        if report.net_sales is None:
            dimensions["basis"] = "reported_splh_x_actual_labor_hours"
        records.append(
            _record(
                report,
                "net_sales",
                sales,
                "sales",
                source=source,
                dimensions=dimensions,
            )
        )

    if report.labor_cost_actual is not None:
        records.append(
            _record(
                report,
                "labor_cost",
                report.labor_cost_actual,
                "labor",
                source=source,
            )
        )
        records.append(
            _record(
                report,
                "labor_cost_actual",
                report.labor_cost_actual,
                "labor",
                source=source,
            )
        )
    if report.labor_cost_scheduled is not None:
        records.append(
            _record(
                report,
                "labor_cost_scheduled",
                report.labor_cost_scheduled,
                "labor",
                source=source,
            )
        )
    if report.labor_hours_actual is not None:
        records.append(
            _record(
                report,
                "labor_hours",
                report.labor_hours_actual,
                "labor",
                source=source,
            )
        )
        records.append(
            _record(
                report,
                "labor_hours_actual",
                report.labor_hours_actual,
                "labor",
                source=source,
            )
        )
    if report.labor_hours_scheduled is not None:
        records.append(
            _record(
                report,
                "labor_hours_scheduled",
                report.labor_hours_scheduled,
                "labor",
                source=source,
            )
        )

    total_covers = report.effective_total_covers
    if report.reservation_covers is not None:
        records.append(
            _record(
                report,
                "reservation_covers",
                report.reservation_covers,
                "demand",
                source=source,
            )
        )
    if total_covers is not None:
        room_total = report.room_total_covers
        total_dimensions: dict[str, object] = {
            "derived_from_rooms": (
                room_total is not None
                and total_covers == room_total
                and report.total_covers != total_covers
            )
        }
        records.append(
            _record(
                report,
                "guest_count",
                total_covers,
                "demand",
                source=source,
                dimensions=total_dimensions,
            )
        )
    if report.dining_room_covers is not None:
        records.append(
            _record(
                report,
                "dining_room_covers",
                report.dining_room_covers,
                "demand",
                source=source,
            )
        )
    if report.bar_atrium_covers is not None:
        records.append(
            _record(
                report,
                "bar_atrium_covers",
                report.bar_atrium_covers,
                "demand",
                source=source,
            )
        )

    total_comps = report.effective_total_comps
    if total_comps is not None:
        records.append(
            _record(
                report,
                "comps",
                total_comps,
                "hospitality",
                source=source,
            )
        )
    for line in report.comps:
        records.append(
            _record(
                report,
                "comp_amount",
                line.amount,
                "hospitality",
                source=source,
                dimensions={"comp_category": line.category, "count": line.count},
            )
        )

    if report.voids is not None:
        records.append(
            _record(
                report,
                "voids",
                report.voids,
                "controls",
                source=source,
                dimensions={"count": report.void_count},
            )
        )

    for feature in report.feature_sales:
        records.append(
            _record(
                report,
                "feature_sales",
                feature.sales,
                "product_mix",
                source=source,
                dimensions={"item": feature.item, "quantity": feature.quantity},
            )
        )
        if feature.quantity is not None:
            records.append(
                _record(
                    report,
                    "feature_quantity",
                    feature.quantity,
                    "product_mix",
                    source=source,
                    dimensions={"item": feature.item},
                )
            )

    return records
