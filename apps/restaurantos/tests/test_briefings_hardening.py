"""Hardening of the briefings writer, feed and nightly wiring.

Covers: the optional nightly briefings step, healing a damaged briefings file,
file generations and the cursors bound to them, the refresh lock, the shared
coverage module, confidence wording and the default briefings path. All data
is synthetic (``test_briefings``).
"""

from __future__ import annotations

import base64
import json
import os
import re
import runpy
import shlex
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import restaurantos.__main__ as cli_module
from _posix import needs_flock
from restaurantos import api, api_defaults, coverage
from restaurantos.briefings import refresh_briefings
from test_briefings import (
    ENTITY,
    NIGHTLY_SCRIPT,
    NIGHTS,
    NOW,
    ROOT,
    Workspace,
    bid,
    parse_lines,
    run_cli,
)
from test_briefings_api import (
    API_TOKEN,
    Client,
    cursor_path,
    serving,
)

try:
    import fcntl
except ImportError:  # not a POSIX host: the tests that need flock skip
    fcntl = None  # type: ignore[assignment]

GENERATION = re.compile(r"[A-Za-z0-9_-]{8,64}")
SERVICE_FILE = ROOT / "deploy" / "systemd" / "atlas-restaurantos-api.service"


def generation_of(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")).get("generation")


def raw_cursor(fields: dict[str, Any]) -> str:
    payload = json.dumps(fields, separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode().rstrip("=")


@pytest.fixture(scope="module")
def built_ws(tmp_path_factory: pytest.TempPathFactory) -> Workspace:
    """A built workspace shared by read-only tests (never mutate it)."""
    ws = Workspace(tmp_path_factory.mktemp("hardening-built"))
    ws.build()
    return ws


# --------------------------------------------------------------------------
# 1. The nightly briefings step is optional


@pytest.fixture
def nightly_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "atlas-data"
    (root / "google").mkdir(parents=True)
    (root / "google" / "gmail-token.json").write_text("{}", encoding="utf-8")
    fonda = root / "restaurantos" / "fonda"
    fonda.mkdir(parents=True)
    (fonda / "nightly-messages.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("ATLAS_DATA_ROOT", str(root))
    monkeypatch.setenv("ATLAS_RESTAURANT", ENTITY)
    monkeypatch.setenv("ATLAS_TIMEZONE", "America/Chicago")
    monkeypatch.delenv("ATLAS_GMAIL_LOOKBACK_DAYS", raising=False)
    return root


def run_nightly(
    monkeypatch: pytest.MonkeyPatch,
    second: Callable[[list[str]], Any] | None = None,
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    """Run the nightly entry point; it must exit 0. Returns calls and kwargs."""
    calls: list[list[str]] = []
    kwargs_seen: list[dict[str, Any]] = []

    def fake(command: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append([str(part) for part in command])
        kwargs_seen.append(kwargs)
        if len(calls) == 2 and second is not None:
            second(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(SystemExit) as exit_:
        runpy.run_path(str(NIGHTLY_SCRIPT), run_name="__main__")
    assert exit_.value.code == 0
    return calls, kwargs_seen


def _called_process(status: int) -> Callable[[list[str]], Any]:
    def raise_(command: list[str]) -> Any:
        raise subprocess.CalledProcessError(status, command)

    return raise_


def _raising(error: BaseException) -> Callable[[list[str]], Any]:
    def raise_(command: list[str]) -> Any:
        raise error

    return raise_


@pytest.mark.parametrize(
    "failure",
    [
        _called_process(1),
        _called_process(2),
        _called_process(-9),
        _raising(OSError("no such interpreter")),
        _raising(FileNotFoundError(2, "No such file", "python")),
        _raising(RuntimeError("briefings blew up")),
    ],
    ids=["exit1", "exit2", "signal9", "oserror", "filenotfound", "runtimeerror"],
)
def test_nightly_survives_a_failed_briefings_step(
    nightly_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    failure: Callable[[list[str]], Any],
):
    calls, kwargs_seen = run_nightly(monkeypatch, failure)
    err = capsys.readouterr().err
    assert len(calls) == 2
    assert "briefings-refresh" in calls[1]
    assert kwargs_seen[0].get("check") is True
    mentions = [line for line in err.splitlines() if "briefings-refresh" in line]
    assert len(mentions) == 1, err
    assert "the ledger refresh succeeded" in mentions[0]


def test_nightly_flattens_a_multi_line_error(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    run_nightly(monkeypatch, _raising(RuntimeError("line one\nline two\r\n  three")))
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if line.strip()]
    assert len(lines) == 1, err
    assert "briefings-refresh" in lines[0]
    assert "line one line two three" in lines[0]
    assert "the ledger refresh succeeded" in lines[0]


def test_nightly_successful_briefings_step_is_silent(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    calls, _ = run_nightly(monkeypatch)
    assert len(calls) == 2
    assert "briefings-refresh" not in capsys.readouterr().err


@pytest.mark.parametrize("status", [1, 3])
def test_nightly_first_step_failure_still_propagates(
    nightly_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    status: int,
):
    calls: list[list[str]] = []
    kwargs_seen: list[dict[str, Any]] = []

    def fake(command: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append([str(part) for part in command])
        kwargs_seen.append(kwargs)
        raise subprocess.CalledProcessError(status, command)

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(subprocess.CalledProcessError) as error:
        runpy.run_path(str(NIGHTLY_SCRIPT), run_name="__main__")
    capsys.readouterr()
    assert error.value.returncode == status
    assert len(calls) == 1
    assert "gmail-nightly-refresh" in calls[0]
    assert kwargs_seen[0].get("check") is True


# --------------------------------------------------------------------------
# 2. A damaged briefings file is rebuilt


def _doc_edit(edit: Callable[[dict[str, Any]], None]) -> Callable[[bytes], bytes]:
    def apply(original: bytes) -> bytes:
        doc = json.loads(original)
        edit(doc)
        return json.dumps(doc).encode("utf-8")

    return apply


def _set(key: str, value: Any) -> Callable[[dict[str, Any]], None]:
    def edit(doc: dict[str, Any]) -> None:
        doc[key] = value

    return edit


def _drop_first_id(doc: dict[str, Any]) -> None:
    del doc["briefings"][0]["id"]


def _yesterday(doc: dict[str, Any]) -> None:
    doc["briefings"][0]["updated_at"] = "yesterday"


def _date_only(doc: dict[str, Any]) -> None:
    doc["briefings"][0]["updated_at"] = "2026-11-13"


def _offset_stamp(doc: dict[str, Any]) -> None:
    doc["briefings"][0]["updated_at"] = "2026-11-13T11:30:00+00:00"


def _end_of_time(doc: dict[str, Any]) -> None:
    # Well-formed, but the next stamp (one second later) cannot exist.
    doc["briefings"][0]["updated_at"] = "9999-12-31T23:59:59Z"


DAMAGE: dict[str, Callable[[bytes], bytes]] = {
    "not-json": lambda _: b"{ not json",
    "not-utf8": lambda _: b"\xff\xfe",
    "list": lambda _: b"[]",
    "empty": lambda _: b"",
    "format-99": _doc_edit(_set("format", 99)),
    "entry-without-id": _doc_edit(_drop_first_id),
    "updated-at-yesterday": _doc_edit(_yesterday),
    "updated-at-date-only": _doc_edit(_date_only),
    "updated-at-offset": _doc_edit(_offset_stamp),
    "updated-at-end-of-time": _doc_edit(_end_of_time),
    "generation-int": _doc_edit(_set("generation", 5)),
    "generation-short": _doc_edit(_set("generation", "x")),
    "generation-missing": lambda raw: json.dumps(
        {k: v for k, v in json.loads(raw).items() if k != "generation"}
    ).encode(),
}


def _assert_healed(ws: Workspace, err: str, result: Any, old_generation: Any) -> None:
    assert str(ws.briefings) in err
    assert "rebuild" in err
    assert result.changed == len(NIGHTS)
    assert result.tombstones == 0
    assert ws.briefings.stat().st_mode & 0o777 == 0o600
    generation = generation_of(ws.briefings)
    assert isinstance(generation, str) and GENERATION.fullmatch(generation)
    if isinstance(old_generation, str):
        assert generation != old_generation
    again = ws.refresh(NOW + timedelta(hours=1))
    assert again.changed == 0
    assert generation_of(ws.briefings) == generation


@needs_flock
@pytest.mark.parametrize("kind", list(DAMAGE))
def test_refresh_heals_a_damaged_file(
    tmp_path: Path, capsys: pytest.CaptureFixture, kind: str
):
    ws = Workspace(tmp_path)
    ws.build()
    original = ws.briefings.read_bytes()
    old_generation = json.loads(original).get("generation")
    ws.briefings.write_bytes(DAMAGE[kind](original))
    capsys.readouterr()

    result = ws.refresh()

    _assert_healed(ws, capsys.readouterr().err, result, old_generation)


@needs_flock
@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-000 file")
def test_refresh_heals_an_unreadable_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    ws = Workspace(tmp_path)
    ws.build()
    old_generation = generation_of(ws.briefings)
    ws.briefings.chmod(0o000)
    capsys.readouterr()
    try:
        result = ws.refresh()
    finally:
        if ws.briefings.exists():
            ws.briefings.chmod(ws.briefings.stat().st_mode | 0o600)
    _assert_healed(ws, capsys.readouterr().err, result, old_generation)


@needs_flock
def test_cli_refresh_heals_a_damaged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    ws = Workspace(tmp_path)
    ws.briefings.write_bytes(b"{ not json")
    run_cli(
        monkeypatch,
        "briefings-refresh",
        "--history",
        str(ws.history),
        "--manifest",
        str(ws.manifest),
        "--briefings",
        str(ws.briefings),
        "--entity",
        ENTITY,
    )
    captured = capsys.readouterr()
    assert parse_lines(captured.out)["changed"] == str(len(NIGHTS))
    assert str(ws.briefings) in captured.err
    assert "rebuild" in captured.err
    assert ws.briefings.stat().st_mode & 0o777 == 0o600


# --------------------------------------------------------------------------
# 3. Generations


@needs_flock
def test_generation_is_kept_until_the_file_is_rebuilt(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.refresh()
    first = generation_of(ws.briefings)
    assert isinstance(first, str) and GENERATION.fullmatch(first)

    assert ws.refresh(NOW + timedelta(hours=1)).changed == 0
    assert generation_of(ws.briefings) == first

    ws.values[date(2026, 11, 12)]["net_sales"] += 98_765.43
    ws.save()
    assert ws.refresh(NOW + timedelta(hours=2)).changed == 1
    assert generation_of(ws.briefings) == first

    ws.briefings.unlink()
    ws.refresh(NOW + timedelta(hours=3))
    second = generation_of(ws.briefings)
    assert isinstance(second, str) and GENERATION.fullmatch(second)
    assert second != first


def _cursors(client: Client) -> dict[str, str]:
    """A mid-walk, a final (resume) and a mid since-walk cursor."""
    first = client.get("/v1/briefings?limit=7")
    assert first["has_more"] is True
    full = client.get("/v1/briefings?limit=100")
    assert full["has_more"] is False
    since = client.get("/v1/briefings?since=2026-11-01&limit=3")
    assert since["has_more"] is True
    return {
        "mid": first["next_cursor"],
        "final": full["next_cursor"],
        "since": since["next_cursor"],
    }


@needs_flock
def test_cursors_from_before_a_rebuild_are_invalid(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    with serving(ws) as client:
        cursors = _cursors(client)
        ws.briefings.unlink()
        ws.refresh(NOW + timedelta(hours=1))
        for name, cursor in cursors.items():
            response = client.error(
                "GET", cursor_path(cursor), API_TOKEN, 400, "invalid_cursor"
            )
            assert response.status == 400, name
        # A fresh walk works, and its cursors do.
        fresh = _cursors(client)
        for cursor in fresh.values():
            client.get(cursor_path(cursor))


@needs_flock
def test_cursors_survive_a_restart_and_an_unchanged_refresh(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    with serving(ws) as client:
        cursors = _cursors(client)
    assert ws.refresh(NOW + timedelta(hours=1)).changed == 0
    with serving(ws) as client:
        for cursor in cursors.values():
            client.get(cursor_path(cursor))
        assert client.get(cursor_path(cursors["final"]))["items"] == []


@needs_flock
@pytest.mark.parametrize(
    "generation", [5, "x", None, ["abcdefgh"], "a" * 65, "bad g!!!x"]
)
def test_cursor_with_a_malformed_generation_is_invalid(
    built_ws: Workspace, generation: Any
):
    cursor = raw_cursor({"v": 1, "p": ["", ""], "s": None, "h": None, "g": generation})
    with serving(built_ws) as client:
        client.error("GET", cursor_path(cursor), API_TOKEN, 400, "invalid_cursor")


@needs_flock
def test_cursor_without_a_generation_is_invalid(built_ws: Workspace):
    # Cursors without a generation were never released: no compatibility path.
    cursor = raw_cursor({"v": 1, "p": ["", ""], "s": None, "h": None})
    with serving(built_ws) as client:
        client.error("GET", cursor_path(cursor), API_TOKEN, 400, "invalid_cursor")


@needs_flock
def test_file_without_generation_is_unavailable_then_healed(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    ws = Workspace(tmp_path)
    ws.build()
    doc = json.loads(ws.briefings.read_text(encoding="utf-8"))
    del doc["generation"]
    ws.briefings.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    with serving(ws) as client:
        client.error(
            "GET", "/v1/briefings?limit=100", API_TOKEN, 503, "briefings_unavailable"
        )
        capsys.readouterr()
        result = ws.refresh(NOW + timedelta(hours=1))
        err = capsys.readouterr().err
        assert str(ws.briefings) in err and "rebuild" in err
        assert result.changed == len(NIGHTS)
        assert result.tombstones == 0
        generation = generation_of(ws.briefings)
        assert isinstance(generation, str) and GENERATION.fullmatch(generation)
        stamps = {item["updated_at"] for item in ws.stored().values()}
        assert stamps.isdisjoint(item["updated_at"] for item in doc["briefings"])
        data = client.get("/v1/briefings?limit=100")
        assert len(data["items"]) == len(NIGHTS)


# --------------------------------------------------------------------------
# 4. The refresh lock


@needs_flock
def test_refresh_creates_a_private_lock_file(tmp_path: Path):
    ws = Workspace(tmp_path)
    old = os.umask(0o000)
    try:
        ws.refresh()
    finally:
        os.umask(old)
    lock = ws.briefings.with_name(ws.briefings.name + ".lock")
    assert lock.is_file()
    assert lock.parent == ws.briefings.parent
    assert lock.stat().st_mode & 0o077 == 0
    assert lock.stat().st_mode & 0o777 == 0o600


@needs_flock
def test_refresh_tightens_a_loose_lock_file(tmp_path: Path):
    ws = Workspace(tmp_path)
    lock = ws.briefings.with_name(ws.briefings.name + ".lock")
    lock.write_bytes(b"")
    lock.chmod(0o666)
    ws.refresh()
    assert lock.stat().st_mode & 0o077 == 0


@pytest.mark.skipif(fcntl is None, reason="needs POSIX fcntl.flock")
def test_refresh_waits_for_the_lock(tmp_path: Path):
    assert fcntl is not None
    ws = Workspace(tmp_path)
    lock = ws.briefings.with_name(ws.briefings.name + ".lock")
    handle = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    errors: list[BaseException] = []

    def target() -> None:
        try:
            ws.refresh()
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=target, daemon=True)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive()
        assert not ws.briefings.exists()
    finally:
        os.close(handle)  # releases the lock
    thread.join(timeout=30)
    assert not thread.is_alive()
    assert errors == []
    assert ws.briefings.is_file()
    assert len(ws.stored()) == len(NIGHTS)


@needs_flock
def test_missing_ledger_creates_nothing(tmp_path: Path):
    target = tmp_path / "out" / "deeper" / "briefings.json"
    with pytest.raises(OSError):
        refresh_briefings(
            tmp_path / "nope.jsonl", tmp_path / "m.json", target, entity=ENTITY
        )
    assert not target.exists()
    assert not target.with_name(target.name + ".lock").exists()
    assert not target.parent.exists()
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------
# 5. Shared coverage


def test_api_reuses_the_coverage_reader():
    assert api.read_reviews is coverage.read_reviews


@pytest.mark.parametrize(
    "content",
    [b"\xff\xfe", b"{ not json", b"[]", b'{"reviews": "x"}', b"", b"\xff{}"],
)
def test_read_reviews_unknown_for_a_bad_manifest(tmp_path: Path, content: bytes):
    manifest = tmp_path / "m.json"
    manifest.write_bytes(content)
    assert coverage.read_reviews(manifest) is None
    assert api.read_reviews(manifest) is None


def test_read_reviews_missing_and_empty(tmp_path: Path):
    assert coverage.read_reviews(tmp_path / "absent.json") is None
    manifest = tmp_path / "m.json"
    manifest.write_text('{"reviews": []}', encoding="utf-8")
    assert coverage.read_reviews(manifest) == {}


@needs_flock
def test_refresh_with_a_non_utf8_manifest_succeeds(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.manifest.write_bytes(b"\xff\xfe")
    result = ws.refresh()
    assert result.changed == len(NIGHTS)
    body = ws.by_date()["2026-11-03"]["body_markdown"]
    assert "- Nights in review this month: unknown" in body


def test_count_flagged_nights():
    start, end = date(2026, 11, 1), date(2026, 11, 10)
    assert coverage.count_flagged_nights(None, set(), start, end) is None
    reviews = {
        date(2026, 10, 31): ("before",),
        date(2026, 11, 1): ("missing_total_covers",),  # start, in ledger
        date(2026, 11, 5): ("primary_without_operational_data", "extra"),
        date(2026, 11, 10): ("missing_total_covers",),  # end, not in ledger
        date(2026, 11, 11): ("after",),
    }
    ledger = {date(2026, 11, d) for d in (1, 2, 3, 4)} | {date(2026, 10, 31)}
    counts = coverage.count_flagged_nights(reviews, ledger, start, end)
    assert counts is not None
    assert (counts.in_review, counts.missing) == (1, 2)
    assert counts.reasons == {
        "extra": 1,
        "missing_total_covers": 2,
        "primary_without_operational_data": 1,
    }
    empty = coverage.count_flagged_nights({}, ledger, start, end)
    assert empty is not None
    assert (empty.in_review, empty.missing, empty.reasons) == (0, 0, {})


def test_writer_and_cli_do_not_load_the_server():
    code = (
        "import sys, restaurantos.briefings, restaurantos.__main__; "
        "loaded = [m for m in ('restaurantos.api', 'http.server') "
        "if m in sys.modules]; "
        "assert not loaded, loaded"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


# --------------------------------------------------------------------------
# 6. Wording


OVERCLAIMS = (
    re.compile(r"accounted for", re.IGNORECASE),
    re.compile(r"\b(?:is|are) complete\b", re.IGNORECASE),
    re.compile(r"\bnights? complete\b", re.IGNORECASE),
)


@needs_flock
def test_no_briefing_claims_completeness(built_ws: Workspace):
    for item in built_ws.by_date().values():
        for field in ("title", "summary", "body_markdown"):
            for pattern in OVERCLAIMS:
                assert not pattern.search(item[field]), (item["date"], field)


@needs_flock
def test_high_confidence_says_nothing_is_flagged(built_ws: Workspace):
    item = built_ws.by_date()["2026-11-03"]
    assert "confidence:high" in item["tags"]
    highs = [
        line
        for line in item["body_markdown"].splitlines()
        if line.startswith("**Confidence:** High")
    ]
    assert highs
    for stored in built_ws.by_date().values():
        for line in stored["body_markdown"].splitlines():
            if line.startswith("**Confidence:** High"):
                assert "flagged" in line, (stored["date"], line)


# --------------------------------------------------------------------------
# 7. The default briefings path


def test_default_briefings_path_matches_the_nightly(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    calls, _ = run_nightly(monkeypatch)
    capsys.readouterr()
    command = calls[1]
    history = Path(command[command.index("--history") + 1])
    briefings = Path(command[command.index("--briefings") + 1])
    fonda = nightly_root / "restaurantos" / "fonda"
    assert history == fonda / "nightly-history.jsonl"
    assert briefings == fonda / "briefings.json"

    monkeypatch.setenv("ATLAS_API_TOKEN", API_TOKEN)
    monkeypatch.delenv("ATLAS_BRIEFINGS_TOKEN", raising=False)
    config = api.config_from_env(history, fonda / "nightly-manifest.json")
    assert config.briefings_path is None
    assert config.resolved_briefings_path == history.parent / "briefings.json"
    assert config.resolved_briefings_path == briefings

    # The systemd unit serves the default: no --briefings, same --history.
    lines = SERVICE_FILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("ExecStart="))
    joined = ""
    for line in lines[start:]:
        if line.rstrip().endswith("\\"):
            joined += line.rstrip()[:-1] + " "
            continue
        joined += line
        break
    argv = shlex.split(joined.removeprefix("ExecStart="))
    assert "serve" in argv
    assert "--briefings" not in argv
    assert not any(arg.startswith("--briefings=") for arg in argv)
    home = str(nightly_root.parent)
    unit_history = Path(argv[argv.index("--history") + 1].replace("%h", home))
    assert unit_history == history
    assert unit_history.parent / "briefings.json" == briefings


def test_serve_defaults_are_shared_with_the_api():
    assert cli_module.DEFAULT_HOST == api.DEFAULT_HOST == api_defaults.DEFAULT_HOST
    assert cli_module.DEFAULT_PORT == api.DEFAULT_PORT == api_defaults.DEFAULT_PORT


@needs_flock
def test_bid_helper_matches_the_feed(built_ws: Workspace):
    """Sanity: the shared fixture holds the expected ids."""
    assert set(built_ws.stored()) == {bid(night) for night in NIGHTS}


@needs_flock
def test_unchanged_refresh_tightens_a_loosened_briefings_file(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    before = ws.briefings.read_bytes()
    ws.briefings.chmod(0o644)
    assert ws.refresh(NOW + timedelta(hours=1)).changed == 0
    assert ws.briefings.read_bytes() == before
    assert ws.briefings.stat().st_mode & 0o777 == 0o600
