from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from restaurantos.gmail_mailbox import (
    GmailApiMailbox,
    GmailOAuthCredentials,
    GmailOAuthTokenProvider,
)
from restaurantos.nightly_mailbox import (
    NightlyMailboxSyncResult,
    sync_nightly_mailbox,
)
from restaurantos.nightly_refresh import (
    NightlyBriefWindow,
    NightlyRefreshResult,
    rebuild_nightly_history,
)

DEFAULT_GMAIL_NIGHTLY_QUERY = "{EOD SPLH} -in:trash -in:spam"


@dataclass(frozen=True, slots=True)
class GmailNightlyRefreshResult:
    sync: NightlyMailboxSyncResult
    refresh: NightlyRefreshResult


def _validate_private_paths(
    credentials_path: str | Path,
    messages_path: str | Path,
    state_path: str | Path,
    history_path: str | Path,
    manifest_path: str | Path,
    overrides_path: str | Path | None,
    brief_path: str | Path | None,
) -> None:
    named_paths: list[tuple[str, Path]] = [
        ("credentials", Path(credentials_path).resolve()),
        ("messages", Path(messages_path).resolve()),
        ("state", Path(state_path).resolve()),
        ("history", Path(history_path).resolve()),
        ("manifest", Path(manifest_path).resolve()),
    ]
    if overrides_path is not None:
        named_paths.append(("overrides", Path(overrides_path).resolve()))
    if brief_path is not None:
        named_paths.append(("brief", Path(brief_path).resolve()))

    seen: dict[Path, str] = {}
    for name, path in named_paths:
        previous = seen.get(path)
        if previous is not None:
            raise ValueError(f"{previous} and {name} paths must be distinct")
        seen[path] = name


def gmail_nightly_refresh(
    credentials_path: str | Path,
    messages_path: str | Path,
    state_path: str | Path,
    history_path: str | Path,
    manifest_path: str | Path,
    *,
    restaurant: str,
    query: str = DEFAULT_GMAIL_NIGHTLY_QUERY,
    lookback_days: int = 2,
    overrides_path: str | Path | None = None,
    brief_path: str | Path | None = None,
    brief_window: NightlyBriefWindow | None = None,
    compare_window: NightlyBriefWindow | None = None,
) -> GmailNightlyRefreshResult:
    """Sync private Gmail EOD source and deterministically rebuild history."""
    if lookback_days < 0:
        raise ValueError("Gmail lookback days cannot be negative")
    _validate_private_paths(
        credentials_path,
        messages_path,
        state_path,
        history_path,
        manifest_path,
        overrides_path,
        brief_path,
    )

    credentials = GmailOAuthCredentials.from_file(credentials_path)
    mailbox = GmailApiMailbox(
        token_provider=GmailOAuthTokenProvider(credentials),
        query=query,
    )
    sync_result = sync_nightly_mailbox(
        mailbox,
        messages_path,
        state_path,
        lookback=timedelta(days=lookback_days),
    )
    refresh_result = rebuild_nightly_history(
        messages_path,
        history_path,
        manifest_path,
        restaurant=restaurant,
        overrides_path=overrides_path,
        brief_path=brief_path,
        brief_window=brief_window,
        compare_window=compare_window,
    )
    return GmailNightlyRefreshResult(sync=sync_result, refresh=refresh_result)
