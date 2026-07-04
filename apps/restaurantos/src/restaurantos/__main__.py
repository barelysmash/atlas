import argparse

from restaurantos.cli import morning_brief


def main() -> None:
    parser = argparse.ArgumentParser(prog="restaurantos")
    subparsers = parser.add_subparsers(dest="command", required=True)

    brief_parser = subparsers.add_parser("morning-brief")
    brief_parser.add_argument("--input", required=True)
    brief_parser.add_argument("--restaurant", required=True)

    args = parser.parse_args()

    if args.command == "morning-brief":
        print(morning_brief(args.input, args.restaurant))


if __name__ == "__main__":
    main()