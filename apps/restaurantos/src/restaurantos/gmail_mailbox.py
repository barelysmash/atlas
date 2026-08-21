import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from restaurantos.nightly_backfill import NightlyEmailMessage

DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"
DEFAULT_GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"

JsonRequest = Callable[[Request], dict[str, Any]]


class AccessTokenProvider(Protocol):
    def access_token(self) -> str: ...


def _request_json(request: Request) -> dict[str, Any]:
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object from Gmail API")
    return payload


@dataclass(frozen=True, slots=True)
class GmailOAuthCredentials:
    client_id: str
    client_secret: str
    refresh_token: str
    token_uri: str = DEFAULT_TOKEN_URI

    @classmethod
    def from_file(cls, path: str | Path) -> "GmailOAuthCredentials":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Gmail OAuth credentials must be a JSON object")

        required = ("client_id", "client_secret", "refresh_token")
        values: dict[str, str] = {}
        for key in required:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Gmail OAuth credentials require {key}")
            values[key] = value

        token_uri = payload.get("token_uri", DEFAULT_TOKEN_URI)
        if not isinstance(token_uri, str) or not token_uri.startswith("https://"):
            raise ValueError("Gmail OAuth token_uri must be an HTTPS URL")

        return cls(
            client_id=values["client_id"],
            client_secret=values["client_secret"],
            refresh_token=values["refresh_token"],
            token_uri=token_uri,
        )


@dataclass(slots=True)
class GmailOAuthTokenProvider:
    credentials: GmailOAuthCredentials
    request_json: JsonRequest = _request_json

    def access_token(self) -> str:
        request = Request(
            self.credentials.token_uri,
            data=urlencode(
                {
                    "client_id": self.credentials.client_id,
                    "client_secret": self.credentials.client_secret,
                    "refresh_token": self.credentials.refresh_token,
                    "grant_type": "refresh_token",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        payload = self.request_json(request)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError(
                "Gmail OAuth refresh response did not include access_token"
            )
        return token


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return "\n".join(self.parts)


def _decode_body_data(data: object) -> str | None:
    if not isinstance(data, str) or not data:
        return None
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode(
        "utf-8",
        errors="replace",
    )


def _mime_bodies(payload: object, mime_type: str) -> list[str]:
    if not isinstance(payload, dict):
        return []

    bodies: list[str] = []
    if payload.get("mimeType") == mime_type:
        body = payload.get("body")
        if isinstance(body, dict):
            decoded = _decode_body_data(body.get("data"))
            if decoded is not None:
                bodies.append(decoded)

    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            bodies.extend(_mime_bodies(part, mime_type))
    return bodies


def _message_body(payload: object) -> str:
    plain = _mime_bodies(payload, "text/plain")
    if plain:
        return "\n".join(plain).strip()

    html_bodies = _mime_bodies(payload, "text/html")
    if not html_bodies:
        return ""

    extractor = _HTMLTextExtractor()
    extractor.feed("\n".join(html_bodies))
    return extractor.text().strip()


def _header(payload: object, name: str) -> str:
    if not isinstance(payload, dict):
        return ""
    headers = payload.get("headers")
    if not isinstance(headers, list):
        return ""
    for header in headers:
        if not isinstance(header, dict):
            continue
        header_name = header.get("name")
        value = header.get("value")
        if (
            isinstance(header_name, str)
            and header_name.casefold() == name.casefold()
            and isinstance(value, str)
        ):
            return value
    return ""


def _message_from_api(payload: dict[str, Any]) -> NightlyEmailMessage:
    message_id = payload.get("id")
    internal_date = payload.get("internalDate")
    mime_payload = payload.get("payload")
    if not isinstance(message_id, str) or not message_id:
        raise ValueError("Gmail message is missing id")
    if not isinstance(internal_date, str) or not internal_date.isdigit():
        raise ValueError(f"Gmail message {message_id!r} is missing internalDate")

    sent_at = datetime.fromtimestamp(int(internal_date) / 1000, tz=UTC)
    return NightlyEmailMessage(
        message_id=message_id,
        subject=_header(mime_payload, "Subject"),
        body=_message_body(mime_payload),
        sent_at=sent_at,
    )


@dataclass(slots=True)
class GmailApiMailbox:
    token_provider: AccessTokenProvider
    query: str
    request_json: JsonRequest = _request_json
    api_base: str = DEFAULT_GMAIL_API_BASE
    user_id: str = "me"

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("Gmail query is required")
        if not self.api_base.startswith("https://"):
            raise ValueError("Gmail API base must be an HTTPS URL")

    def _get(
        self,
        path: str,
        token: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        suffix = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{self.api_base}/{path}{suffix}",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        return self.request_json(request)

    def _search_query(self, since: datetime | None) -> str:
        query = self.query.strip()
        if since is None:
            return query
        if since.utcoffset() is None:
            raise ValueError("Gmail fetch cursor must include a timezone offset")
        return f"{query} after:{int(since.timestamp())}"

    def _message_ids(self, token: str, query: str) -> list[str]:
        message_ids: list[str] = []
        page_token: str | None = None
        while True:
            params = {"q": query, "maxResults": "500"}
            if page_token is not None:
                params["pageToken"] = page_token
            payload = self._get(
                f"users/{self.user_id}/messages",
                token,
                params,
            )
            messages = payload.get("messages", [])
            if not isinstance(messages, list):
                raise ValueError("Gmail messages.list returned invalid messages")
            for message in messages:
                if not isinstance(message, dict):
                    continue
                message_id = message.get("id")
                if isinstance(message_id, str) and message_id:
                    message_ids.append(message_id)

            raw_page_token = payload.get("nextPageToken")
            if not isinstance(raw_page_token, str) or not raw_page_token:
                break
            page_token = raw_page_token
        return message_ids

    def fetch_messages(self, since: datetime | None) -> list[NightlyEmailMessage]:
        token = self.token_provider.access_token()
        query = self._search_query(since)
        messages = [
            _message_from_api(
                self._get(
                    f"users/{self.user_id}/messages/{message_id}",
                    token,
                    {"format": "full"},
                )
            )
            for message_id in self._message_ids(token, query)
        ]
        messages.sort(key=lambda message: (message.sent_at, message.message_id))
        return messages
