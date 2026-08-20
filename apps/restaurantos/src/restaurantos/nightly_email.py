import re
from datetime import date

from restaurantos.nightly import CompLine, FeatureSale, NightlyReport

_NUMBER = r"([0-9][0-9,]*(?:\.\d+)?)"


def _float(value: str) -> float:
    return float(value.replace(",", ""))


def _int(value: str) -> int:
    return int(float(value.replace(",", "")))


def _first_money(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        match = re.search(
            rf"{label}\s*:\s*\$?\s*(-|[0-9][0-9,]*(?:\.\d+)?)",
            text,
            re.IGNORECASE,
        )
        if match:
            value = match.group(1)
            return 0.0 if value == "-" else _float(value)
    return None


def _first_number(text: str, labels: tuple[str, ...]) -> int | None:
    for label in labels:
        match = re.search(
            rf"{label}\s*:\s*\$?\s*{_NUMBER}",
            text,
            re.IGNORECASE,
        )
        if match:
            return _int(match.group(1))
    return None


def _money_count(text: str, labels: tuple[str, ...]) -> int | None:
    for label in labels:
        match = re.search(
            (
                rf"{label}\s*:\s*\$?\s*"
                r"(?:-|[0-9][0-9,]*(?:\.\d+)?)\s*\((\d+)\)"
            ),
            text,
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1))
    return None


def _narrative_total(text: str) -> int | None:
    patterns = (
        r"finished seating\s+(\d+)\s+guests",
        r"finished with\s+(\d+)\s+covers",
        r"finishing the day with\s+(\d+)\s+covers",
        r"ended the night seating\s+(\d+)\s+in total",
        r"ended the evening with\s+(\d+)\s+seated",
        r"ended the night with\s+(\d+)\s+(?:covers|guests)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))
    return None


def _structured_total(text: str) -> int | None:
    match = re.search(
        rf"\bTotal\s*:?\s*\$?\s*{_NUMBER}",
        text,
        re.IGNORECASE,
    )
    return _int(match.group(1)) if match else None


def _comp_section(text: str) -> str:
    heading = re.search(r"Comps and Voids\s*:?", text, re.IGNORECASE)
    if heading:
        tail = text[heading.end() :]
        stop = re.search(
            (
                r"\n(?:Best,|Features Sold|Feature Sales|"
                r"Sales and Labor|Covers)\b"
            ),
            tail,
            re.IGNORECASE,
        )
        return tail[: stop.start()] if stop else tail

    total = re.search(r"Total Comps\s*:", text, re.IGNORECASE)
    if total:
        tail = text[total.start() :]
        voids = re.search(r"Total Voids\s*:[^\n]*", tail, re.IGNORECASE)
        return tail[: voids.end()] if voids else tail

    return text


def _comp_lines(text: str) -> tuple[CompLine, ...]:
    reserved = {
        "net sales",
        "splh",
        "labor",
        "labor actual",
        "labor projected",
        "labor scheduled",
        "hours",
        "horas",
        "hours actual",
        "horas actual",
        "hours projected",
        "horas projected",
        "hours scheduled",
        "horas scheduled",
        "reservations",
        "starting reservations",
        "dining room",
        "dining room eod covers",
        "bar atrium",
        "atrium bar",
        "total",
        "total comps",
        "total voids",
        "voids",
    }
    section = _comp_section(text)
    lines: list[CompLine] = []
    pattern = re.compile(
        r"(?P<label>[A-Za-z][A-Za-z /&'-]{1,36}?)\s*:\s*\$\s*"
        r"(?P<amount>[0-9][0-9,]*(?:\.\d+)?)"
        r"(?:\s*\((?P<count>\d+)\))?",
        re.IGNORECASE,
    )
    for match in pattern.finditer(section):
        label = " ".join(match.group("label").split()).strip()
        normalized = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
        if normalized in reserved or normalized.startswith("total "):
            continue
        count = match.group("count")
        lines.append(
            CompLine(
                category=label,
                amount=_float(match.group("amount")),
                count=int(count) if count else None,
            )
        )
    return tuple(lines)


def _feature_sales(text: str) -> tuple[FeatureSale, ...]:
    heading = re.search(
        r"(?:Feature Sales|Features Sold)\s*:?",
        text,
        re.IGNORECASE,
    )
    if not heading:
        return ()

    tail = text[heading.end() :]
    stop = re.search(
        r"\n(?:Comps and Voids|Best,|Net Sales:|Sales and Labor|Covers)\b",
        tail,
        re.IGNORECASE,
    )
    section = tail[: stop.start()] if stop else tail

    features: list[FeatureSale] = []
    for line in section.splitlines():
        match = re.match(
            r"\s*[*-]?\s*(?P<item>[^:$]+?)\s*:\s*\$\s*"
            r"(?P<sales>[0-9][0-9,]*(?:\.\d+)?)\s*"
            r"(?:\((?P<quantity>\d+)\))?\s*$",
            line,
        )
        if match:
            quantity = match.group("quantity")
            features.append(
                FeatureSale(
                    item=" ".join(match.group("item").split()),
                    sales=_float(match.group("sales")),
                    quantity=int(quantity) if quantity else None,
                )
            )
    return tuple(features)


def parse_nightly_email(
    body: str,
    *,
    service_date: date,
    restaurant: str = "Fonda San Miguel",
    source_message_id: str | None = None,
) -> NightlyReport:
    """Parse a semi-structured Fonda EOD email into the nightly domain model."""
    labor_actual = _first_money(body, (r"Labor\s*\(actual\)",))
    if labor_actual is None:
        labor_actual = _first_money(body, (r"Labor",))

    hours_actual = _first_money(body, (r"(?:Hours|Horas)\s*\(actual\)",))
    if hours_actual is None:
        hours_actual = _first_money(body, (r"(?:Hours|Horas)",))

    return NightlyReport(
        restaurant=restaurant,
        service_date=service_date,
        net_sales=_first_money(body, (r"Net Sales",)),
        reported_splh=_first_money(body, (r"SPLH",)),
        labor_cost_actual=labor_actual,
        labor_cost_scheduled=_first_money(
            body,
            (r"Labor\s*\(scheduled\)", r"Labor\s*\(projected\)"),
        ),
        labor_hours_actual=hours_actual,
        labor_hours_scheduled=_first_money(
            body,
            (
                r"(?:Hours|Horas)\s*\(scheduled\)",
                r"(?:Hours|Horas)\s*\(projected\)",
            ),
        ),
        reservation_covers=_first_number(
            body,
            (r"Starting Reservations", r"Reservations"),
        ),
        dining_room_covers=_first_number(
            body,
            (r"Dining Room EOD Covers", r"Dining Room"),
        ),
        bar_atrium_covers=_first_number(
            body,
            (r"Bar\s*/\s*Atrium", r"Atrium\s*/\s*Bar"),
        ),
        total_covers=_structured_total(body),
        narrative_total_covers=_narrative_total(body),
        comps=_comp_lines(body),
        reported_total_comps=_first_money(body, (r"Total Comps",)),
        voids=_first_money(body, (r"Total Voids", r"Voids")),
        void_count=_money_count(body, (r"Total Voids", r"Voids")),
        feature_sales=_feature_sales(body),
        source_message_id=source_message_id,
    )
