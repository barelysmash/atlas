from datetime import date, timedelta

from restaurantos.nightly_refresh import NightlyBriefWindow


def _period_label(start: date, end: date) -> str:
    if start == end:
        return f"{start:%B} {start.day}"
    if start.year == end.year and start.month == end.month:
        return f"{start:%B} {start.day}-{end.day}"
    return f"{start:%b} {start.day}-{end:%b} {end.day}"


def aligned_month_windows(
    service_end: date,
) -> tuple[NightlyBriefWindow, NightlyBriefWindow]:
    """Build month-to-date and prior-month aligned operating brief windows."""
    current_start = service_end.replace(day=1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)

    aligned_previous_end = previous_start + timedelta(days=service_end.day - 1)
    if aligned_previous_end > previous_end:
        aligned_previous_end = previous_end

    return (
        NightlyBriefWindow(
            start_date=current_start,
            end_date=service_end,
            label=_period_label(current_start, service_end),
        ),
        NightlyBriefWindow(
            start_date=previous_start,
            end_date=aligned_previous_end,
            label=_period_label(previous_start, aligned_previous_end),
        ),
    )
