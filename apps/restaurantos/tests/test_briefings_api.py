"""The briefings feed over HTTP: paging, cursors, errors, auth and privacy.

The server runs in-process (``make_server`` on port 0 in a thread), as in
``test_peer_api``. The synthetic ledger and privacy helpers come from
``test_briefings``.
"""

from __future__ import annotations

import base64
import http.client
import json
import logging
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from _posix import needs_flock
from restaurantos.api import ApiConfig, config_from_env, make_server
from restaurantos.briefings_feed import Cursor, decode_cursor, encode_cursor
from test_briefings import (
    ENTITY,
    NIGHTS,
    NOV,
    NOW,
    Workspace,
    bid,
    forbidden_numbers,
    leaks,
    prose_of,
    stray_numbers,
    synthetic_values,
    with_separators,
)

API_TOKEN = "synthetic-api-token-0123456789abcdef"
PHONE_TOKEN = "synthetic-phone-token-fedcba9876543210"
WRONG_TOKEN = "wrong-token-wrong-token-wrong"
OPAQUE_KEYS = {"request_id", "next_cursor", "id"}


class Response:
    def __init__(self, status: int, headers: dict[str, str], raw: bytes) -> None:
        self.status = status
        self.headers = headers
        self.raw = raw
        try:
            self.json: Any = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.json = None

    @property
    def code(self) -> str | None:
        error = self.json.get("error") if isinstance(self.json, dict) else None
        return error.get("code") if isinstance(error, dict) else None


class Client:
    def __init__(self, port: int) -> None:
        self.port = port
        self.responses: list[Response] = []

    def request(
        self,
        method: str,
        path: str,
        token: str | None = API_TOKEN,
        *,
        body: bytes | None = None,
        authorization: str | None = None,
    ) -> Response:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Accept": "application/json"}
        if authorization is not None:
            headers["Authorization"] = authorization
        elif token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, body=body, headers=headers)
            reply = connection.getresponse()
            response = Response(
                reply.status,
                {k.lower(): v for k, v in reply.getheaders()},
                reply.read(),
            )
        finally:
            connection.close()
        self.responses.append(response)
        return response

    def get(self, path: str, token: str | None = API_TOKEN) -> Any:
        response = self.request("GET", path, token)
        assert response.status == 200, (path, response.raw[:300])
        assert_conventions(response)
        assert set(response.json) == {"request_id", "data"}
        return response.json["data"]

    def error(
        self,
        method: str,
        path: str,
        token: str | None,
        status: int,
        code: str,
    ) -> Response:
        response = self.request(method, path, token)
        assert response.status == status, (method, path, response.raw[:300])
        assert_conventions(response)
        assert set(response.json) == {"request_id", "error"}
        assert isinstance(response.json["request_id"], str)
        assert set(response.json["error"]) == {"code", "message"}
        assert isinstance(response.json["error"]["message"], str)
        assert response.code == code, (method, path, response.json)
        return response


def assert_conventions(response: Response) -> None:
    assert response.headers.get("cache-control") == "no-store"
    assert response.headers.get("content-type") == "application/json"
    assert response.json is not None
    assert response.raw == json.dumps(response.json, sort_keys=True).encode()


@contextmanager
def serving(
    ws: Workspace,
    *,
    phone_token: str | None = PHONE_TOKEN,
    briefings: Path | None = None,
) -> Iterator[Client]:
    config = ApiConfig(
        history_path=ws.history,
        manifest_path=ws.manifest,
        token=API_TOKEN,
        port=0,
        briefings_path=briefings or ws.briefings,
        briefings_token=phone_token,
    )
    server = make_server(config)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    try:
        yield Client(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def cursor_path(cursor: str, extra: str = "") -> str:
    return f"/v1/briefings?cursor={quote(cursor, safe='')}{extra}"


def walk(
    client: Client, query: str, token: str = API_TOKEN
) -> tuple[list[dict[str, Any]], str, list[int], list[bool]]:
    """Follow has_more; return items, final cursor, page sizes, has_more flags."""
    items: list[dict[str, Any]] = []
    sizes: list[int] = []
    flags: list[bool] = []
    limit = dict(p.split("=", 1) for p in query.split("&") if p).get("limit")
    suffix = f"&limit={limit}" if limit else ""
    data = client.get(f"/v1/briefings?{query}", token)
    while True:
        assert_page(data)
        items.extend(data["items"])
        sizes.append(len(data["items"]))
        flags.append(data["has_more"])
        if not data["has_more"]:
            return items, data["next_cursor"], sizes, flags
        assert len(sizes) < 100, "walk did not terminate"
        data = client.get(cursor_path(data["next_cursor"], suffix), token)


def assert_page(data: Any) -> None:
    assert set(data) == {"figures", "has_more", "items", "next_cursor"}
    assert data["figures"] == "relative_only"
    assert isinstance(data["has_more"], bool)
    assert isinstance(data["next_cursor"], str) and data["next_cursor"]
    keys = [key(item) for item in data["items"]]
    assert keys == sorted(keys)


def key(item: dict[str, Any]) -> tuple[str, str]:
    return item["updated_at"], item["id"]


@pytest.fixture(scope="module")
def shared(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Client]:
    """A server over a built, never-mutated workspace."""
    ws = Workspace(tmp_path_factory.mktemp("feed"))
    ws.build()
    with serving(ws) as client:
        yield client


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    workspace = Workspace(tmp_path)
    workspace.build()
    return workspace


# --------------------------------------------------------------------------
# Paging


@needs_flock
def test_full_page_and_default_limit(shared: Client):
    full = shared.get("/v1/briefings?limit=100")
    assert_page(full)
    assert full["has_more"] is False
    assert sorted(i["date"] for i in full["items"]) == [n.isoformat() for n in NIGHTS]
    assert shared.get("/v1/briefings")["items"] == full["items"]  # default 50 > 41
    one = shared.get("/v1/briefings?limit=1")
    assert one["items"] == full["items"][:1] and one["has_more"] is True
    for item in full["items"]:
        assert item["deleted"] is False
        assert item["figures"] == "relative_only"
        assert "sections" not in item and "content_hash" not in item
        assert set(item) == {
            "id",
            "date",
            "title",
            "summary",
            "body_markdown",
            "tags",
            "created_at",
            "updated_at",
            "deleted",
            "figures",
        }


@needs_flock
def test_default_limit_is_50(tmp_path: Path):
    workspace = Workspace(tmp_path)
    # September added: 71 nights, so the feed exceeds the default page.
    for night in NIGHTS[:30]:
        september = night.replace(month=9)
        workspace.values[september] = dict(workspace.values[night])
    workspace.save()
    workspace.refresh()
    with serving(workspace) as client:
        page = client.get("/v1/briefings")
        assert len(page["items"]) == 50 and page["has_more"] is True
        rest = client.get(cursor_path(page["next_cursor"]))
        assert len(rest["items"]) == 21 and rest["has_more"] is False


@needs_flock
def test_small_pages_walk_the_whole_feed_in_order(shared: Client):
    full = shared.get("/v1/briefings?limit=100")["items"]
    items, resume, sizes, flags = walk(shared, "limit=7")
    assert sizes == [7, 7, 7, 7, 7, 6]
    assert flags == [True] * 5 + [False]
    assert items == full
    assert [key(i) for i in items] == sorted(key(i) for i in items)

    empty = shared.get(cursor_path(resume))
    assert empty["items"] == [] and empty["has_more"] is False
    assert empty["next_cursor"]
    again = shared.get(cursor_path(empty["next_cursor"]))
    assert again["items"] == [] and again["next_cursor"]


@needs_flock
def test_exact_multiple_page_ends_with_has_more_false(shared: Client):
    _, _, sizes, flags = walk(shared, "limit=41")
    assert sizes == [41] and flags == [False]


@needs_flock
def test_since_is_inclusive(shared: Client):
    items, _, sizes, _ = walk(shared, "since=2026-11-01&limit=3")
    assert sorted(i["date"] for i in items) == [n.isoformat() for n in NOV]
    assert sizes == [3, 3, 3, 1]
    exact = shared.get("/v1/briefings?since=2026-11-12")
    assert [i["date"] for i in exact["items"]] == ["2026-11-12"]
    assert shared.get("/v1/briefings?since=2026-11-13")["items"] == []


@needs_flock
def test_single_briefing_equals_feed_item(shared: Client):
    full = shared.get("/v1/briefings?limit=100")["items"]
    for item in (full[0], full[-1]):
        assert shared.get(f"/v1/briefings/{item['id']}") == item
        assert shared.get(f"/v1/briefings/{item['id']}", PHONE_TOKEN) == item
    # Percent-encoded id and trailing slash resolve to the same briefing.
    ident = full[3]["id"]
    assert shared.get(f"/v1/briefings/{quote(ident)}/") == full[3]
    assert shared.get("/v1/briefings/?limit=100")["items"] == full


@needs_flock
@pytest.mark.parametrize(
    "path",
    [
        "/v1/briefings/brf_1999-01-01_00000000",
        "/v1/briefings/a/b",
        "/v1/briefings/a%2Fb",
        f"/v1/briefings/{bid(date(2026, 11, 5))}",  # never a ledger night
    ],
)
def test_unknown_ids_are_404(shared: Client, path: str):
    shared.error("GET", path, API_TOKEN, 404, "not_found")


# --------------------------------------------------------------------------
# Sync: rebuilds, tombstones, resume cursors


@needs_flock
def test_sync_across_rebuilds(ws: Workspace):
    with serving(ws) as client:
        full = client.get("/v1/briefings?limit=100")["items"]
        first_max = max(key(i) for i in full)
        _, resume_since, _, _ = walk(client, "since=2026-11-01&limit=3")
        _, resume_all, _, _ = walk(client, "limit=100")

        # Unchanged rebuild: nothing moves.
        assert ws.refresh(NOW + timedelta(hours=1)).changed == 0
        for cursor in (resume_since, resume_all):
            assert client.get(cursor_path(cursor))["items"] == []

        # The latest night changes: only its briefing.
        latest = bid(date(2026, 11, 12))
        ws.values[date(2026, 11, 12)]["net_sales"] += 98_765.43
        ws.values[date(2026, 11, 12)]["guest_count"] += 1_731.0
        ws.save()
        assert ws.refresh(NOW + timedelta(hours=2)).changed == 1
        data = client.get(cursor_path(resume_all))
        assert [i["id"] for i in data["items"]] == [latest]
        changed = data["items"][0]
        assert key(changed) > first_max
        before = next(i for i in full if i["id"] == latest)
        assert changed["created_at"] == before["created_at"]
        assert changed["updated_at"] > before["updated_at"]
        since_data = client.get(cursor_path(resume_since))
        assert [i["id"] for i in since_data["items"]] == [latest]
        resume_all = data["next_cursor"]
        resume_since = since_data["next_cursor"]

        # An October night changes: a November since-walk's resume cursor
        # still returns it (later changes of any date).
        ws.values[date(2026, 10, 20)]["net_sales"] += 123_457.79
        ws.save()
        ws.refresh(NOW + timedelta(hours=3))
        data = client.get(cursor_path(resume_since))
        dates = {i["date"] for i in data["items"]}
        assert {"2026-10-20", "2026-10-27"} <= dates
        assert dates <= {date(2026, 10, d).isoformat() for d in range(20, 32)}
        assert client.get(cursor_path(resume_all))["items"] == data["items"]
        previous_max = max(key(i) for i in data["items"])
        resume = data["next_cursor"]

        # A night leaves the ledger: a tombstone ordered after everything.
        gone = bid(date(2026, 10, 1))
        removed = ws.values.pop(date(2026, 10, 1))
        ws.save()
        assert ws.refresh(NOW + timedelta(hours=4)).tombstones == 1
        data = client.get(cursor_path(resume))
        stones = [i for i in data["items"] if i["deleted"]]
        assert stones == [
            {"id": gone, "updated_at": "2026-11-13T15:30:00Z", "deleted": True}
        ]
        assert key(stones[0]) > previous_max
        client.error("GET", f"/v1/briefings/{gone}", API_TOKEN, 404, "not_found")
        client.error("GET", f"/v1/briefings/{gone}", PHONE_TOKEN, 404, "not_found")

        # Tombstones appear without a cursor and are never filtered by since.
        everything, _, _, _ = walk(client, "limit=100")
        assert stones[0] in everything
        since_walk, _, _, _ = walk(client, "since=2026-11-01&limit=5")
        assert stones[0] in since_walk
        assert all(i["deleted"] or i["date"] >= "2026-11-01" for i in since_walk)
        keys = [key(i) for i in everything]
        assert keys == sorted(keys) and len(set(keys)) == len(keys)

        # The night returns: live again, newer than the tombstone.
        resume = data["next_cursor"]
        ws.values[date(2026, 10, 1)] = removed
        ws.save()
        ws.refresh(NOW + timedelta(hours=5))
        data = client.get(cursor_path(resume))
        back = [i for i in data["items"] if i["id"] == gone]
        assert len(back) == 1 and back[0]["deleted"] is False
        assert back[0]["updated_at"] > stones[0]["updated_at"]
        assert client.get(f"/v1/briefings/{gone}") == back[0]


@needs_flock
def test_since_walk_is_bounded_by_its_head(ws: Workspace):
    """A change during a since walk is left for the resume cursor."""
    with serving(ws) as client:
        page = client.get("/v1/briefings?since=2026-11-01&limit=4")
        assert page["has_more"] is True
        ws.values[date(2026, 11, 12)]["net_sales"] += 98_765.43
        ws.save()
        ws.refresh(NOW + timedelta(hours=1))
        items = list(page["items"])
        data = page
        while data["has_more"]:
            data = client.get(cursor_path(data["next_cursor"], "&limit=4"))
            items.extend(data["items"])
        ids = [i["id"] for i in items]
        assert len(ids) == len(set(ids))
        latest = bid(date(2026, 11, 12))
        stale = [i for i in items if i["id"] == latest]
        resumed = client.get(cursor_path(data["next_cursor"]))
        assert [i["id"] for i in resumed["items"]] == [latest]
        assert resumed["items"][0]["updated_at"] > max(
            [i["updated_at"] for i in stale] or [""]
        )


# --------------------------------------------------------------------------
# Parameters


@needs_flock
@pytest.mark.parametrize("value", ["0", "101", "-1", "abc", "1.5", "", "1000", "+5"])
def test_invalid_limit(shared: Client, value: str):
    shared.error("GET", f"/v1/briefings?limit={value}", API_TOKEN, 400, "invalid_limit")


@needs_flock
def test_repeated_parameters_are_invalid(shared: Client):
    shared.error(
        "GET", "/v1/briefings?limit=1&limit=2", API_TOKEN, 400, "invalid_limit"
    )
    shared.error(
        "GET",
        "/v1/briefings?since=2026-11-01&since=2026-11-02",
        API_TOKEN,
        400,
        "invalid_since",
    )


@needs_flock
@pytest.mark.parametrize(
    "value", ["15-11-2026", "2026-02-30", "20261115", "", "2026-11-1", "2026-13-01"]
)
def test_invalid_since(shared: Client, value: str):
    shared.error("GET", f"/v1/briefings?since={value}", API_TOKEN, 400, "invalid_since")


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def raw_cursor(**fields: Any) -> str:
    """A cursor in the documented format, with fields replaced or removed."""
    payload: dict[str, Any] = {"v": 1, "p": ["", ""], "s": None, "h": None}
    for name, value in fields.items():
        if value is _DROP:
            payload.pop(name)
        else:
            payload[name] = value
    return b64(json.dumps(payload, separators=(",", ":")).encode())


_DROP = object()


@needs_flock
def test_cursor_format_is_unpadded_base64url_json(shared: Client):
    page = shared.get("/v1/briefings?limit=2")
    cursor = page["next_cursor"]
    assert re.fullmatch(r"[A-Za-z0-9_-]+", cursor)
    payload = json.loads(unb64(cursor))
    # "g": the file's generation, so cursors from before a rebuild are refused.
    assert set(payload) == {"v", "p", "s", "h", "g"}
    assert payload["v"] == 1
    assert isinstance(payload["g"], str) and payload["g"]
    assert payload["p"] == list(key(page["items"][-1]))
    assert payload["s"] is None and payload["h"] is None

    since_page = shared.get("/v1/briefings?since=2026-11-01&limit=2")
    since_payload = json.loads(unb64(since_page["next_cursor"]))
    assert since_payload["s"] == "2026-11-01"
    assert isinstance(since_payload["h"], list) and len(since_payload["h"]) == 2

    decoded = decode_cursor(cursor)
    assert encode_cursor(decoded) == cursor


@needs_flock
@pytest.mark.parametrize(
    "value",
    [
        "not-a-cursor",  # base64url alphabet, but not JSON
        "",
        "a.b",
        "!!!",
        "abc=",
        b64(b"hello, not json"),
        b64(b"\xff\xfe\xfd"),
        b64(b"[1, 2]"),
        raw_cursor(v=2),
        raw_cursor(v="1"),
        raw_cursor(v=_DROP),
        raw_cursor(extra="x"),
        raw_cursor(h=_DROP),
        raw_cursor(p=_DROP),
        raw_cursor(s=_DROP),
        raw_cursor(p=["only-one"]),
        raw_cursor(p="2026-11-13T11:30:00Z"),
        raw_cursor(p=[1, 2]),
        raw_cursor(h=["a", "b", "c"]),
        raw_cursor(s="15-11-2026"),
        raw_cursor(s="20261115"),
        raw_cursor(s=""),
        raw_cursor(s=20261115),
    ],
)
def test_invalid_cursor(shared: Client, value: str):
    shared.error("GET", cursor_path(value), API_TOKEN, 400, "invalid_cursor")


@needs_flock
def test_well_formed_cursor_is_accepted_structurally(shared: Client):
    """No signature: a forged cursor only re-reads readable data."""
    listing = shared.get("/v1/briefings?limit=100")
    full = listing["items"]
    # Hand-built cursors must carry the served file's generation.
    g = json.loads(unb64(listing["next_cursor"]))["g"]
    assert shared.get(cursor_path(raw_cursor(g=g)) + "&limit=100")["items"] == full
    middle = key(full[9])
    page = shared.get(cursor_path(raw_cursor(p=list(middle), g=g)) + "&limit=100")
    assert page["items"] == full[10:]
    windowed = shared.get(
        cursor_path(raw_cursor(s="2026-11-10", h=list(key(full[-1])), g=g))
        + "&limit=100"
    )
    assert sorted(i["date"] for i in windowed["items"]) == ["2026-11-10", "2026-11-12"]
    built = encode_cursor(Cursor(position=middle, generation=g))
    assert shared.get(cursor_path(built, "&limit=100"))["items"] == full[10:]


@needs_flock
def test_cursors_survive_a_restart(ws: Workspace):
    with serving(ws) as first:
        page = first.get("/v1/briefings?since=2026-10-20&limit=5")
        rest = first.get(cursor_path(page["next_cursor"], "&limit=100"))["items"]
    with serving(ws, phone_token=None) as second:
        again = second.get(cursor_path(page["next_cursor"], "&limit=100"))
        assert again["items"] == rest


@needs_flock
def test_cursor_makes_since_ignored_and_limit_comes_first(shared: Client):
    valid = shared.get("/v1/briefings?limit=2")["next_cursor"]
    page = shared.get(cursor_path(valid, "&since=15-11-2026&since=x&limit=3"))
    assert len(page["items"]) == 3
    assert page["items"][0]["date"] < "2026-11-01"  # since did not filter
    shared.error(
        "GET", "/v1/briefings?limit=0&cursor=bogus", API_TOKEN, 400, "invalid_limit"
    )
    shared.error(
        "GET", "/v1/briefings?cursor=bogus&since=bad", API_TOKEN, 400, "invalid_cursor"
    )
    shared.error(
        "GET",
        "/v1/briefings?cursor=&since=15-11-2026",
        API_TOKEN,
        400,
        "invalid_cursor",
    )


@needs_flock
def test_unknown_parameters_are_ignored(shared: Client):
    assert shared.get("/v1/briefings?limit=2&colour=blue")["items"]


# --------------------------------------------------------------------------
# Methods and availability


@needs_flock
@pytest.mark.parametrize("token", [API_TOKEN, PHONE_TOKEN])
@pytest.mark.parametrize(
    "path", ["/v1/health", "/v1/briefings", f"/v1/briefings/{bid(NOV[0])}"]
)
def test_post_to_a_briefing_route_is_405(shared: Client, path: str, token: str):
    response = shared.error("POST", path, token, 405, "method_not_allowed")
    assert response.headers.get("allow") == "GET"


@needs_flock
def test_other_methods_get_the_http_layer_501(shared: Client):
    # Documented deviation: only GET and POST are dispatched.
    response = shared.request("DELETE", "/v1/briefings")
    assert response.status == 501


@needs_flock
def test_missing_file_is_503_while_other_routes_work(ws: Workspace, tmp_path: Path):
    missing = tmp_path / "not-yet" / "briefings.json"
    with serving(ws, briefings=missing) as client:
        for path in ("/v1/briefings", f"/v1/briefings/{bid(NOV[0])}"):
            for token in (API_TOKEN, PHONE_TOKEN):
                client.error("GET", path, token, 503, "briefings_unavailable")
        # Parameter errors answer before the file is needed.
        for query, code in (
            ("limit=0", "invalid_limit"),
            ("since=20261115", "invalid_since"),
            ("cursor=bogus", "invalid_cursor"),
        ):
            client.error("GET", f"/v1/briefings?{query}", PHONE_TOKEN, 400, code)
        client.error("GET", "/v1/briefings/a/b", API_TOKEN, 404, "not_found")
        assert client.get("/v1/health", PHONE_TOKEN)["ok"] is True
        assert (
            client.get("/v1/freshness")["last_service_date"] == "2026-11-13"
        )  # other entity
        assert client.request("GET", "/health", None).status == 200

        # Built after start-up: served without a restart.
        missing.parent.mkdir()
        ws.briefings = missing
        ws.refresh()
        assert len(client.get("/v1/briefings?limit=100", PHONE_TOKEN)["items"]) == 41


@needs_flock
@pytest.mark.parametrize(
    "content",
    ["not json", '{"format": 2, "figures": "relative_only", "briefings": []}', "[]"],
)
def test_unreadable_file_is_503(ws: Workspace, content: str):
    ws.briefings.write_text(content, encoding="utf-8")
    with serving(ws) as client:
        client.error("GET", "/v1/briefings", API_TOKEN, 503, "briefings_unavailable")


@needs_flock
def test_empty_feed_still_yields_a_cursor(ws: Workspace):
    ws.briefings.write_text(
        '{"format": 1, "figures": "relative_only", "generation": "emptyfeed01",'
        ' "briefings": []}',
        encoding="utf-8",
    )
    with serving(ws) as client:
        page = client.get("/v1/briefings")
        assert page["items"] == [] and page["has_more"] is False
        assert page["next_cursor"]
        assert client.get(cursor_path(page["next_cursor"]))["items"] == []


# --------------------------------------------------------------------------
# Auth

BRIEFING_ROUTES = ["/v1/health", "/v1/briefings", f"/v1/briefings/{bid(NOV[2])}"]


@needs_flock
def test_health_is_unchanged_and_unauthenticated(shared: Client):
    response = shared.request("GET", "/health", None)
    assert response.status == 200
    assert response.raw == b'{"service": "atlas-restaurantos", "status": "ok"}'


@needs_flock
def test_v1_health_data(shared: Client):
    assert shared.get("/v1/health", PHONE_TOKEN) == {
        "api_version": "1",
        "figures": "relative_only",
        "name": "atlas-restaurantos",
        "ok": True,
    }


@needs_flock
@pytest.mark.parametrize("path", BRIEFING_ROUTES)
def test_both_tokens_open_briefing_routes(shared: Client, path: str):
    assert shared.get(path, API_TOKEN) == shared.get(path, PHONE_TOKEN)
    for authorization in (f"bearer {PHONE_TOKEN}", f"BEARER {API_TOKEN}"):
        response = shared.request("GET", path, authorization=authorization)
        assert response.status == 200


@needs_flock
@pytest.mark.parametrize(
    "path", [*BRIEFING_ROUTES, "/v1/freshness", "/v1/unknown", "/nope"]
)
@pytest.mark.parametrize("token", [None, "", WRONG_TOKEN, API_TOKEN[:-1]])
def test_missing_wrong_or_empty_token_is_401(shared: Client, path: str, token: Any):
    shared.error("GET", path, token, 401, "unauthorized")


@needs_flock
@pytest.mark.parametrize(
    "authorization",
    [
        f"Basic {PHONE_TOKEN}",
        PHONE_TOKEN,
        f"Bearer {PHONE_TOKEN}x",
        f"Bearer{PHONE_TOKEN}",
        f"Token {API_TOKEN}",
    ],
)
def test_malformed_authorization_is_401(shared: Client, authorization: str):
    response = shared.request("GET", "/v1/briefings", authorization=authorization)
    assert response.status == 401 and response.code == "unauthorized"


@needs_flock
def test_phone_token_opens_nothing_else(shared: Client):
    for method, path in (
        ("GET", "/v1/freshness"),
        ("POST", "/v1/operating-summary"),
        ("GET", "/v1/unknown"),
        ("GET", "/v1/briefings/a/b"),
        ("GET", "/nope"),
        ("POST", "/v1/freshness"),
        # JAM Decisions is a JARVIS route (upstream 151fbf6), never the phone's.
        ("GET", "/v1/decisions"),
        ("GET", "/v1/decisions/"),
        ("GET", "/v1/decisions?limit=1"),
        ("POST", "/v1/decisions"),
    ):
        shared.error(method, path, PHONE_TOKEN, 401, "unauthorized")


@needs_flock
def test_api_token_opens_every_route(shared: Client):
    for path in BRIEFING_ROUTES:
        shared.get(path, API_TOKEN)
    shared.get("/v1/freshness", API_TOKEN)
    response = shared.request(
        "POST",
        "/v1/operating-summary",
        API_TOKEN,
        body=json.dumps({"entity": ENTITY}).encode(),
    )
    assert response.status == 200
    assert response.json["data"]["figures"] == "relative_only"
    decisions = shared.request("GET", "/v1/decisions", API_TOKEN)
    assert decisions.status != 401, decisions.raw[:300]
    shared.error("GET", "/v1/unknown", API_TOKEN, 404, "not_found")
    shared.error("POST", "/v1/unknown", None, 401, "unauthorized")


@needs_flock
def test_phone_token_refused_when_unset(ws: Workspace):
    with serving(ws, phone_token=None) as client:
        for path in BRIEFING_ROUTES:
            client.error("GET", path, PHONE_TOKEN, 401, "unauthorized")
            client.get(path, API_TOKEN)


@needs_flock
def test_tokens_are_never_logged(ws: Workspace, caplog: pytest.LogCaptureFixture):
    with caplog.at_level(logging.INFO, logger="restaurantos.api"), serving(ws) as c:
        c.get("/v1/briefings?limit=2", PHONE_TOKEN)
        c.request("GET", "/v1/freshness", PHONE_TOKEN)
        c.request("GET", "/v1/briefings", WRONG_TOKEN)
    assert caplog.records  # the request lines were logged
    for secret in (API_TOKEN, PHONE_TOKEN, WRONG_TOKEN):
        assert secret not in caplog.text


# --------------------------------------------------------------------------
# Config


def _config(**overrides: Any) -> ApiConfig:
    fields: dict[str, Any] = {
        "history_path": Path("h.jsonl"),
        "manifest_path": Path("m.json"),
        "token": API_TOKEN,
    }
    fields.update(overrides)
    return ApiConfig(**fields)


@pytest.mark.parametrize(
    ("phone", "message"),
    [
        ("short-phone-token-12345", "at least 24"),  # 23 characters
        (API_TOKEN, "must differ"),
    ],
)
def test_config_rejects_bad_phone_tokens(phone: str, message: str):
    with pytest.raises(ValueError, match=message) as error:
        _config(briefings_token=phone)
    assert phone not in str(error.value)
    assert API_TOKEN not in str(error.value)
    assert "ATLAS_BRIEFINGS_TOKEN" in str(error.value)


def test_config_accepts_a_24_character_phone_token():
    assert _config(briefings_token="x" * 24).briefings_token == "x" * 24


def test_config_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("ATLAS_API_TOKEN", API_TOKEN)
    monkeypatch.setenv("ATLAS_BRIEFINGS_TOKEN", "")
    config = config_from_env(tmp_path / "h.jsonl", tmp_path / "m.json")
    assert config.briefings_token is None
    assert config.resolved_briefings_path == tmp_path / "briefings.json"

    monkeypatch.delenv("ATLAS_BRIEFINGS_TOKEN")
    assert config_from_env("h", "m").briefings_token is None

    monkeypatch.setenv("ATLAS_BRIEFINGS_TOKEN", PHONE_TOKEN)
    config = config_from_env("h", "m", briefings_path=tmp_path / "b.json")
    assert config.briefings_token == PHONE_TOKEN
    assert config.resolved_briefings_path == tmp_path / "b.json"


# --------------------------------------------------------------------------
# Privacy


def _scrub(value: Any, name: str | None = None) -> list[str]:
    """Every key and value as text, opaque tokens skipped (cursors decoded)."""
    if name == "next_cursor" and isinstance(value, str):
        body = value.partition(".")[0]
        return [base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode()]
    if name in OPAQUE_KEYS and isinstance(value, str):
        return []
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            out.append(str(k))
            out.extend(_scrub(v, str(k)))
        return out
    if isinstance(value, list):
        return [part for element in value for part in _scrub(element)]
    return [str(value)]


@needs_flock
def test_no_response_reveals_an_absolute_figure(ws: Workspace):
    with serving(ws) as client:
        walk(client, "limit=100")
        walk(client, "limit=4", PHONE_TOKEN)
        walk(client, "since=2026-10-15&limit=9")
        full = client.get("/v1/briefings?limit=100")["items"]
        for item in full:
            client.get(f"/v1/briefings/{item['id']}", PHONE_TOKEN)
        client.get("/v1/health", PHONE_TOKEN)
        client.request("GET", "/v1/briefings?limit=0", PHONE_TOKEN)
        client.request("GET", "/v1/briefings?since=bad", PHONE_TOKEN)
        client.request("GET", "/v1/briefings?cursor=bad", PHONE_TOKEN)
        client.request("GET", "/v1/briefings/brf_1999-01-01_00000000", PHONE_TOKEN)
        client.request("POST", "/v1/briefings", PHONE_TOKEN)
        client.request("GET", "/v1/freshness", PHONE_TOKEN)

        ws.values[date(2026, 11, 12)]["net_sales"] += 11_111.11
        ws.values.pop(date(2026, 10, 2))
        ws.save()
        ws.refresh(NOW + timedelta(hours=1))
        after, _, _, _ = walk(client, "limit=100")
        responses = list(client.responses)

    assert len(responses) > 60
    forbidden = forbidden_numbers(synthetic_values()) | forbidden_numbers(ws.values)
    separated = with_separators(forbidden)
    for response in responses:
        assert response.json is not None
        assert leaks(response.raw.decode(), set(), set()) == []  # names, currency
        text = " | ".join(_scrub(response.json))
        assert leaks(text, forbidden, separated) == []
    for item in full + after:
        if not item["deleted"]:
            assert stray_numbers(prose_of(item)) == [], item["date"]
