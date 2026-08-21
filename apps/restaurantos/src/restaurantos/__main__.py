import argparse
from datetime import date

from restaurantos.cli import morning_brief
from restaurantos.nightly_refresh import NightlyBriefWindow, rebuild_nightly_history
from restaurantos.operating_brief_runner import (
    operating_brief_from_history,
    write_operating_brief,
)


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected ISO date YYYY-MM-DD, got {value!r}"
        ) from error


def _window(
    start: date | None,
    end: date | None,
    label: str | None,
    *,
    name: str,
) -> NightlyBriefWindow | None:
    if (start is None) != (end is None):
        raise ValueError(f"{name} start and end dates must be provided together")
    if start is None or end is None:
        return None
    return NightlyBriefWindow(start_date=start, end_date=end, label=label)


def main() -> None:
    parser = argparse.ArgumentParser(prog="restaurantos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    brief_parser = subparsers.add_parser("morning-brief")
    brief_parser.add_argument("--input", required=True)
    brief_parser.add_argument("--restaurant", required=True)

    operating_parser = subparsers.add_parser("operating-brief")
    operating_parser.add_argument("--history", required=True)
    operating_parser.add_argument("--start", required=True, type=_iso_date)
    operating_parser.add_argument("--end", required=True, type=_iso_date)
    operating_parser.add_argument("--entity")
    operating_parser.add_argument("--label")
    operating_parser.add_argument("--compare-start", type=_iso_date)
    operating_parser.add_argument("--compare-end", type=_iso_date)
    operating_parser.add_argument("--compare-label")
    operating_parser.add_argument("--output")

    refresh_parser = subparsers.add_parser("nightly-refresh")
    refresh_parser.add_argument("--messages", required=True)
    refresh_parser.add_argument("--history", required=True)
    refresh_parser.add_argument("--manifest", required=True)
    refresh_parser.add_argument("--restaurant", required=True)
    refresh_parser.add_argument("--overrides")
    refresh_parser.add_argument("--brief-output")
    refresh_parser.add_argument("--brief-start", type=_iso_date)
    refresh_parser.add_argument("--brief-end", type=_iso_date)
    refresh_parser.add_argument("--brief-label")
    refresh_parser.add_argument("--compare-start", type=_iso_date)
    refresh_parser.add_argument("--compare-end", type=_iso_date)
    refresh_parser.add_argument("--compare-label")

    args = parser.parse_args()

    if args.command == "morning-brief":
        print(morning_brief(args.input, args.restaurant))
        return

    if args.command == "nightly-refresh":
        try:
            brief_window = _window(
                args.brief_start,
                args.brief_end,
                args.brief_label,
                name="brief",
            )
            compare_window = _window(
                args.compare_start,
                args.compare_end,
                args.compare_label,
                name="comparison",
            )
        except ValueError as error:
            parser.error(str(error))

        result = rebuild_nightly_history(
            args.messages,
            args.history,
            args.manifest,
            restaurant=args.restaurant,
            overrides_path=args.overrides,
            brief_path=args.brief_output,
            brief_window=brief_window,
            compare_window=compare_window,
        )
        print(f"service_nights={result.service_nights}")
        print(f"records={result.record_count}")
        print(f"reviews={result.review_count}")
        print(f"history={result.history_path}")
        print(f"manifest={result.manifest_path}")
        if result.brief_path is not None:
            print(f"brief={result.brief_path}")
        return

    brief = operating_brief_from_history(
        args.history,
        args.start,
        args.end,
        entity=args.entity,
        label=args.label,
        compare_start_date=args.compare_start,
        compare_end_date=args.compare_end,
        compare_label=args.compare_label,
    )
    if args.output:
        print(write_operating_brief(args.output, brief))
        return

    print(brief, end="")


if __name__ == "__main__":
    main()
