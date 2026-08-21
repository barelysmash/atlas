import re
from dataclasses import dataclass, replace
from datetime import date, datetime

from restaurantos.nightly import NightlyReport
from restaurantos.nightly_email import parse_nightly_email

_SUBJECT_DATE = re.compile(
    r"(?<!\d)(?P<month>\d{1,2})[./-](?P<day>\d{1,2})"
    r"(?:[./-](?P<year>\d{2,4}))?(?!\d)"
)
_QUOTED_REPLY = re.compile(
    r"^On .*?wrote:\s*$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_FORWARDED = re.compile(
    r"^-{2,}\s*Forwarded message\s*-{2,}\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_OPERATIONAL_LABEL = re.compile(
    r"\b(?:SPLH|Labor|Hours|Horas|Reservations|Starting|Dining Room|"
    r"Bar\s*/\s*Atrium|Atrium\s*/\s*Bar|Total|Net Sales|Comps?|Voids?)\s*:",
    re.IGNORECASE,
)
_COMPACT_COVERS = re.compile(
    r"\bStarting\s*:\s*(?P<starting>\d+)\b.*?"
    r"\bEnd\s*:\s*(?P<end>\d+)\b.*?"
    r"\bAtrium\s*:\s*(?P<atrium>\d+)\b",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class NightlyEmailMessage:
    message_id: str
    subject: str
    body: str
    sent_at: datetime

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise ValueError("message_id is required")
        if not self.subject.strip():
            raise ValueError("subject is required")


@dataclass(frozen=True, slots=True)
class BackfillEntry:
    report: NightlyReport
    source_message_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BackfillReview:
    service_date: date | None
    source_message_ids: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BackfillResult:
    entries: tuple[BackfillEntry, ...]
    skipped_message_ids: tuple[str, ...]
    review: tuple[BackfillReview, ...]


@dataclass(frozen=True, slots=True)
class _DatedMessage:
    message: NightlyEmailMessage
    service_date: date
    warnings: tuple[str, ...]


def _expand_year(raw_year: str) -> int:
    year = int(raw_year)
    return 2000 + year if year < 100 else year


def _subject_date(subject: str, sent_at: datetime) -> date | None:
    matches = tuple(_SUBJECT_DATE.finditer(subject))
    if not matches:
        return None

    match = matches[-1]
    month = int(match.group("month"))
    day = int(match.group("day"))
    raw_year = match.group("year")

    if raw_year:
        year = _expand_year(raw_year)
        try:
            return date(year, month, day)
        except ValueError:
            return None

    candidates: list[date] = []
    for year in (sent_at.year - 1, sent_at.year, sent_at.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    if not candidates:
        return None
    return min(candidates, key=lambda value: abs((value - sent_at.date()).days))


def infer_service_date(
    subject: str,
    sent_at: datetime,
    *,
    max_subject_drift_days: int = 2,
) -> tuple[date, tuple[str, ...]]:
    """Resolve a service date while flagging implausible subject dates."""
    subject_date = _subject_date(subject, sent_at)
    if subject_date is None:
        return sent_at.date(), ("subject_date_missing",)

    drift = abs((subject_date - sent_at.date()).days)
    if drift <= max_subject_drift_days:
        return subject_date, ()

    return sent_at.date(), ("subject_sent_date_mismatch",)


def _reply_head(body: str) -> str:
    quoted = _QUOTED_REPLY.search(body)
    boundaries = [quoted.start()] if quoted else []
    forwarded = _FORWARDED.search(body)
    if forwarded:
        boundaries.append(forwarded.start())
    if not boundaries:
        return body
    return body[: min(boundaries)]


def _is_reply(subject: str) -> bool:
    return bool(re.match(r"\s*re\s*:", subject, re.IGNORECASE))


def _is_forward(subject: str) -> bool:
    return bool(re.match(r"\s*fwd?\s*:", subject, re.IGNORECASE))


def _looks_like_reaction(text: str) -> bool:
    lowered = text.lower()
    return "reacted via gmail" in lowered and not _OPERATIONAL_LABEL.search(text)


def _has_amendment_data(message: NightlyEmailMessage) -> bool:
    head = _reply_head(message.body)
    return bool(_OPERATIONAL_LABEL.search(head) or _COMPACT_COVERS.search(head))


def _parse_primary(message: _DatedMessage, restaurant: str) -> NightlyReport:
    return parse_nightly_email(
        message.message.body,
        service_date=message.service_date,
        restaurant=restaurant,
        source_message_id=message.message.message_id,
    )


def _merge_report(base: NightlyReport, amendment: NightlyReport) -> NightlyReport:
    return replace(
        base,
        net_sales=(amendment.net_sales if amendment.net_sales is not None else base.net_sales),
        reported_splh=(
            amendment.reported_splh
            if amendment.reported_splh is not None
            else base.reported_splh
        ),
        labor_cost_actual=(
            amendment.labor_cost_actual
            if amendment.labor_cost_actual is not None
            else base.labor_cost_actual
        ),
        labor_cost_scheduled=(
            amendment.labor_cost_scheduled
            if amendment.labor_cost_scheduled is not None
            else base.labor_cost_scheduled
        ),
        labor_hours_actual=(
            amendment.labor_hours_actual
            if amendment.labor_hours_actual is not None
            else base.labor_hours_actual
        ),
        labor_hours_scheduled=(
            amendment.labor_hours_scheduled
            if amendment.labor_hours_scheduled is not None
            else base.labor_hours_scheduled
        ),
        reservation_covers=(
            amendment.reservation_covers
            if amendment.reservation_covers is not None
            else base.reservation_covers
        ),
        dining_room_covers=(
            amendment.dining_room_covers
            if amendment.dining_room_covers is not None
            else base.dining_room_covers
        ),
        bar_atrium_covers=(
            amendment.bar_atrium_covers
            if amendment.bar_atrium_covers is not None
            else base.bar_atrium_covers
        ),
        total_covers=(
            amendment.total_covers
            if amendment.total_covers is not None
            else base.total_covers
        ),
        narrative_total_covers=(
            amendment.narrative_total_covers
            if amendment.narrative_total_covers is not None
            else base.narrative_total_covers
        ),
        reported_total_comps=(
            amendment.reported_total_comps
            if amendment.reported_total_comps is not None
            else base.reported_total_comps
        ),
        voids=amendment.voids if amendment.voids is not None else base.voids,
        void_count=(
            amendment.void_count if amendment.void_count is not None else base.void_count
        ),
        comps=amendment.comps if amendment.comps else base.comps,
        feature_sales=(
            amendment.feature_sales if amendment.feature_sales else base.feature_sales
        ),
    )


def _apply_compact_cover_amendment(
    report: NightlyReport,
    text: str,
) -> NightlyReport:
    match = _COMPACT_COVERS.search(text)
    if not match:
        return report

    dining_room = int(match.group("end"))
    bar_atrium = int(match.group("atrium"))
    return replace(
        report,
        reservation_covers=int(match.group("starting")),
        dining_room_covers=dining_room,
        bar_atrium_covers=bar_atrium,
        total_covers=dining_room + bar_atrium,
    )


def _apply_amendment(
    base: NightlyReport,
    message: NightlyEmailMessage,
    restaurant: str,
) -> NightlyReport:
    head = _reply_head(message.body)
    amendment = parse_nightly_email(
        head,
        service_date=base.service_date,
        restaurant=restaurant,
        source_message_id=message.message_id,
    )
    merged = _merge_report(base, amendment)
    return _apply_compact_cover_amendment(merged, head)


def _repair_obvious_labor_swap(report: NightlyReport) -> tuple[NightlyReport, bool]:
    labor_cost = report.labor_cost_actual
    labor_hours = report.labor_hours_actual
    if labor_cost is None or labor_hours is None:
        return report, False
    if labor_cost >= 1000 or labor_hours <= 1000:
        return report, False

    return (
        replace(
            report,
            labor_cost_actual=labor_hours,
            labor_hours_actual=labor_cost,
        ),
        True,
    )


def _candidate_priority(message: NightlyEmailMessage) -> tuple[int, datetime]:
    if _is_reply(message.subject):
        return (0, message.sent_at)
    if _is_forward(message.subject):
        return (1, message.sent_at)
    return (2, message.sent_at)


def backfill_nightly_emails(
    messages: list[NightlyEmailMessage] | tuple[NightlyEmailMessage, ...],
    *,
    restaurant: str = "Fonda San Miguel",
) -> BackfillResult:
    """Reconcile EOD messages into one normalized report per service date."""
    groups: dict[date, list[_DatedMessage]] = {}
    skipped: list[str] = []
    reviews: list[BackfillReview] = []

    for message in messages:
        if _looks_like_reaction(_reply_head(message.body)):
            skipped.append(message.message_id)
            continue

        service_date, date_warnings = infer_service_date(message.subject, message.sent_at)
        groups.setdefault(service_date, []).append(
            _DatedMessage(
                message=message,
                service_date=service_date,
                warnings=date_warnings,
            )
        )

    entries: list[BackfillEntry] = []
    for service_date in sorted(groups):
        group = sorted(
            groups[service_date],
            key=lambda item: _candidate_priority(item.message),
            reverse=True,
        )
        primaries = [item for item in group if not _is_reply(item.message.subject)]
        if not primaries:
            reviews.append(
                BackfillReview(
                    service_date=service_date,
                    source_message_ids=tuple(item.message.message_id for item in group),
                    reasons=("missing_primary_report",),
                )
            )
            skipped.extend(item.message.message_id for item in group)
            continue

        direct_primaries = [
            item for item in primaries if not _is_forward(item.message.subject)
        ]
        primary = direct_primaries[0] if direct_primaries else primaries[0]
        entry_warnings: list[str] = list(primary.warnings)

        if len(direct_primaries) > 1:
            entry_warnings.append("multiple_primary_reports")
            reviews.append(
                BackfillReview(
                    service_date=service_date,
                    source_message_ids=tuple(
                        item.message.message_id for item in direct_primaries
                    ),
                    reasons=("multiple_primary_reports",),
                )
            )

        try:
            report = _parse_primary(primary, restaurant)
        except ValueError:
            reviews.append(
                BackfillReview(
                    service_date=service_date,
                    source_message_ids=(primary.message.message_id,),
                    reasons=("primary_parse_failed",),
                )
            )
            skipped.extend(item.message.message_id for item in group)
            continue

        source_ids = [primary.message.message_id]
        for item in sorted(group, key=lambda value: value.message.sent_at):
            message = item.message
            if message.message_id == primary.message.message_id:
                continue
            if _is_reply(message.subject) and _has_amendment_data(message):
                try:
                    report = _apply_amendment(report, message, restaurant)
                except ValueError:
                    reviews.append(
                        BackfillReview(
                            service_date=service_date,
                            source_message_ids=(message.message_id,),
                            reasons=("amendment_parse_failed",),
                        )
                    )
                    skipped.append(message.message_id)
                    continue
                source_ids.append(message.message_id)
                entry_warnings.extend(item.warnings)
                entry_warnings.append("amended_from_reply")
            else:
                skipped.append(message.message_id)

        report, labor_swapped = _repair_obvious_labor_swap(report)
        if labor_swapped:
            entry_warnings.append("labor_hours_probably_swapped")

        entries.append(
            BackfillEntry(
                report=report,
                source_message_ids=tuple(source_ids),
                warnings=tuple(dict.fromkeys(entry_warnings)),
            )
        )

    return BackfillResult(
        entries=tuple(entries),
        skipped_message_ids=tuple(dict.fromkeys(skipped)),
        review=tuple(reviews),
    )
