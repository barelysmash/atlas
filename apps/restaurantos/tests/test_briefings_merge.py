"""The briefings feed against upstream main at 151fbf6.

Partial nights (filled from an approved point-of-sale summary: net sales and
voids only) in briefings and in the shared coverage module, the pre-lock
regular-file check, the nightly entry point's upstream flags and its 600 s
briefings timeout, and the CLI's upstream commands on a host without
``fcntl``. All data is synthetic (``test_briefings``).
"""

from __future__ import annotations

import ast
import json
import os
import runpy
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import restaurantos.api as api
import restaurantos.coverage as coverage
from _posix import needs_flock
from restaurantos.briefings import refresh_briefings, render_briefing
from restaurantos.coverage import count_partial_nights, read_partial_nights
from restaurantos.nightly_history import read_history_jsonl
from test_briefings import (
    ENTITY,
    NIGHTLY_SCRIPT,
    REVIEWS,
    Workspace,
    write_ledger,
)
from test_briefings_hardening import nightly_root
from test_briefings_portability import APP, run_without_posix

__all__ = ["nightly_root"]  # a fixture the nightly tests use

LACKING = (
    "Covers",
    "Average check",
    "Sales per labor hour",
    "Labor cost (share of sales)",
    "Reservation share",
    "Comp rate",
)
CARRIED = ("Net sales", "Void rate")
EXPLAIN = ("point-of-sale summary", "only net sales and voids are known")
PARTIAL = ("2026-10-27", "2026-11-09")


def make_partial(ws: Workspace, nights: tuple[str, ...]) -> None:
    """Keep only net sales and voids on the given nights, as upstream does."""
    for night in nights:
        day = date.fromisoformat(night)
        ws.values[day] = {m: ws.values[day][m] for m in ("net_sales", "voids")}
    write_ledger(ws.history, ws.values)


def write_manifest_with(path: Path, partial: list[str] | None) -> None:
    payload: dict[str, Any] = {
        "reviews": [
            {"service_date": day, "reasons": reasons}
            for day, reasons in sorted(REVIEWS.items())
        ],
    }
    if partial is not None:
        payload["partial_nights"] = partial
    path.write_text(json.dumps(payload), encoding="utf-8")


def render_all(ws: Workspace) -> dict[str, dict[str, Any]]:
    """Every night's content, as the writer renders it (no lock needed)."""
    records = [r for r in read_history_jsonl(ws.history) if r.entity == ENTITY]
    nights = {date.fromisoformat(r.period) for r in records}
    reviews = coverage.read_reviews(ws.manifest)
    partial = read_partial_nights(ws.manifest)
    return {
        night.isoformat(): render_briefing(
            records, ENTITY, night, nights, reviews, partial
        )
        for night in sorted(nights)
    }


def section(body: str, prefix: str) -> list[str]:
    """The lines of the '### ' finding whose title starts with ``prefix``."""
    lines: list[str] = []
    inside = False
    for line in body.splitlines():
        if line.startswith("### ") or line.startswith("## "):
            inside = line.startswith(f"### {prefix}")
            continue
        if inside:
            lines.append(line)
    return lines


def bullet(lines: list[str], label: str) -> str:
    found = [line for line in lines if line.startswith(f"- {label}: ")]
    assert len(found) == 1, (label, lines)
    return found[0].removeprefix(f"- {label}: ")


def confidence(lines: list[str]) -> str:
    found = [line for line in lines if line.startswith("**Confidence:**")]
    assert len(found) == 1, lines
    return found[0]


@pytest.fixture
def partial_ws(tmp_path: Path) -> Workspace:
    ws = Workspace(tmp_path)
    make_partial(ws, PARTIAL)
    write_manifest_with(ws.manifest, list(PARTIAL))
    return ws


# --------------------------------------------------------------------------
# 1. Partial nights in briefings


@pytest.mark.parametrize(
    ("day", "partial_name"),
    [
        ("2026-11-03", "Tuesday, October 27"),  # the week-earlier night
        ("2026-11-09", "Monday, November 9"),  # the night itself
    ],
)
def test_briefings_partial_nights_show_no_comparison_for_what_they_lack(
    partial_ws: Workspace, day: str, partial_name: str
):
    # Manifest: {"partial_nights": ["2026-10-27", "2026-11-09"]}.
    content = render_all(partial_ws)[day]
    week = section(content["body_markdown"], "Against")
    for label in LACKING:
        assert bullet(week, label) == "no comparison available", label
    for label in CARRIED:
        assert bullet(week, label) != "no comparison available", label
    explained = [line for line in week if all(part in line.lower() for part in EXPLAIN)]
    assert len(explained) == 1
    assert partial_name in explained[0]
    assert not explained[0].startswith(("- ", "**"))
    level = confidence(week)
    assert level.startswith("**Confidence:** Medium")
    assert "partial" in level and "point-of-sale" not in level
    assert "confidence:high" not in content["tags"]


def test_a_partial_week_earlier_night_turns_high_into_medium(partial_ws: Workspace):
    content = render_all(partial_ws)["2026-11-03"]
    assert "confidence:medium" in content["tags"]
    overall = confidence(section(content["body_markdown"], "Data coverage"))
    assert overall.startswith("**Confidence:** Medium")
    assert "partial" in overall


def test_a_night_without_partial_comparison_compares_every_headline(
    partial_ws: Workspace,
):
    content = render_all(partial_ws)["2026-11-10"]
    body = content["body_markdown"]
    week = section(body, "Against")
    assert not any("point-of-sale" in line for line in week)
    for label in (*LACKING, *CARRIED):
        assert bullet(week, label) != "no comparison available", label
    # November to date holds the partial 11-09: the month cannot be High.
    month = section(body, "November")
    assert not confidence(month).startswith("**Confidence:** High")
    assert "partial" in confidence(month)


@pytest.mark.parametrize(
    ("day", "this_month", "comparison"),
    [
        ("2026-10-15", "0", "0"),
        ("2026-10-27", "1", "0"),
        ("2026-11-03", "0", "0"),
        ("2026-11-09", "1", "0"),
        ("2026-11-12", "1", "0"),
        ("2026-10-31", "1", "0"),
    ],
)
def test_coverage_counts_partial_nights_per_window(
    partial_ws: Workspace, day: str, this_month: str, comparison: str
):
    lines = section(render_all(partial_ws)[day]["body_markdown"], "Data coverage")
    assert f"- Partial nights this month: {this_month}" in lines
    assert f"- Partial nights, comparison days: {comparison}" in lines


def test_partial_night_in_the_comparison_month_is_counted(tmp_path: Path):
    ws = Workspace(tmp_path)
    make_partial(ws, ("2026-10-02",))
    write_manifest_with(ws.manifest, ["2026-10-02"])
    lines = section(render_all(ws)["2026-11-03"]["body_markdown"], "Data coverage")
    assert "- Partial nights this month: 0" in lines
    assert "- Partial nights, comparison days: 1" in lines
    assert "partial" in confidence(lines)


def test_both_compared_nights_partial_are_named_in_one_line(tmp_path: Path):
    ws = Workspace(tmp_path)
    make_partial(ws, ("2026-10-20", "2026-10-27"))
    write_manifest_with(ws.manifest, ["2026-10-20", "2026-10-27"])
    week = section(render_all(ws)["2026-10-27"]["body_markdown"], "Against")
    explained = [line for line in week if "point-of-sale summary" in line]
    assert explained == [
        "October 27 and October 20 were filled from a "
        "point-of-sale summary, so only net sales and voids are known."
    ]
    for label in LACKING:
        assert bullet(week, label) == "no comparison available"


def test_partial_nights_are_not_inferred_from_the_ledger(tmp_path: Path):
    # A night with net sales and voids only, but not listed as partial: the
    # manifest is the only source (as for /v1/operating-summary), so no line.
    ws = Workspace(tmp_path)
    make_partial(ws, ("2026-10-27",))
    write_manifest_with(ws.manifest, [])
    week = section(render_all(ws)["2026-11-03"]["body_markdown"], "Against")
    assert not any("point-of-sale" in line for line in week)


def test_unknown_partial_nights_read_unknown_and_are_never_high(tmp_path: Path):
    ws = Workspace(tmp_path)
    write_manifest_with(ws.manifest, None)  # a manifest from before the upgrade
    for day, content in render_all(ws).items():
        lines = section(content["body_markdown"], "Data coverage")
        assert "- Partial nights this month: unknown" in lines, day
        assert "- Partial nights, comparison days: unknown" in lines, day
        assert "confidence:high" not in content["tags"], day
    week = section(render_all(ws)["2026-11-03"]["body_markdown"], "Against")
    assert "partial nights are unknown" in confidence(week)


def test_empty_partial_nights_keep_high(tmp_path: Path):
    ws = Workspace(tmp_path)
    write_manifest_with(ws.manifest, [])
    content = render_all(ws)["2026-11-03"]
    assert "confidence:high" in content["tags"]
    overall = confidence(section(content["body_markdown"], "Data coverage"))
    assert "flagged" in overall


def test_partial_nights_never_make_a_briefing_low_by_themselves(
    partial_ws: Workspace,
):
    for day in ("2026-11-03", "2026-11-10"):
        assert "confidence:low" not in render_all(partial_ws)[day]["tags"], day


def test_partial_bodies_stay_short_and_structured(partial_ws: Workspace):
    for day, content in render_all(partial_ws).items():
        body = content["body_markdown"]
        assert len(body.split()) <= 250, day
        findings = body.split("\n### ")[1:]
        assert len(findings) == 3, day
        for finding in findings:
            assert finding.count("**Confidence:**") == 1, day


@needs_flock
def test_refresh_reads_partial_nights_from_the_manifest(partial_ws: Workspace):
    partial_ws.refresh()
    items = {
        item["date"]: item
        for item in json.loads(partial_ws.briefings.read_text("utf-8"))["briefings"]
    }
    week = section(items["2026-11-03"]["body_markdown"], "Against")
    assert bullet(week, "Covers") == "no comparison available"
    assert any("point-of-sale summary" in line for line in week)
    # A manifest change alone (the night is no longer listed) is a content
    # change: the briefing gets a new updated_at on the next refresh.
    write_manifest_with(partial_ws.manifest, [])
    result = partial_ws.refresh()
    assert result.changed > 0


# --------------------------------------------------------------------------
# 2. The shared coverage module


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("{ not json", None),
        ("[]", None),
        ("{}", None),
        ('{"partial_nights": "2026-11-09"}', None),
        ('{"partial_nights": []}', set()),
        (
            '{"partial_nights": ["2026-11-09", "junk", 7, null, "2026-10-27"]}',
            {date(2026, 11, 9), date(2026, 10, 27)},
        ),
    ],
)
def test_read_partial_nights(tmp_path: Path, text: str | None, expected: Any):
    manifest = tmp_path / "nightly-manifest.json"
    if text is not None:
        manifest.write_text(text, encoding="utf-8")
    assert read_partial_nights(manifest) == expected


def test_read_partial_nights_treats_a_non_utf8_manifest_as_unknown(tmp_path: Path):
    manifest = tmp_path / "nightly-manifest.json"
    manifest.write_bytes(b"\xff{}")
    assert read_partial_nights(manifest) is None


def test_count_partial_nights_is_inclusive_and_none_when_unknown():
    partial = {date(2026, 11, 1), date(2026, 11, 9), date(2026, 12, 1)}
    assert count_partial_nights(None, date(2026, 11, 1), date(2026, 11, 30)) is None
    assert count_partial_nights(set(), date(2026, 11, 1), date(2026, 11, 30)) == 0
    assert count_partial_nights(partial, date(2026, 11, 1), date(2026, 11, 9)) == 2
    assert count_partial_nights(partial, date(2026, 11, 2), date(2026, 11, 8)) == 0


def test_api_reuses_the_shared_partial_night_helpers():
    assert api.read_partial_nights is coverage.read_partial_nights
    source = (APP / "src" / "restaurantos" / "api.py").read_text(encoding="utf-8")
    defined = {
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef)
    }
    assert not defined & {"read_partial_nights", "_partial_count", "read_reviews"}
    tree = ast.parse(
        (APP / "src" / "restaurantos" / "coverage.py").read_text(encoding="utf-8")
    )
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not imported & {"restaurantos.api", "http.server", "socketserver"}


def test_operating_summary_counts_partial_nights_through_the_shared_helper(
    partial_ws: Workspace,
):
    records = read_history_jsonl(partial_ws.history)
    summary = api.operating_summary(
        records,
        {"entity": ENTITY},
        reviews=coverage.read_reviews(partial_ws.manifest),
        partial_nights=read_partial_nights(partial_ws.manifest),
    )
    assert summary["current"]["nights_partial"] == 1  # 11-09 in Nov 1-12
    assert summary["previous"]["nights_partial"] == 0  # Oct 1-12
    unknown = api.operating_summary(records, {"entity": ENTITY})
    assert unknown["current"]["nights_partial"] is None


# --------------------------------------------------------------------------
# 3. The history path must be a regular file, checked before the lock


@needs_flock
def test_history_that_is_a_fifo_is_refused_before_the_lock(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.history.unlink()
    os.mkfifo(ws.history)
    target = tmp_path / "out" / "briefings.json"
    with pytest.raises(OSError, match="not a regular file"):
        refresh_briefings(ws.history, ws.manifest, target, entity=ENTITY)
    assert not (tmp_path / "out").exists()


def test_cli_history_fifo_is_one_line_and_does_not_block(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.history.unlink()
    os.mkfifo(ws.history)
    target = tmp_path / "out" / "briefings.json"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(APP / "src"), str(APP.parents[1] / "packages" / "atlas-core" / "src")]
        ),
    }
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "restaurantos",
            "briefings-refresh",
            "--history",
            str(ws.history),
            "--manifest",
            str(ws.manifest),
            "--briefings",
            str(target),
            "--entity",
            ENTITY,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert run.returncode != 0
    lines = run.stderr.strip().splitlines()
    assert len(lines) == 1, run.stderr
    assert "regular file" in lines[0]
    assert "No such file" not in lines[0]
    assert "Traceback" not in run.stderr
    assert run.stdout == ""
    assert not (tmp_path / "out").exists()


@needs_flock
def test_history_symlink_to_a_regular_file_is_followed(tmp_path: Path):
    ws = Workspace(tmp_path)
    link = tmp_path / "ledger-link.jsonl"
    link.symlink_to(ws.history)
    result = refresh_briefings(link, ws.manifest, ws.briefings, entity=ENTITY)
    assert result.briefings > 0


# --------------------------------------------------------------------------
# 4. The nightly entry point keeps upstream's flags and a 600 s briefings step


def run_nightly_capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    calls: list[tuple[Any, ...]] = []

    def fake(command: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append(([str(part) for part in command], kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(SystemExit) as exit_:
        runpy.run_path(str(NIGHTLY_SCRIPT), run_name="__main__")
    assert exit_.value.code == 0
    return calls


def test_nightly_timeout_is_600_seconds():
    namespace = runpy.run_path(str(NIGHTLY_SCRIPT))
    assert namespace["BRIEFINGS_TIMEOUT_SECONDS"] == 600


def test_nightly_passes_upstream_flags_when_present(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    fonda = nightly_root / "restaurantos" / "fonda"
    (fonda / "toast-approved").mkdir()
    (fonda / "goals.json").write_text("{}", encoding="utf-8")
    (fonda / "service-date-overrides.json").write_text("{}", encoding="utf-8")
    calls = run_nightly_capture(monkeypatch)
    capsys.readouterr()
    assert len(calls) == 2
    (first, first_kwargs), (second, second_kwargs) = calls
    assert first[3] == "gmail-nightly-refresh"
    assert first[first.index("--approved-imports") + 1] == str(fonda / "toast-approved")
    assert first[first.index("--goals") + 1] == str(fonda / "goals.json")
    assert first[first.index("--overrides") + 1] == str(
        fonda / "service-date-overrides.json"
    )
    assert first_kwargs == {"check": True}
    assert second[3] == "briefings-refresh"
    assert second_kwargs == {"check": True, "timeout": 600}


def test_nightly_omits_upstream_flags_when_absent(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    calls = run_nightly_capture(monkeypatch)
    capsys.readouterr()
    first = calls[0][0]
    for flag in ("--approved-imports", "--goals", "--overrides"):
        assert flag not in first
    assert calls[-1][0][3] == "briefings-refresh"


# --------------------------------------------------------------------------
# 5. Upstream's CLI commands without fcntl


@pytest.mark.parametrize(
    ("command", "flags"),
    [
        ("toast-approve", ("--review-dir", "--approved-dir", "--service-date")),
        ("nightly-refresh", ("--approved-imports", "--goals", "--overrides")),
        ("gmail-nightly-refresh", ("--approved-imports", "--goals", "--overrides")),
    ],
)
def test_upstream_commands_load_neither_the_writer_nor_fcntl(
    command: str, flags: tuple[str, ...]
):
    run = run_without_posix(
        "import io, contextlib, runpy\n"
        f"sys.argv = ['restaurantos', {command!r}, '--help']\n"
        "out = io.StringIO()\n"
        "try:\n"
        "    with contextlib.redirect_stdout(out):\n"
        "        runpy.run_module(\n"
        "            'restaurantos', run_name='__main__', alter_sys=True\n"
        "        )\n"
        "except SystemExit as stop:\n"
        "    assert stop.code in (0, None), stop.code\n"
        "assert 'restaurantos.briefings' not in sys.modules, 'loaded the writer'\n"
        "assert sys.modules.get('fcntl') is None, 'loaded fcntl'\n"
        "print(out.getvalue())\n"
    )
    assert run.returncode == 0, run.stderr
    for flag in flags:
        assert flag in run.stdout, (command, flag)


def test_toast_approve_does_not_load_the_writer_in_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    monkeypatch.setitem(sys.modules, "fcntl", None)  # type: ignore[arg-type]
    monkeypatch.delitem(sys.modules, "restaurantos.briefings", raising=False)
    from restaurantos.__main__ import main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "restaurantos",
            "toast-approve",
            "--review-dir",
            str(tmp_path / "review"),
            "--approved-dir",
            str(tmp_path / "approved"),
            "--service-date",
            "2026-11-09",
        ],
    )
    with pytest.raises(SystemExit) as exit_:
        main()  # nothing staged: argparse reports it and exits 2
    assert exit_.value.code == 2
    assert "restaurantos.briefings" not in sys.modules
    capsys.readouterr()


@pytest.mark.parametrize("with_reviews", [True, False])
def test_worst_case_partial_bodies_fit_in_250_words(tmp_path: Path, with_reviews: bool):
    # Every night partial: every headline but two reads "no comparison
    # available" in both findings, the explanation names two nights, and the
    # rationales stack partial, review and coverage reasons.
    ws = Workspace(tmp_path)
    nights = tuple(night.isoformat() for night in sorted(ws.values))
    make_partial(ws, nights)
    payload: dict[str, Any] = {"partial_nights": list(nights)}
    if with_reviews:
        payload["reviews"] = [
            {"service_date": night, "reasons": ["synthetic"]}
            for night in ("2026-10-26", "2026-11-02", "2026-11-05", "2026-10-02")
        ]
    ws.manifest.write_text(json.dumps(payload), encoding="utf-8")
    for day, content in render_all(ws).items():
        assert len(content["body_markdown"].split()) <= 250, day


def test_explanation_line_is_its_own_paragraph(partial_ws: Workspace):
    # In CommonMark a plain line right after a list item continues that item;
    # the explanation must follow a blank line to render as its own paragraph.
    lines = render_all(partial_ws)["2026-11-09"]["body_markdown"].splitlines()
    index = next(i for i, line in enumerate(lines) if "point-of-sale" in line)
    assert lines[index - 1] == ""
    assert lines[index - 2].startswith("- Void rate: ")


@pytest.mark.parametrize(
    ("day", "note"),
    [
        ("2026-11-09", "this night is partial"),
        ("2026-11-03", "the week-earlier night is partial"),
    ],
)
def test_rationale_names_which_night_is_partial(
    partial_ws: Workspace, day: str, note: str
):
    body = render_all(partial_ws)[day]["body_markdown"]
    assert note in confidence(section(body, "Against"))
    assert note in confidence(section(body, "Data coverage"))
