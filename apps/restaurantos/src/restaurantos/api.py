"""RestaurantOS peer API: the surface JARVIS routes to.

A small read-only HTTP service over the private nightly ledger, registered in
JARVIS's agent registry per JAM ``standards/agent-registration.md``:

* binds to loopback by default;
* every data route requires ``Authorization: Bearer $ATLAS_API_TOKEN``; the
  briefing routes also accept the phone's ``$ATLAS_BRIEFINGS_TOKEN``, which
  opens nothing else;
* returns relative figures only (``relative_summary``), so no absolute dollar
  or cover figure leaves the host through this service;
* never writes: the nightly workload owns the ledger and the briefings file.

Standard library only, so the release venv gains no dependency.

Routes
    GET  /health                 liveness, no auth, no data
    GET  /v1/freshness           how current the ledger is
    POST /v1/operating-summary   relative comparison of two periods
    GET  /v1/decisions           Decisions against the venue's goals, relative
    GET  /v1/health              authenticated check for the phone app
    GET  /v1/briefings           change feed of nightly briefings
    GET  /v1/briefings/{id}      one briefing
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from atlas_core.operational_record import OperationalRecord

from restaurantos.api_defaults import DEFAULT_HOST as DEFAULT_HOST  # re-exported
from restaurantos.api_defaults import DEFAULT_PORT as DEFAULT_PORT  # re-exported
from restaurantos.briefings_feed import (
    BriefingsStore,
    briefing_id_from_path,
    list_page,
    parse_list_query,
    single_briefing,
)
from restaurantos.coverage import count_flagged_nights, count_partial_nights
from restaurantos.coverage import (
    read_partial_nights as read_partial_nights,  # re-exported
)
from restaurantos.coverage import read_reviews as read_reviews  # re-exported
from restaurantos.decisions import (
    DECISIONS_FILENAME,
    read_decisions_file,
    relative_decisions,
)
from restaurantos.http_errors import ApiError as ApiError  # re-exported
from restaurantos.nightly_history import read_history_jsonl
from restaurantos.nightly_schedule import aligned_month_windows
from restaurantos.operating_brief import summarize_operating_period
from restaurantos.relative_summary import (
    FIGURES_POLICY,
    preceding_window,
    relative_operating_summary,
)

logger = logging.getLogger("restaurantos.api")

SERVICE_NAME = "atlas-restaurantos"
DEFAULT_TIMEZONE = "America/Chicago"
DEFAULT_BRIEFINGS_NAME = "briefings.json"
API_VERSION = "1"
MIN_TOKEN_LENGTH = 24
MAX_BODY_BYTES = 16 * 1024
MAX_WINDOW_DAYS = 366

_SUMMARY_KEYS = {
    "start_date",
    "end_date",
    "compare_start_date",
    "compare_end_date",
    "entity",
}
# Manifest fields that are counts and dates only; anything else is not relayed.
_MANIFEST_KEYS = (
    "service_nights",
    "record_count",
    "first_service_date",
    "last_service_date",
    "skipped_message_count",
    "review_count",
    "warning_counts",
    "review_reason_counts",
    "reviews",
    "partial_nights",
)


@dataclass(frozen=True, slots=True)
class ApiConfig:
    history_path: Path
    manifest_path: Path
    token: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    timezone: str = DEFAULT_TIMEZONE
    # The briefings file the nightly workload writes; default next to the ledger.
    briefings_path: Path | None = None
    # The phone's token, accepted on the briefing routes only. None: unset.
    briefings_token: str | None = None

    def __post_init__(self) -> None:
        if len(self.token) < MIN_TOKEN_LENGTH:
            raise ValueError(
                f"ATLAS_API_TOKEN must be at least {MIN_TOKEN_LENGTH} characters"
            )
        if self.briefings_token is not None:
            # Messages name the variable, never its value.
            if len(self.briefings_token) < MIN_TOKEN_LENGTH:
                raise ValueError(
                    "ATLAS_BRIEFINGS_TOKEN must be at least "
                    f"{MIN_TOKEN_LENGTH} characters"
                )
            if hmac.compare_digest(
                self.briefings_token.encode("utf-8"), self.token.encode("utf-8")
            ):
                raise ValueError(
                    "ATLAS_BRIEFINGS_TOKEN must differ from ATLAS_API_TOKEN"
                )

    @property
    def resolved_briefings_path(self) -> Path:
        if self.briefings_path is not None:
            return self.briefings_path
        return self.history_path.parent / DEFAULT_BRIEFINGS_NAME


def config_from_env(
    history_path: str | Path,
    manifest_path: str | Path,
    *,
    host: str | None = None,
    port: int | None = None,
    briefings_path: str | Path | None = None,
) -> ApiConfig:
    """Build the service config; tokens come from the environment only.

    An empty ``ATLAS_BRIEFINGS_TOKEN`` (as in the env template) means unset.
    """
    return ApiConfig(
        history_path=Path(history_path).expanduser(),
        manifest_path=Path(manifest_path).expanduser(),
        token=os.environ.get("ATLAS_API_TOKEN", ""),
        host=host or os.environ.get("ATLAS_API_HOST", DEFAULT_HOST),
        port=port
        if port is not None
        else int(os.environ.get("ATLAS_API_PORT", str(DEFAULT_PORT))),
        timezone=os.environ.get("ATLAS_TIMEZONE", DEFAULT_TIMEZONE),
        briefings_path=Path(briefings_path).expanduser()
        if briefings_path is not None
        else None,
        briefings_token=os.environ.get("ATLAS_BRIEFINGS_TOKEN") or None,
    )


class Ledger:
    """The nightly history, re-read only when the file changes."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._records: list[OperationalRecord] = []

    def records(self) -> list[OperationalRecord]:
        try:
            stat = self._path.stat()
        except FileNotFoundError:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "ledger_unavailable",
                "The nightly ledger does not exist yet.",
            ) from None
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if stamp != self._stamp:
                self._records = read_history_jsonl(self._path)
                self._stamp = stamp
            return self._records

    def modified_at(self) -> datetime | None:
        try:
            return datetime.fromtimestamp(self._path.stat().st_mtime).astimezone()
        except FileNotFoundError:
            return None


def _service_dates(records: Iterable[OperationalRecord]) -> list[date]:
    dates: set[date] = set()
    for record in records:
        try:
            dates.add(date.fromisoformat(record.period))
        except ValueError:
            continue
    return sorted(dates)


def _parse_date(payload: dict[str, Any], key: str) -> date | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError(
            HTTPStatus.BAD_REQUEST, "invalid_request", f"{key} must be YYYY-MM-DD"
        )
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(
            HTTPStatus.BAD_REQUEST, "invalid_request", f"{key} must be YYYY-MM-DD"
        ) from None


def _pair(
    payload: dict[str, Any], start_key: str, end_key: str
) -> tuple[date, date] | None:
    start = _parse_date(payload, start_key)
    end = _parse_date(payload, end_key)
    if (start is None) != (end is None):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            f"{start_key} and {end_key} must be provided together",
        )
    if start is None or end is None:
        return None
    if end < start:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            f"{end_key} cannot be before {start_key}",
        )
    if (end - start).days >= MAX_WINDOW_DAYS:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            f"a window may span at most {MAX_WINDOW_DAYS} days",
        )
    return start, end


def _coverage(
    period: dict[str, Any],
    records: list[OperationalRecord],
    entity: str,
    reviews: dict[date, tuple[str, ...]] | None,
) -> dict[str, Any]:
    """How much of a period to trust: counts of nights, never figures.

    ``nights_missing`` are reviewed nights with nothing in the ledger (the
    report arrived but could not be read). ``nights_in_review`` are nights in
    the ledger with something flagged, usually one missing field.
    """
    start = date.fromisoformat(period["start_date"])
    end = date.fromisoformat(period["end_date"])
    nights = set(_service_dates(r for r in records if r.entity == entity))
    counts = count_flagged_nights(reviews, nights, start, end)
    if counts is None:
        return {
            "nights_in_review": None,
            "nights_missing": None,
            "review_reasons": None,
        }
    return {
        "nights_in_review": counts.in_review,
        "nights_missing": counts.missing,
        "review_reasons": counts.reasons,
    }


def operating_summary(
    records: list[OperationalRecord],
    payload: dict[str, Any],
    *,
    reviews: dict[date, tuple[str, ...]] | None = None,
    partial_nights: set[date] | None = None,
) -> dict[str, Any]:
    """Resolve the two windows and compare them, relative figures only.

    No dates: month to date through the latest service night in the ledger,
    against the aligned days of the prior month (the nightly brief's windows).
    A window without a comparison: the window of equal length just before it.
    """
    unknown = sorted(set(payload) - _SUMMARY_KEYS)
    if unknown:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_request",
            f"unknown field(s): {', '.join(unknown)}",
        )
    entity = payload.get("entity")
    if entity is not None and not isinstance(entity, str):
        raise ApiError(
            HTTPStatus.BAD_REQUEST, "invalid_request", "entity must be a string"
        )

    window = _pair(payload, "start_date", "end_date")
    compare = _pair(payload, "compare_start_date", "compare_end_date")
    current_label: str | None = None
    compare_label: str | None = None

    if window is None:
        if compare is not None:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid_request",
                "a comparison window requires start_date and end_date",
            )
        dates = _service_dates(records)
        if not dates:
            raise ApiError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "no_data",
                "The nightly ledger has no service nights.",
            )
        brief_window, compare_window = aligned_month_windows(dates[-1])
        window = (brief_window.start_date, brief_window.end_date)
        compare = (compare_window.start_date, compare_window.end_date)
        current_label = brief_window.label
        compare_label = compare_window.label
    elif compare is None:
        compare = preceding_window(*window)

    try:
        current = summarize_operating_period(
            records, window[0], window[1], entity=entity, label=current_label
        )
    except ValueError as error:
        raise ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "unprocessable_period",
            f"current period: {error}",
        ) from None
    try:
        previous = summarize_operating_period(
            records,
            compare[0],
            compare[1],
            entity=current.entity,
            label=compare_label,
        )
    except ValueError as error:
        raise ApiError(
            HTTPStatus.UNPROCESSABLE_ENTITY,
            "unprocessable_period",
            f"comparison period: {error}",
        ) from None

    summary = relative_operating_summary(current, previous)
    for name in ("current", "previous"):
        summary[name].update(_coverage(summary[name], records, current.entity, reviews))
        summary[name]["nights_partial"] = count_partial_nights(
            partial_nights,
            date.fromisoformat(summary[name]["start_date"]),
            date.fromisoformat(summary[name]["end_date"]),
        )
    summary["notes"].append(
        "nights_missing counts nights whose report arrived but could not be "
        "read, so they are absent from the comparison. nights_in_review "
        "counts nights that are included but have a field flagged. "
        "nights_partial counts nights filled from a point-of-sale summary: "
        "they add to net sales and voids only, and are left out of every "
        "labor, cover, reservation and comp figure. null means unknown."
    )
    return summary


def freshness(ledger: Ledger, manifest_path: Path, *, today: date) -> dict[str, Any]:
    """How current the ledger is: dates and counts, no operating figures."""
    dates = _service_dates(ledger.records())
    latest = dates[-1] if dates else None
    modified = ledger.modified_at()

    manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            manifest = {key: raw[key] for key in _MANIFEST_KEYS if key in raw}

    return {
        "figures": FIGURES_POLICY,
        "as_of": today.isoformat(),
        "first_service_date": dates[0].isoformat() if dates else None,
        "last_service_date": latest.isoformat() if latest else None,
        "days_since_last_service": (today - latest).days if latest else None,
        "service_nights_in_ledger": len(dates),
        "ledger_modified_at": modified.isoformat(timespec="seconds")
        if modified
        else None,
        "manifest": manifest,
    }


class _Handler(BaseHTTPRequestHandler):
    server_version = "AtlasRestaurantOS/1"
    protocol_version = "HTTP/1.1"

    # Set per server by make_server().
    config: ApiConfig
    ledger: Ledger
    briefings: BriefingsStore

    def log_message(self, format: str, *args: Any) -> None:
        # Request line and status only; never a body, never the token.
        logger.info("%s %s", self.address_string(), format % args)

    def _send(
        self,
        status: HTTPStatus,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        encoded = json.dumps(body, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self, *, briefing_route: bool = False) -> bool:
        """The service token opens every route; the phone token only briefings.

        Both comparisons run in constant time, and both always run on a
        briefing route, so timing does not tell which token matched.
        """
        header = self.headers.get("Authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        offered = presented.strip().encode("utf-8")
        allowed = hmac.compare_digest(offered, self.config.token.encode("utf-8"))
        phone = self.config.briefings_token
        if briefing_route and phone is not None:
            allowed = hmac.compare_digest(offered, phone.encode("utf-8")) | allowed
        return allowed

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            # The body is left unread, so the connection cannot be reused.
            self.close_connection = True
            raise ApiError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "invalid_request",
                "request body is missing a valid length or is too large",
            )
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_request", "body must be JSON"
            ) from None
        if not isinstance(payload, dict):
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_request", "body must be an object"
            )
        return payload

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self.config.timezone)).date()

    def _briefing_route(self, method: str, path: str, query: str) -> dict[str, Any]:
        """GET /v1/health, /v1/briefings and /v1/briefings/{id}."""
        if method != "GET":
            self.close_connection = True
            raise ApiError(
                HTTPStatus.METHOD_NOT_ALLOWED,
                "method_not_allowed",
                "Only GET is allowed on this route.",
                headers={"Allow": "GET"},
            )
        if path == "/v1/health":
            return {
                "api_version": API_VERSION,
                "figures": FIGURES_POLICY,
                "name": SERVICE_NAME,
                "ok": True,
            }
        if path == "/v1/briefings":
            listing = parse_list_query(query)
            return list_page(self.briefings.snapshot(), listing)
        ident = briefing_id_from_path(path.removeprefix("/v1/briefings/"))
        return single_briefing(self.briefings.snapshot(), ident)

    def _dispatch(self, method: str) -> None:
        request_id = uuid4().hex
        raw_path, _, query = self.path.partition("?")
        path = raw_path.rstrip("/") or "/"
        try:
            if path == "/health" and method == "GET":
                self._send(
                    HTTPStatus.OK,
                    {"status": "ok", "service": SERVICE_NAME},
                )
                return
            briefing_route = _is_briefing_route(path)
            if not self._authorized(briefing_route=briefing_route):
                # Drain nothing and say nothing about which routes exist.
                self.close_connection = True
                raise ApiError(
                    HTTPStatus.UNAUTHORIZED,
                    "unauthorized",
                    "A valid bearer token is required.",
                )
            if briefing_route:
                data = self._briefing_route(method, path, query)
            elif path == "/v1/freshness" and method == "GET":
                data = freshness(
                    self.ledger, self.config.manifest_path, today=self._today()
                )
            elif path == "/v1/decisions" and method == "GET":
                data = relative_decisions(
                    read_decisions_file(
                        self.config.history_path.parent / DECISIONS_FILENAME
                    ),
                    today=self._today(),
                )
            elif path == "/v1/operating-summary" and method == "POST":
                data = operating_summary(
                    self.ledger.records(),
                    self._body(),
                    reviews=read_reviews(self.config.manifest_path),
                    partial_nights=read_partial_nights(self.config.manifest_path),
                )
            else:
                self.close_connection = True
                raise ApiError(HTTPStatus.NOT_FOUND, "not_found", "No such route.")
        except ApiError as error:
            self._send(
                error.status,
                {
                    "request_id": request_id,
                    "error": {"code": error.code, "message": error.message},
                },
                error.headers,
            )
            return
        except Exception:
            # The detail goes to the journal; the caller gets no ledger content.
            logger.exception("request %s failed", request_id)
            self.close_connection = True
            self._send(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "request_id": request_id,
                    "error": {
                        "code": "internal_error",
                        "message": "Atlas could not complete the request.",
                    },
                },
            )
            return
        self._send(HTTPStatus.OK, {"request_id": request_id, "data": data})

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")


def _is_briefing_route(path: str) -> bool:
    """The routes the phone token may open (matched before any decoding)."""
    if path in ("/v1/health", "/v1/briefings"):
        return True
    segment = path.removeprefix("/v1/briefings/")
    return segment != path and segment != "" and "/" not in segment


def make_server(config: ApiConfig) -> ThreadingHTTPServer:
    """Build the server (not yet serving). Port 0 picks a free port."""
    handler = type(
        "RestaurantOSHandler",
        (_Handler,),
        {
            "config": config,
            "ledger": Ledger(config.history_path),
            "briefings": BriefingsStore(config.resolved_briefings_path),
        },
    )
    server = ThreadingHTTPServer((config.host, config.port), handler)
    server.daemon_threads = True
    return server


def serve(config: ApiConfig) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    server = make_server(config)
    host, port = server.server_address[:2]
    logger.info("%s listening on %s:%s", SERVICE_NAME, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
