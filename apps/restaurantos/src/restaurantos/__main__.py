import argparse
from datetime import date

from restaurantos.cli import morning_brief
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

    args = parser.parse_args()

    if args.command == "morning-brief":
        print(morning_brief(args.input, args.restaurant))
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
