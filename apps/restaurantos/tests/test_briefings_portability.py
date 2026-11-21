"""Portability of the CLI, the nightly time limit and the refresh's lock order.

The CLI must keep working where ``fcntl`` does not exist (a Windows
development machine): only ``briefings-refresh`` loads the briefings writer,
and it says plainly that it needs a POSIX host. The host is simulated by
putting ``None`` in ``sys.modules['fcntl']``. All data is synthetic
(``test_briefings``).
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import restaurantos
from _posix import needs_flock
from restaurantos.briefings import PosixHostRequiredError, refresh_briefings
from test_briefings import ENTITY, NOV, ROOT, Workspace, odd, run_cli
from test_briefings_hardening import nightly_root, run_nightly

try:
    import fcntl
except ImportError:  # not a POSIX host
    fcntl = None  # type: ignore[assignment]

__all__ = ["nightly_root"]  # a fixture the nightly tests use


APP = ROOT / "apps" / "restaurantos"
# A child prelude that makes this interpreter look like a host without POSIX
# file locking: fcntl cannot be imported, nor the os attributes Windows lacks.
NO_POSIX = (
    "import os, sys\n"
    "sys.modules['fcntl'] = None\n"
    "for _name in ('O_CLOEXEC', 'fchmod', 'fchown'):\n"
    "    if hasattr(os, _name):\n"
    "        delattr(os, _name)\n"
)


def run_without_posix(code: str) -> subprocess.CompletedProcess[str]:
    path = os.pathsep.join(
        [str(APP / "src"), str(ROOT / "packages" / "atlas-core" / "src")]
    )
    env = {**os.environ, "PYTHONPATH": path}
    return subprocess.run(
        [sys.executable, "-c", NO_POSIX + code],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def run_cli_without_posix(*argv: str) -> subprocess.CompletedProcess[str]:
    return run_without_posix(
        "import runpy\n"
        f"sys.argv = ['restaurantos', *{list(argv)!r}]\n"
        "try:\n"
        "    runpy.run_module('restaurantos', run_name='__main__', alter_sys=True)\n"
        "finally:\n"
        "    assert sys.modules.get('fcntl') is None\n"
    )


# --------------------------------------------------------------------------
# 1. The CLI on a host without fcntl


@pytest.mark.parametrize(
    "module",
    ["restaurantos.__main__", "restaurantos.briefings", "restaurantos.briefings_feed"],
)
def test_modules_import_without_fcntl(module: str):
    # sys.modules['fcntl'] = None makes `import fcntl` fail (NO_POSIX).
    run = run_without_posix(
        f"import importlib\nimportlib.import_module({module!r})\n"
        "if 'restaurantos.briefings' in sys.modules:\n"
        f"    assert {module!r} != 'restaurantos.__main__', 'loaded the writer'\n"
    )
    assert run.returncode == 0, run.stderr


def test_main_does_not_load_the_writer_in_process(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(sys.modules, "fcntl", None)  # type: ignore[arg-type]
    monkeypatch.delitem(sys.modules, "restaurantos.__main__", raising=False)
    monkeypatch.delitem(sys.modules, "restaurantos.briefings", raising=False)
    monkeypatch.delattr(restaurantos, "__main__", raising=False)
    monkeypatch.delattr(restaurantos, "briefings", raising=False)
    importlib.import_module("restaurantos.__main__")
    assert "restaurantos.briefings" not in sys.modules
    writer = importlib.import_module("restaurantos.briefings")
    assert writer.refresh_briefings is not None


def test_other_commands_run_without_fcntl(tmp_path: Path):
    ws = Workspace(tmp_path)
    run = run_cli_without_posix(
        "operating-brief",
        "--history",
        str(ws.history),
        "--start",
        "2026-11-01",
        "--end",
        "2026-11-12",
        "--entity",
        ENTITY,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip()
    help_run = run_cli_without_posix("--help")
    assert help_run.returncode == 0, help_run.stderr
    assert "briefings-refresh" in help_run.stdout


def test_briefings_refresh_without_fcntl_needs_a_posix_host(tmp_path: Path):
    ws = Workspace(tmp_path)
    run = run_cli_without_posix(
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
    lines = [line for line in run.stderr.splitlines() if line.strip()]
    assert run.returncode != 0
    assert len(lines) == 1, run.stderr
    assert "POSIX host" in lines[0]
    assert "Traceback" not in run.stderr
    assert "briefings=" not in run.stdout
    assert not ws.briefings.exists()
    assert not ws.briefings.with_name(ws.briefings.name + ".lock").exists()


def test_refresh_without_fcntl_raises_before_creating_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    ws = Workspace(tmp_path)
    target = tmp_path / "out" / "briefings.json"
    monkeypatch.setitem(sys.modules, "fcntl", None)  # type: ignore[arg-type]
    with pytest.raises(PosixHostRequiredError, match="POSIX host"):
        refresh_briefings(ws.history, ws.manifest, target, entity=ENTITY)
    assert not (tmp_path / "out").exists()


def test_cli_refresh_without_fcntl_exits_with_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    ws = Workspace(tmp_path)
    monkeypatch.setitem(sys.modules, "fcntl", None)  # type: ignore[arg-type]
    with pytest.raises(SystemExit) as exit_:
        run_cli(
            monkeypatch,
            "briefings-refresh",
            "--history",
            str(ws.history),
            "--manifest",
            str(ws.manifest),
            "--briefings",
            str(ws.briefings),
        )
    assert exit_.value.code == 1
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1 and "POSIX host" in lines[0], captured.err
    assert captured.out == ""
    assert not ws.briefings.exists()


# --------------------------------------------------------------------------
# 2. The ledger is read under the lock


@needs_flock
def test_refresh_that_waited_for_the_lock_reads_the_current_ledger(tmp_path: Path):
    assert fcntl is not None
    ws = Workspace(tmp_path)
    first = ws.refresh()
    assert first.changed == first.briefings
    lock = ws.briefings.with_name(ws.briefings.name + ".lock")
    handle = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    results: list[Any] = []
    errors: list[BaseException] = []

    def target() -> None:
        try:
            results.append(ws.refresh())
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=target, daemon=True)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        thread.start()
        time.sleep(1.0)
        assert thread.is_alive()
        # Rewrite the latest night while the refresh waits for the lock.
        latest = NOV[-1]
        ws.values[latest]["net_sales"] = odd(
            round(ws.values[latest]["net_sales"] * 1.37, 2)
        )
        ws.save()
    finally:
        os.close(handle)  # releases the lock
    thread.join(timeout=60)
    assert not thread.is_alive()
    assert errors == []
    assert len(results) == 1
    assert results[0].changed == 1
    assert ws.refresh().changed == 0


# --------------------------------------------------------------------------
# 3. A ledger that exists but cannot be read is reported as it is


@needs_flock
def test_history_that_is_a_directory_is_reported_as_one(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.history.unlink()
    ws.history.mkdir()
    target = tmp_path / "out" / "briefings.json"
    with pytest.raises(IsADirectoryError):
        refresh_briefings(ws.history, ws.manifest, target, entity=ENTITY)
    assert not (tmp_path / "out").exists()


@needs_flock
def test_cli_history_directory_is_not_reported_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    ws = Workspace(tmp_path)
    ws.history.unlink()
    ws.history.mkdir()
    with pytest.raises(SystemExit):
        run_cli(
            monkeypatch,
            "briefings-refresh",
            "--history",
            str(ws.history),
            "--manifest",
            str(ws.manifest),
            "--briefings",
            str(ws.briefings),
        )
    err = capsys.readouterr().err
    assert "Is a directory" in err
    assert "No such file" not in err
    assert not ws.briefings.exists()


@needs_flock
@pytest.mark.skipif(
    not hasattr(os, "geteuid") or os.geteuid() == 0,
    reason="root stats through mode 000",
)
def test_history_that_cannot_be_stated_is_a_permission_error(tmp_path: Path):
    (tmp_path / "ledger").mkdir()
    ws = Workspace(tmp_path / "ledger")
    target = tmp_path / "out" / "briefings.json"
    ws.root.chmod(0)
    try:
        with pytest.raises(PermissionError):
            refresh_briefings(ws.history, ws.manifest, target, entity=ENTITY)
    finally:
        ws.root.chmod(0o700)
    assert not (tmp_path / "out").exists()


# --------------------------------------------------------------------------
# 4. The nightly briefings step has a time limit


def test_nightly_briefings_step_has_a_timeout(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch
):
    calls, kwargs_seen = run_nightly(monkeypatch)
    assert len(calls) == 2
    limit = kwargs_seen[1].get("timeout")
    assert isinstance(limit, int | float) and 60 <= limit <= 900
    assert "timeout" not in kwargs_seen[0]


def test_nightly_survives_a_timed_out_briefings_step(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    def times_out(command: list[str]) -> Any:
        raise subprocess.TimeoutExpired(command, 300)

    calls, _ = run_nightly(monkeypatch, times_out)
    assert len(calls) == 2
    lines = [line for line in capsys.readouterr().err.splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert "briefings-refresh" in lines[0]
    assert "timed out after 300 seconds" in lines[0]
    assert "the ledger refresh succeeded" in lines[0]
