from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from restaurantos.nightly_schedule import aligned_month_windows

_DEFAULT_TIMEZONE = "America/Chicago"
_DEFAULT_RESTAURANT = "Fonda San Miguel"
# The briefings step waits for its refresh lock; a stuck holder must not hold
# the nightly unit until systemd's start timeout fails it. Ten minutes leaves
# room to wait behind a slow manual refresh that holds the lock.
BRIEFINGS_TIMEOUT_SECONDS = 600


def _required_file(path: Path, description: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing {description}: {path}")


def _refresh_briefings(command: list[str]) -> None:
    """Run the optional briefings step; report a failure on one stderr line.

    By now the ledger refresh and operating brief have succeeded, so nothing
    this step does (a non-zero exit, a missing interpreter, anything raised)
    may mark the nightly unit as failed. The step is killed after
    ``BRIEFINGS_TIMEOUT_SECONDS``, and a timeout is reported the same way.
    """
    try:
        subprocess.run(command, check=True, timeout=BRIEFINGS_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as error:
        problem = f"exited with status {error.returncode}"
    except subprocess.TimeoutExpired as error:
        problem = f"timed out after {error.timeout:g} seconds"
    except Exception as error:  # optional step: never fatal
        problem = f"raised {type(error).__name__}: {error}"
    else:
        return
    problem = " ".join(problem.split())
    print(
        f"restaurantos_nightly: the briefings-refresh step {problem}; the ledger "
        "refresh succeeded, so the nightly run still succeeds (the phone feed "
        "keeps its previous briefings until the next run)",
        file=sys.stderr,
    )


def main() -> int:
    timezone_name = os.environ.get("ATLAS_TIMEZONE", _DEFAULT_TIMEZONE)
    restaurant = os.environ.get("ATLAS_RESTAURANT", _DEFAULT_RESTAURANT)
    lookback_days = int(os.environ.get("ATLAS_GMAIL_LOOKBACK_DAYS", "2"))

    data_root = Path(
        os.environ.get("ATLAS_DATA_ROOT", str(Path.home() / "atlas-data"))
    ).expanduser()
    restaurant_root = data_root / "restaurantos" / "fonda"
    credentials = data_root / "google" / "gmail-token.json"
    messages = restaurant_root / "nightly-messages.jsonl"
    state = restaurant_root / "nightly-sync-state.json"
    history = restaurant_root / "nightly-history.jsonl"
    manifest = restaurant_root / "nightly-manifest.json"
    brief = restaurant_root / "operating-brief.md"
    overrides = restaurant_root / "service-date-overrides.json"
    approved_imports = restaurant_root / "toast-approved"
    goals = restaurant_root / "goals.json"
    briefings = restaurant_root / "briefings.json"

    _required_file(credentials, "Gmail OAuth credentials")
    _required_file(messages, "private nightly message bundle")
    restaurant_root.mkdir(parents=True, exist_ok=True)

    local_today = datetime.now(ZoneInfo(timezone_name)).date()
    service_end = local_today - timedelta(days=1)
    brief_window, compare_window = aligned_month_windows(service_end)

    command = [
        sys.executable,
        "-m",
        "restaurantos",
        "gmail-nightly-refresh",
        "--credentials",
        str(credentials),
        "--messages",
        str(messages),
        "--state",
        str(state),
        "--history",
        str(history),
        "--manifest",
        str(manifest),
        "--restaurant",
        restaurant,
        "--lookback-days",
        str(lookback_days),
        "--brief-output",
        str(brief),
        "--brief-start",
        brief_window.start_date.isoformat(),
        "--brief-end",
        brief_window.end_date.isoformat(),
        "--brief-label",
        brief_window.label or "",
        "--compare-start",
        compare_window.start_date.isoformat(),
        "--compare-end",
        compare_window.end_date.isoformat(),
        "--compare-label",
        compare_window.label or "",
    ]
    if overrides.is_file():
        command.extend(("--overrides", str(overrides)))
    if approved_imports.is_dir():
        command.extend(("--approved-imports", str(approved_imports)))
    if goals.is_file():
        command.extend(("--goals", str(goals)))

    print(f"scheduled_service_end={service_end.isoformat()}")
    print(
        "scheduled_brief_window="
        f"{brief_window.start_date.isoformat()}..{brief_window.end_date.isoformat()}"
    )
    print(
        "scheduled_compare_window="
        f"{compare_window.start_date.isoformat()}..{compare_window.end_date.isoformat()}"
    )
    subprocess.run(command, check=True)

    # The phone briefings feed: rebuilt from the refreshed ledger, relative
    # figures only. Runs only after a successful refresh (check=True above);
    # the peer API reads the file and never writes it. The feed is optional:
    # its failure is reported, never allowed to fail the nightly unit.
    _refresh_briefings(
        [
            sys.executable,
            "-m",
            "restaurantos",
            "briefings-refresh",
            "--history",
            str(history),
            "--manifest",
            str(manifest),
            "--briefings",
            str(briefings),
            "--entity",
            restaurant,
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
