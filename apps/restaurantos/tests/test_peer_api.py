import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from restaurantos.api import (
    ApiConfig,
    ApiError,
    Ledger,
    config_from_env,
    freshness,
    make_server,
    operating_summary,
)
from restaurantos.nightly_history import read_history_jsonl
from restaurantos.operating_brief import summarize_operating_period
from restaurantos.relative_summary import (
    preceding_window,
    relative_operating_summary,
)

TOKEN = "test-token-0123456789abcdefghij"
ENTITY = "Test Restaurant"

# Deliberately odd values: if one shows up in a response, it leaked.
NIGHTS: dict[str, dict[str, float]] = {
    "2026-05-01": {
        "net_sales": 7311.0,
        "guest_count": 213.0,
        "reservation_covers": 131.0,
        "labor_hours": 97.0,
        "labor_cost": 1913.0,
        "comps": 83.0,
        "voids": 29.0,
    },
    "2026-05-02": {
        "net_sales": 6187.0,
        "guest_count": 187.0,
        "reservation_covers": 113.0,
        "labor_hours": 89.0,
        "labor_cost": 1777.0,
        "comps": 71.0,
        "voids": 23.0,
    },
    "2026-06-01": {
        "net_sales": 8419.0,
        "guest_count": 241.0,
        "reservation_covers": 163.0,
        "labor_hours": 103.0,
        "labor_cost": 2039.0,
        "comps": 67.0,
        "voids": 31.0,
    },
    "2026-06-02": {
        "net_sales": 7793.0,
        "guest_count": 229.0,
        "reservation_covers": 149.0,
        "labor_hours": 101.0,
        "labor_cost": 1987.0,
        "comps": 59.0,
        "voids": 37.0,
    },
}


def write_ledger(path: Path, nights: dict[str, dict[str, float]] = NIGHTS) -> Path:
    lines = [
        json.dumps(
            {
                "source": "nightly_email",
                "entity": ENTITY,
                "period": period,
                "category": "operations",
                "metric": metric,
                "value": value,
                "dimensions": {},
                "grain": "daily",
                "aggregation": "sum",
            },
            sort_keys=True,
        )
        for period, metrics in nights.items()
        for metric, value in metrics.items()
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_manifest(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "service_nights": 4,
                "record_count": 28,
                "first_service_date": "2026-05-01",
                "last_service_date": "2026-06-02",
                "skipped_message_count": 0,
                "review_count": 1,
                "warning_counts": {"estimated_sales": 1},
                "review_reason_counts": {},
                "not_a_manifest_field": "must not be relayed",
            }
        ),
        encoding="utf-8",
    )
    return path


def _numbers(node: Any) -> Iterator[float]:
    if isinstance(node, bool):
        return
    if isinstance(node, int | float):
        yield float(node)
    elif isinstance(node, dict):
        for value in node.values():
            yield from _numbers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _numbers(value)


def _absolute_figures() -> set[float]:
    """Every nightly value, period total and rate level in the fixture."""
    records = read_history_jsonl_from_nights()
    figures = {value for metrics in NIGHTS.values() for value in metrics.values()}
    for start, end in (
        (date(2026, 5, 1), date(2026, 5, 2)),
        (date(2026, 6, 1), date(2026, 6, 2)),
    ):
        summary = summarize_operating_period(records, start, end)
        figures.update(value for _, value in summary.totals)
        # Exact rate levels. Rounded ones are left out on purpose: a small
        # level such as covers per labor hour can equal an unrelated change.
        figures.update(value for _, value in summary.derived)
    return figures


def read_history_jsonl_from_nights() -> list[Any]:
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        return read_history_jsonl(write_ledger(Path(directory) / "h.jsonl"))


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return write_ledger(tmp_path / "nightly-history.jsonl")


@pytest.fixture
def server(tmp_path: Path, ledger_path: Path) -> Iterator[ThreadingHTTPServer]:
    config = ApiConfig(
        history_path=ledger_path,
        manifest_path=write_manifest(tmp_path / "nightly-manifest.json"),
        token=TOKEN,
        port=0,
    )
    instance = make_server(config)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


def call(
    server: ThreadingHTTPServer,
    method: str,
    path: str,
    *,
    body: Any = None,
    token: str | None = TOKEN,
    raw: bytes | None = None,
) -> tuple[int, dict[str, Any]]:
    host, port = server.server_address[:2]
    data = raw if raw is not None else None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"http://{host!s}:{port}{path}", data=data, method=method
    )
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


# --- relative summary -------------------------------------------------------


def _summaries() -> tuple[Any, Any]:
    records = read_history_jsonl_from_nights()
    current = summarize_operating_period(records, date(2026, 6, 1), date(2026, 6, 2))
    previous = summarize_operating_period(records, date(2026, 5, 1), date(2026, 5, 2))
    return current, previous


def test_relative_summary_reports_changes_not_levels():
    current, previous = _summaries()
    result = relative_operating_summary(current, previous)
    changes = {entry["metric"]: entry for entry in result["changes"]}

    assert result["figures"] == "relative_only"
    sales = changes["net_sales"]
    expected = (16212.0 - 13498.0) / 13498.0 * 100.0
    assert sales["unit"] == "percent"
    assert sales["basis"] == "total"
    assert sales["change"] == round(expected, 1)
    assert sales["direction"] == "up"

    labor_pct = changes["labor_cost_pct"]
    assert labor_pct["unit"] == "percentage_points"
    assert labor_pct["change"] == round(
        4026.0 / 16212.0 * 100.0 - 3690.0 / 13498.0 * 100.0, 1
    )
    assert labor_pct["direction"] == "down"

    # A metric neither period carries is reported as unknown, not as zero.
    assert changes["dining_room_covers"]["change"] is None
    assert changes["dining_room_covers"]["direction"] is None


def test_relative_summary_never_contains_an_absolute_figure():
    current, previous = _summaries()
    result = relative_operating_summary(current, previous)

    leaked = set(_numbers(result)) & _absolute_figures()
    assert leaked == set()
    text = json.dumps(result)
    assert "$" not in text
    for forbidden in ("totals", "derived", "per_night", "value"):
        assert f'"{forbidden}"' not in text


def test_uneven_coverage_compares_per_covered_night():
    nights = {key: dict(value) for key, value in NIGHTS.items()}
    del nights["2026-05-02"]["net_sales"]
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        records = read_history_jsonl(write_ledger(Path(directory) / "h.jsonl", nights))
    current = summarize_operating_period(records, date(2026, 6, 1), date(2026, 6, 2))
    previous = summarize_operating_period(records, date(2026, 5, 1), date(2026, 5, 2))
    sales = next(
        entry
        for entry in relative_operating_summary(current, previous)["changes"]
        if entry["metric"] == "net_sales"
    )
    assert sales["basis"] == "per_covered_night"
    assert (sales["current_nights"], sales["previous_nights"]) == (2, 1)
    assert sales["change"] == round((8106.0 - 7311.0) / 7311.0 * 100.0, 1)


def test_flat_and_mismatched_entities():
    current, _ = _summaries()
    result = relative_operating_summary(current, current)
    assert {entry["direction"] for entry in result["changes"]} <= {"flat", None}

    records = read_history_jsonl_from_nights()
    other = summarize_operating_period(
        [
            type(record)(
                **{
                    **{
                        field: getattr(record, field)
                        for field in record.__dataclass_fields__
                    },
                    "entity": "Elsewhere",
                }
            )
            for record in records
        ],
        date(2026, 6, 1),
        date(2026, 6, 2),
    )
    with pytest.raises(ValueError, match="same entity"):
        relative_operating_summary(current, other)


def test_preceding_window_is_equal_length_and_adjacent():
    assert preceding_window(date(2026, 6, 8), date(2026, 6, 14)) == (
        date(2026, 6, 1),
        date(2026, 6, 7),
    )
    with pytest.raises(ValueError):
        preceding_window(date(2026, 6, 2), date(2026, 6, 1))


# --- window resolution ------------------------------------------------------


def test_default_windows_are_month_to_date_against_prior_month(ledger_path: Path):
    result = operating_summary(read_history_jsonl(ledger_path), {})
    assert result["current"]["start_date"] == "2026-06-01"
    assert result["current"]["end_date"] == "2026-06-02"
    assert result["previous"]["start_date"] == "2026-05-01"
    assert result["previous"]["end_date"] == "2026-05-02"
    assert result["current"]["service_nights"] == 2


def test_window_without_comparison_uses_the_preceding_window(ledger_path: Path):
    records = read_history_jsonl(ledger_path)
    with pytest.raises(ApiError) as caught:
        operating_summary(
            records, {"start_date": "2026-06-01", "end_date": "2026-06-02"}
        )
    # May 30-31 holds no service nights in the fixture.
    assert caught.value.code == "unprocessable_period"
    assert caught.value.message.startswith("comparison period:")


@pytest.mark.parametrize(
    "payload",
    [
        {"start_date": "2026-06-01"},
        {"start_date": "2026-06-02", "end_date": "2026-06-01"},
        {"start_date": "June 1", "end_date": "2026-06-02"},
        {"start_date": 20260601, "end_date": "2026-06-02"},
        {"start_date": "2024-01-01", "end_date": "2026-06-02"},
        {"compare_start_date": "2026-05-01", "compare_end_date": "2026-05-02"},
        {"entity": 7},
        {"metric": "net_sales"},
    ],
)
def test_invalid_requests_are_rejected(ledger_path: Path, payload: dict[str, Any]):
    with pytest.raises(ApiError) as caught:
        operating_summary(read_history_jsonl(ledger_path), payload)
    assert caught.value.code == "invalid_request"


def test_empty_ledger_has_no_default_window():
    with pytest.raises(ApiError) as caught:
        operating_summary([], {})
    assert caught.value.code == "no_data"


# --- freshness --------------------------------------------------------------


def test_freshness_reports_dates_and_counts_only(tmp_path: Path, ledger_path: Path):
    manifest = write_manifest(tmp_path / "manifest.json")
    result = freshness(Ledger(ledger_path), manifest, today=date(2026, 6, 5))

    assert result["last_service_date"] == "2026-06-02"
    assert result["days_since_last_service"] == 3
    assert result["service_nights_in_ledger"] == 4
    assert result["manifest"]["review_count"] == 1
    assert "not_a_manifest_field" not in result["manifest"]
    assert set(_numbers(result)) & _absolute_figures() == set()


def test_freshness_without_manifest(tmp_path: Path, ledger_path: Path):
    missing = freshness(
        Ledger(ledger_path), tmp_path / "absent.json", today=date(2026, 6, 5)
    )
    assert missing["manifest"] is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert (
        freshness(Ledger(ledger_path), broken, today=date(2026, 6, 5))["manifest"]
        is None
    )


def test_ledger_reloads_when_the_file_changes(ledger_path: Path):
    ledger = Ledger(ledger_path)
    assert len(ledger.records()) == 28
    assert ledger.records() is ledger.records()

    nights = {**NIGHTS, "2026-06-03": {"net_sales": 9001.0}}
    write_ledger(ledger_path, nights)
    assert len(ledger.records()) == 29

    ledger_path.unlink()
    assert ledger.modified_at() is None
    with pytest.raises(ApiError) as caught:
        ledger.records()
    assert caught.value.code == "ledger_unavailable"


# --- configuration ----------------------------------------------------------


def test_config_requires_a_real_token(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ATLAS_API_TOKEN", raising=False)
    with pytest.raises(ValueError, match="ATLAS_API_TOKEN"):
        config_from_env(tmp_path / "h.jsonl", tmp_path / "m.json")

    monkeypatch.setenv("ATLAS_API_TOKEN", "short")
    with pytest.raises(ValueError, match="ATLAS_API_TOKEN"):
        config_from_env(tmp_path / "h.jsonl", tmp_path / "m.json")


def test_config_defaults_to_loopback(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ATLAS_API_TOKEN", TOKEN)
    monkeypatch.delenv("ATLAS_API_HOST", raising=False)
    monkeypatch.setenv("ATLAS_API_PORT", "8791")
    config = config_from_env(tmp_path / "h.jsonl", tmp_path / "m.json")
    assert (config.host, config.port) == ("127.0.0.1", 8791)
    assert config_from_env(tmp_path / "h", tmp_path / "m", port=0).port == 0


# --- HTTP surface -----------------------------------------------------------


def test_health_needs_no_token_and_carries_no_data(server: ThreadingHTTPServer):
    status, body = call(server, "GET", "/health", token=None)
    assert status == 200
    assert body == {"status": "ok", "service": "atlas-restaurantos"}


@pytest.mark.parametrize("token", [None, "wrong-token-0123456789abcdefgh", ""])
def test_data_routes_require_the_bearer_token(
    server: ThreadingHTTPServer, token: str | None
):
    for method, path in (
        ("GET", "/v1/freshness"),
        ("POST", "/v1/operating-summary"),
        ("GET", "/v1/anything-else"),
    ):
        status, body = call(server, method, path, token=token)
        assert status == 401
        assert body["error"]["code"] == "unauthorized"
        assert "data" not in body


def test_operating_summary_over_http_is_relative_only(server: ThreadingHTTPServer):
    status, body = call(server, "POST", "/v1/operating-summary", body={})
    assert status == 200
    assert body["request_id"]
    data = body["data"]
    assert data["entity"] == ENTITY
    assert data["figures"] == "relative_only"
    assert set(_numbers(body)) & _absolute_figures() == set()

    status, explicit = call(
        server,
        "POST",
        "/v1/operating-summary",
        body={
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
            "compare_start_date": "2026-05-01",
            "compare_end_date": "2026-05-02",
            "entity": ENTITY,
        },
    )
    assert status == 200
    assert explicit["data"]["changes"] == data["changes"]


def test_freshness_over_http(server: ThreadingHTTPServer):
    status, body = call(server, "GET", "/v1/freshness")
    assert status == 200
    assert body["data"]["last_service_date"] == "2026-06-02"


def test_http_errors_use_the_error_envelope(server: ThreadingHTTPServer):
    status, body = call(server, "POST", "/v1/operating-summary", raw=b"{not json")
    assert (status, body["error"]["code"]) == (400, "invalid_request")

    status, body = call(server, "POST", "/v1/operating-summary", body=[1, 2])
    assert (status, body["error"]["code"]) == (400, "invalid_request")

    status, body = call(
        server, "POST", "/v1/operating-summary", body={"entity": "Nowhere"}
    )
    assert (status, body["error"]["code"]) == (422, "unprocessable_period")

    status, body = call(server, "GET", "/v1/operating-summary")
    assert (status, body["error"]["code"]) == (404, "not_found")

    status, body = call(
        server, "POST", "/v1/operating-summary", raw=b" " * (16 * 1024 + 1)
    )
    assert (status, body["error"]["code"]) == (413, "invalid_request")


def test_internal_errors_do_not_echo_ledger_content(
    server: ThreadingHTTPServer, ledger_path: Path
):
    ledger_path.write_text('{"value": 424242.0, "broken": true}\n', encoding="utf-8")
    status, body = call(server, "POST", "/v1/operating-summary", body={})
    assert status == 500
    assert body["error"]["code"] == "internal_error"
    assert "424242" not in json.dumps(body)
