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


def _required_file(path: Path, description: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"missing {description}: {path}")


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
