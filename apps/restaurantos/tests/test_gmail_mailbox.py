import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request

import pytest
from restaurantos.gmail_mailbox import (
    GmailApiMailbox,
    GmailOAuthCredentials,
    GmailOAuthTokenProvider,
    _google_http_error,
)


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


@dataclass
class StaticTokenProvider:
    token: str = "test-access-token"

    def access_token(self) -> str:
        return self.token


def test_oauth_credentials_load_standard_authorized_user_fields(tmp_path: Path):
    path = tmp_path / "gmail-oauth.json"
    path.write_text(
        json.dumps(
            {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "refresh_token": "refresh-token",
                "token_uri": "https://oauth.example.test/token",
            }
        ),
        encoding="utf-8",
    )

    credentials = GmailOAuthCredentials.from_file(path)

    assert credentials.client_id == "client-id"
    assert credentials.client_secret == "client-secret"
    assert credentials.refresh_token == "refresh-token"
    assert credentials.token_uri == "https://oauth.example.test/token"


def test_oauth_token_provider_posts_refresh_grant():
    requests: list[Request] = []

    def request_json(request: Request):
        requests.append(request)
        return {"access_token": "fresh-token"}

    provider = GmailOAuthTokenProvider(
        GmailOAuthCredentials(
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
        ),
        request_json=request_json,
    )

    assert provider.access_token() == "fresh-token"
    assert len(requests) == 1
    request = requests[0]
    form = parse_qs((request.data or b"").decode("utf-8"))
    assert request.full_url == "https://oauth2.googleapis.com/token"
    assert form == {
        "client_id": ["client-id"],
        "client_secret": ["client-secret"],
        "refresh_token": ["refresh-token"],
        "grant_type": ["refresh_token"],
    }


def test_gmail_api_error_includes_google_status_reason_and_message():
    body = json.dumps(
        {
            "error": {
                "code": 403,
                "message": "Gmail API has not been used in project 123 before.",
                "status": "PERMISSION_DENIED",
                "errors": [{"reason": "accessNotConfigured"}],
            }
        }
    ).encode("utf-8")
    error = HTTPError(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        403,
        "Forbidden",
        hdrs=None,
        fp=BytesIO(body),
    )

    rendered = _google_http_error(error)

    assert str(rendered) == (
        "Gmail API request failed (403 PERMISSION_DENIED; accessNotConfigured): "
        "Gmail API has not been used in project 123 before."
    )


def test_gmail_mailbox_pages_search_and_extracts_plain_or_html_body():
    requests: list[Request] = []
    first_ms = str(int(datetime(2026, 8, 20, 4, 30, tzinfo=UTC).timestamp() * 1000))
    second_ms = str(int(datetime(2026, 8, 21, 4, 30, tzinfo=UTC).timestamp() * 1000))

    def request_json(request: Request):
        requests.append(request)
        parsed = urlparse(request.full_url)
        params = parse_qs(parsed.query)
        assert request.get_header("Authorization") == "Bearer test-access-token"

        if parsed.path.endswith("/users/me/messages"):
            if params.get("pageToken") == ["page-2"]:
                return {"messages": [{"id": "gmail-2"}]}
            return {
                "messages": [{"id": "gmail-1"}],
                "nextPageToken": "page-2",
            }
        if parsed.path.endswith("/users/me/messages/gmail-1"):
            return {
                "id": "gmail-1",
                "internalDate": first_ms,
                "payload": {
                    "mimeType": "multipart/alternative",
                    "headers": [{"name": "Subject", "value": "EOD 8/19/2026"}],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _encoded("SPLH: $80.00\nTotal: 400")},
                        }
                    ],
                },
            }
        if parsed.path.endswith("/users/me/messages/gmail-2"):
            return {
                "id": "gmail-2",
                "internalDate": second_ms,
                "payload": {
                    "mimeType": "text/html",
                    "headers": [{"name": "Subject", "value": "EOD 8/20/2026"}],
                    "body": {"data": _encoded("<p>SPLH: <b>$90.00</b></p>")},
                },
            }
        raise AssertionError(f"unexpected request: {request.full_url}")

    mailbox = GmailApiMailbox(
        token_provider=StaticTokenProvider(),
        query="{EOD SPLH} -in:trash -in:spam",
        request_json=request_json,
    )
    since = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)

    messages = mailbox.fetch_messages(since)

    assert [message.message_id for message in messages] == ["gmail-1", "gmail-2"]
    assert messages[0].subject == "EOD 8/19/2026"
    assert messages[0].body == "SPLH: $80.00\nTotal: 400"
    assert messages[1].body == "SPLH:\n$90.00"

    list_requests = [
        request
        for request in requests
        if urlparse(request.full_url).path.endswith("/users/me/messages")
    ]
    first_query = parse_qs(urlparse(list_requests[0].full_url).query)["q"][0]
    assert "{EOD SPLH} -in:trash -in:spam" in first_query
    assert f"after:{int(since.timestamp())}" in first_query


def test_gmail_mailbox_requires_timezone_aware_cursor():
    mailbox = GmailApiMailbox(
        token_provider=StaticTokenProvider(),
        query="EOD",
        request_json=lambda request: {},
    )

    with pytest.raises(ValueError, match="timezone offset"):
        mailbox.fetch_messages(datetime(2026, 8, 20, 4, 0))
