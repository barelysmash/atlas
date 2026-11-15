"""Manually stage Toast Gmail attachments for review; no ledger modifications."""
import argparse
import json
from pathlib import Path

from restaurantos.gmail_mailbox import (
    GmailApiMailbox, GmailOAuthCredentials, GmailOAuthTokenProvider,
)
from restaurantos.toast_email_intake import stage_toast_gmail_imports


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--query",
        default="label:Atlas/Imports has:attachment -in:trash -in:spam",
    )
    args = parser.parse_args()
    provider = GmailOAuthTokenProvider(
        GmailOAuthCredentials.from_file(args.credentials)
    )
    mailbox = GmailApiMailbox(token_provider=provider, query=args.query)
    results = stage_toast_gmail_imports(
        mailbox, args.output_dir, query=args.query,
    )
    print(json.dumps(results, indent=2, sort_keys=True))
    return 1 if any(item["status"] not in ("pending_review",) for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
