import argparse
import sys
from datetime import date

# restaurantos.api (and with it http.server) is imported only by `serve`, so
# the nightly commands never load the server; the defaults live apart from it.
# Likewise restaurantos.briefings (which needs the POSIX-only fcntl to write)
# is imported only by `briefings-refresh`, so every other command also runs
# on a host without fcntl, such as a Windows development machine.
from restaurantos.api_defaults import DEFAULT_HOST, DEFAULT_PORT
from restaurantos.cli import morning_brief
from restaurantos.gmail_nightly_refresh import (
    DEFAULT_GMAIL_NIGHTLY_QUERY,
    gmail_nightly_refresh,
)
from restaurantos.nightly_refresh import (
    NightlyBriefWindow,
    NightlyRefreshResult,
    rebuild_nightly_history,
)
from restaurantos.operating_brief_runner import (
    operating_brief_from_history,
    write_operating_brief,
)
from restaurantos.toast_import_apply import approve_staged_import


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


def _add_brief_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--brief-output")
    parser.add_argument("--brief-start", type=_iso_date)
    parser.add_argument("--brief-end", type=_iso_date)
    parser.add_argument("--brief-label")
    parser.add_argument("--compare-start", type=_iso_date)
    parser.add_argument("--compare-end", type=_iso_date)
    parser.add_argument("--compare-label")


def _brief_windows(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[NightlyBriefWindow | None, NightlyBriefWindow | None]:
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
    return brief_window, compare_window


def _print_decisions(result: NightlyRefreshResult) -> None:
    """Counts only. A goals problem is reported; it never fails the refresh."""
    if result.decision_count is not None:
        print(f"decisions={result.decision_count}")
    if result.decision_error is not None:
        print(f"decisions_error={result.decision_error}")


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
    refresh_parser.add_argument("--approved-imports")
    refresh_parser.add_argument("--goals")
    _add_brief_arguments(refresh_parser)

    gmail_parser = subparsers.add_parser("gmail-nightly-refresh")
    gmail_parser.add_argument("--credentials", required=True)
    gmail_parser.add_argument("--messages", required=True)
    gmail_parser.add_argument("--state", required=True)
    gmail_parser.add_argument("--history", required=True)
    gmail_parser.add_argument("--manifest", required=True)
    gmail_parser.add_argument("--restaurant", required=True)
    gmail_parser.add_argument("--query", default=DEFAULT_GMAIL_NIGHTLY_QUERY)
    gmail_parser.add_argument("--lookback-days", type=int, default=2)
    gmail_parser.add_argument("--overrides")
    gmail_parser.add_argument("--approved-imports")
    gmail_parser.add_argument("--goals")
    _add_brief_arguments(gmail_parser)

    briefings_parser = subparsers.add_parser(
        "briefings-refresh",
        help="build or refresh the briefings file from the nightly ledger",
        description=(
            "Build one relative-only briefing per service night in the ledger. "
            "Unchanged briefings keep their updated_at; nights that left the "
            "ledger become tombstones."
        ),
    )
    briefings_parser.add_argument(
        "--history", required=True, help="the nightly ledger (JSON Lines)"
    )
    briefings_parser.add_argument(
        "--manifest",
        required=True,
        help="the nightly manifest (nights in review); may not exist yet",
    )
    briefings_parser.add_argument(
        "--briefings", required=True, help="the briefings file to write"
    )
    briefings_parser.add_argument(
        "--entity", help="the entity to brief; required if the ledger has several"
    )

    approve_parser = subparsers.add_parser(
        "toast-approve",
        help="approve one staged Toast night so the next rebuild adds it",
    )
    approve_parser.add_argument("--review-dir", required=True)
    approve_parser.add_argument("--approved-dir", required=True)
    approve_parser.add_argument("--service-date", required=True, type=_iso_date)
    approve_parser.add_argument("--sha256")
    approve_parser.add_argument("--replace", action="store_true")

    serve_parser = subparsers.add_parser(
        "serve",
        help="run the read-only peer API (token from ATLAS_API_TOKEN)",
    )
    serve_parser.add_argument("--history", required=True)
    serve_parser.add_argument("--manifest", required=True)
    serve_parser.add_argument(
        "--briefings",
        help="the briefings file to serve (read only); "
        "default briefings.json next to --history",
    )
    serve_parser.add_argument(
        "--host", help=f"default ATLAS_API_HOST or {DEFAULT_HOST}"
    )
    serve_parser.add_argument(
        "--port", type=int, help=f"default ATLAS_API_PORT or {DEFAULT_PORT}"
    )

    args = parser.parse_args()

    if args.command == "serve":
        from restaurantos.api import config_from_env, serve

        try:
            config = config_from_env(
                args.history,
                args.manifest,
                host=args.host,
                port=args.port,
                briefings_path=args.briefings,
            )
        except ValueError as error:
            parser.error(str(error))
        serve(config)
        return

    if args.command == "briefings-refresh":
        from restaurantos.briefings import PosixHostRequiredError, refresh_briefings

        try:
            result = refresh_briefings(
                args.history, args.manifest, args.briefings, entity=args.entity
            )
        except (OSError, ValueError, PosixHostRequiredError) as error:
            print(f"restaurantos briefings-refresh: {error}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"briefings={result.briefings}")
        print(f"changed={result.changed}")
        print(f"tombstones={result.tombstones}")
        print(f"path={result.path}")
        return

    if args.command == "toast-approve":
        try:
            night = approve_staged_import(
                args.review_dir,
                args.approved_dir,
                args.service_date,
                sha256=args.sha256,
                replace=args.replace,
            )
        except ValueError as error:
            parser.error(str(error))
        # Date and hash only: figures stay in the private approval file.
        print(f"approved_service_date={night.service_date.isoformat()}")
        print(f"sha256={night.sha256}")
        print("applies=net_sales,voids")
        print("next=run the nightly refresh to rebuild the ledger")
        return

    if args.command == "morning-brief":
        print(morning_brief(args.input, args.restaurant))
        return

    if args.command == "nightly-refresh":
        brief_window, compare_window = _brief_windows(args, parser)
        refresh_result = rebuild_nightly_history(
            args.messages,
            args.history,
            args.manifest,
            restaurant=args.restaurant,
            overrides_path=args.overrides,
            approved_imports_path=args.approved_imports,
            goals_path=args.goals,
            brief_path=args.brief_output,
            brief_window=brief_window,
            compare_window=compare_window,
        )
        print(f"service_nights={refresh_result.service_nights}")
        print(f"records={refresh_result.record_count}")
        print(f"reviews={refresh_result.review_count}")
        print(f"history={refresh_result.history_path}")
        print(f"manifest={refresh_result.manifest_path}")
        _print_decisions(refresh_result)
        if refresh_result.brief_path is not None:
            print(f"brief={refresh_result.brief_path}")
        return

    if args.command == "gmail-nightly-refresh":
        brief_window, compare_window = _brief_windows(args, parser)
        gmail_result = gmail_nightly_refresh(
            args.credentials,
            args.messages,
            args.state,
            args.history,
            args.manifest,
            restaurant=args.restaurant,
            query=args.query,
            lookback_days=args.lookback_days,
            overrides_path=args.overrides,
            approved_imports_path=args.approved_imports,
            goals_path=args.goals,
            brief_path=args.brief_output,
            brief_window=brief_window,
            compare_window=compare_window,
        )
        print(f"fetched_messages={gmail_result.sync.fetched_message_count}")
        print(f"new_messages={gmail_result.sync.new_message_count}")
        print(f"updated_messages={gmail_result.sync.updated_message_count}")
        print(f"bundle_messages={gmail_result.sync.bundle_message_count}")
        print(f"service_nights={gmail_result.refresh.service_nights}")
        print(f"records={gmail_result.refresh.record_count}")
        print(f"reviews={gmail_result.refresh.review_count}")
        print(f"messages={gmail_result.sync.bundle_path}")
        print(f"state={gmail_result.sync.state_path}")
        print(f"history={gmail_result.refresh.history_path}")
        print(f"manifest={gmail_result.refresh.manifest_path}")
        _print_decisions(gmail_result.refresh)
        if gmail_result.refresh.brief_path is not None:
            print(f"brief={gmail_result.refresh.brief_path}")
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
