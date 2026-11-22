"""Briefings builder: content, stability across rebuilds, privacy, CLI wiring.

Every figure here is synthetic: distinctive values with at least five integer
digits, so that any one of them (or a window total, average or rate level
built from them) showing up in a briefing is an unmistakable leak.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import runpy
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from _posix import needs_flock
from restaurantos.__main__ import main as cli_main
from restaurantos.briefings import (
    briefing_id,
    content_hash,
    phrase,
    refresh_briefings,
)
from restaurantos.briefings_feed import BriefingsStore

ENTITY = "Quillfeather Test Kitchen"
OTHER_ENTITY = "Marrowgate Synthetic Bistro"

METRICS = (
    "net_sales",
    "labor_cost",
    "labor_hours",
    "guest_count",
    "reservation_covers",
    "dining_room_covers",
    "bar_atrium_covers",
    "comps",
    "voids",
)

OCT = [date(2026, 10, d) for d in range(1, 32)]
NOV = [date(2026, 11, d) for d in (1, 2, 3, 4, 6, 7, 8, 9, 10, 12)]
NIGHTS = OCT + NOV  # 41 nights; 2026-11-05 missing (reviewed), 11-11 absent.
OTHER_NIGHTS = [date(2026, 11, 11), date(2026, 11, 13)]
REVIEWS: dict[str, list[str]] = {
    "2026-11-04": ["missing_total_covers"],  # in the ledger, in review
    "2026-11-05": ["primary_without_operational_data"],  # missing
}

NOW = datetime(2026, 11, 13, 11, 30, tzinfo=UTC)
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CONFIDENCE = re.compile(r"^\*\*Confidence:\*\* (High|Medium|Low)( — .+)?$")

ROOT = Path(__file__).resolve().parents[3]
NIGHTLY_SCRIPT = ROOT / "deploy" / "bin" / "restaurantos_nightly.py"


# --------------------------------------------------------------------------
# Synthetic ledger


def odd(value: float) -> float:
    """Force an odd integer part so values never land on round numbers."""
    whole = int(value)
    return value if whole % 2 else value + 1


def synthetic_values(seed: int = 20261117) -> dict[date, dict[str, float]]:
    rng = random.Random(seed)
    values: dict[date, dict[str, float]] = {}
    for night in NIGHTS:
        values[night] = {
            "net_sales": odd(round(rng.uniform(2_400_000, 3_900_000), 2)),
            "labor_cost": odd(round(rng.uniform(600_000, 1_000_000), 2)),
            "labor_hours": odd(round(rng.uniform(41_000, 59_000), 2)),
            "guest_count": odd(float(rng.randint(52_000, 79_000))),
            "reservation_covers": odd(float(rng.randint(21_000, 39_000))),
            "dining_room_covers": odd(float(rng.randint(30_000, 45_000))),
            "bar_atrium_covers": odd(float(rng.randint(11_000, 19_000))),
            "comps": odd(round(rng.uniform(31_000, 49_000), 2)),
            "voids": odd(round(rng.uniform(12_000, 28_000), 2)),
        }
    return values


def other_values() -> dict[date, dict[str, float]]:
    rng = random.Random(7)
    return {
        night: {m: odd(round(rng.uniform(10_000, 99_000), 2)) for m in METRICS}
        for night in OTHER_NIGHTS
    }


def write_ledger(path: Path, values: dict[date, dict[str, float]]) -> None:
    lines = []
    for entity, nights in ((ENTITY, values), (OTHER_ENTITY, other_values())):
        for night, metrics in sorted(nights.items()):
            for metric, value in metrics.items():
                lines.append(
                    json.dumps(
                        {
                            "source": "nightly_email",
                            "entity": entity,
                            "period": night.isoformat(),
                            "category": "operations",
                            "metric": metric,
                            "value": value,
                            "dimensions": {},
                            "grain": "daily",
                            "aggregation": "sum",
                        },
                        sort_keys=True,
                    )
                )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(
    path: Path,
    reviews: dict[str, list[str]],
    partial: list[str] | None = None,
) -> None:
    """The synthetic manifest; ``partial=None`` lists no partial nights."""
    path.write_text(
        json.dumps(
            {
                "service_nights": len(NIGHTS),
                "review_count": len(reviews),
                "reviews": [
                    {"service_date": day, "reasons": reasons}
                    for day, reasons in sorted(reviews.items())
                ],
                "partial_nights": sorted(partial or []),
            }
        ),
        encoding="utf-8",
    )


_BUILDS: dict[str, bytes] = {}


class Workspace:
    def __init__(self, root: Path, reviews: dict[str, list[str]] | None = None) -> None:
        self.root = root
        self.history = root / "nightly-history.jsonl"
        self.manifest = root / "nightly-manifest.json"
        self.briefings = root / "briefings.json"
        self.values = synthetic_values()
        self.reviews = dict(REVIEWS if reviews is None else reviews)
        self.save()

    def save(self) -> None:
        write_ledger(self.history, self.values)
        write_manifest(self.manifest, self.reviews)

    def refresh(self, now: datetime = NOW) -> Any:
        return refresh_briefings(
            self.history, self.manifest, self.briefings, entity=ENTITY, now=now
        )

    def build(self) -> None:
        """A first build at NOW; reuses the bytes of an identical earlier one.

        The build is deterministic, so this only saves time (a refresh of
        41 nights is slow under coverage). Tests of the first build itself
        call ``refresh`` instead.
        """
        key = json.dumps([self.reviews, self.manifest.exists()], sort_keys=True)
        if self.values != synthetic_values() or self.briefings.exists():
            self.refresh()
            return
        if key not in _BUILDS:
            self.refresh()
            _BUILDS[key] = self.briefings.read_bytes()
            return
        self.briefings.parent.mkdir(parents=True, exist_ok=True)
        self.briefings.write_bytes(_BUILDS[key])
        self.briefings.chmod(0o600)

    def stored(self) -> dict[str, dict[str, Any]]:
        raw = json.loads(self.briefings.read_text(encoding="utf-8"))
        return {item["id"]: item for item in raw["briefings"]}

    def by_date(self) -> dict[str, dict[str, Any]]:
        return {
            item["date"]: item
            for item in self.stored().values()
            if not item.get("deleted")
        }


def bid(night: date) -> str:
    digest = hashlib.sha256(ENTITY.encode("utf-8")).hexdigest()[:8]
    return f"brf_{night.isoformat()}_{digest}"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Workspace:
    """A built workspace that read-only tests share (never mutate it)."""
    ws = Workspace(tmp_path_factory.mktemp("built"))
    ws.build()
    return ws


# --------------------------------------------------------------------------
# Expected arithmetic (independent of the code under test)


def window_rows(
    values: dict[date, dict[str, float]], start: date, end: date
) -> list[dict[str, float]]:
    return [m for night, m in values.items() if start <= night <= end]


def volume_change(
    values: dict[date, dict[str, float]],
    current: tuple[date, date],
    previous: tuple[date, date],
    metric: str,
) -> float | None:
    now = [m[metric] for m in window_rows(values, *current)]
    before = [m[metric] for m in window_rows(values, *previous)]
    if not now or not before:
        return None
    if len(now) == len(before):
        a, b = sum(now), sum(before)
    else:
        a, b = sum(now) / len(now), sum(before) / len(before)
    return (a - b) / b * 100.0


def labor_share_points(
    values: dict[date, dict[str, float]],
    current: tuple[date, date],
    previous: tuple[date, date],
) -> float | None:
    def share(window: tuple[date, date]) -> float | None:
        rows = window_rows(values, *window)
        if not rows:
            return None
        return sum(r["labor_cost"] for r in rows) / sum(r["net_sales"] for r in rows)

    a, b = share(current), share(previous)
    return None if a is None or b is None else (a - b) * 100.0


def expected_phrase(change: float | None, unit: str = "%") -> str:
    if change is None:
        return "no comparison available"
    if abs(change) < 0.05:
        return "flat"
    word = "up" if change > 0 else "down"
    size = f"{abs(round(change, 1)):.1f}"
    return f"{word} {size}%" if unit == "%" else f"{word} {size} points"


def month_windows(night: date) -> tuple[tuple[date, date], tuple[date, date]]:
    start = night.replace(day=1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    aligned = min(previous_start + timedelta(days=night.day - 1), previous_end)
    return (start, night), (previous_start, aligned)


# --------------------------------------------------------------------------
# Privacy helpers (shared with test_briefings_api)

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
CURRENCY = ("$", "£", "€", "¥", "USD")


def forbidden_numbers(values: dict[date, dict[str, float]]) -> set[str]:
    """Absolute figures in every form a leak could take (no separators)."""
    forbidden: set[str] = set()

    def add(value: float) -> None:
        value = abs(value)
        whole = str(int(value))
        if len(whole) >= 5:
            forbidden.add(whole)
            forbidden.add(str(round(value)))
        forbidden.add(f"{value:.2f}")

    for nights in (values, other_values()):
        for metrics in nights.values():
            for value in metrics.values():
                add(value)
    windows: list[tuple[date, date]] = []
    for night in values:
        week = night - timedelta(days=7)
        current, previous = month_windows(night)
        windows += [(night, night), (week, week), current, previous]
    ratios = (
        ("net_sales", "guest_count", 1.0),
        ("net_sales", "labor_hours", 1.0),
        ("guest_count", "labor_hours", 1.0),
        ("labor_cost", "guest_count", 1.0),
        ("labor_cost", "net_sales", 100.0),
        ("reservation_covers", "guest_count", 100.0),
        ("comps", "net_sales", 100.0),
        ("voids", "net_sales", 100.0),
    )
    for window in set(windows):
        rows = window_rows(values, *window)
        if not rows:
            continue
        sums = {m: sum(r[m] for r in rows) for m in METRICS}
        for total in sums.values():
            add(total)
            add(total / len(rows))
        for left, right, scale in ratios:
            add(sums[left] / sums[right] * scale)
    forbidden.discard("0.00")
    return forbidden


def with_separators(forbidden: set[str]) -> set[str]:
    """The same figures with thousands separators, as a formatter writes them."""
    out: set[str] = set()
    for text in forbidden:
        whole, dot, cents = text.partition(".")
        if len(whole) >= 4:
            out.add(f"{int(whole):,}" + (dot + cents if dot else ""))
    return out


def leaks(text: str, forbidden: set[str], separated: set[str]) -> list[str]:
    squashed = text.replace(",", "")
    for space in (0x202F, 0xA0, 0x2009):  # narrow, no-break and thin spaces
        squashed = squashed.replace(chr(space), "")
    found = [value for value in forbidden if value in squashed]
    found += [value for value in separated if value in text]
    found += [symbol for symbol in CURRENCY if symbol in text]
    found += [name for name in (ENTITY, OTHER_ENTITY) if name in text]
    return sorted(found)


def stray_numbers(prose: str) -> list[str]:
    """Numbers other than one-decimal changes, days of month and years."""
    prose = ISO_DATE.sub(" ", prose)
    stray: list[str] = []
    for match in NUMBER.finditer(prose):
        token = match.group()
        after = prose[match.end() : match.end() + 7]
        if re.fullmatch(r"\d+\.\d", token) and (
            after.startswith("%") or after.startswith(" points")
        ):
            continue
        if re.fullmatch(r"\d+", token) and (
            int(token) <= 31 or 2000 <= int(token) <= 2099
        ):
            continue
        stray.append(token)
    return stray


def prose_of(item: dict[str, Any]) -> str:
    return " ".join(
        [item["title"], item["summary"], item["body_markdown"], *item["tags"]]
    )


def body_problems(body: str) -> list[str]:
    problems: list[str] = []
    lines = body.splitlines()
    if sum(1 for line in lines if line.startswith("## ")) < 3:
        problems.append("fewer than three '## ' sections")
    if not any(line.startswith("- ") for line in lines):
        problems.append("no bullets")
    if len(body.split()) > 250:
        problems.append(f"{len(body.split())} words")
    findings: list[list[str]] = []
    for line in lines:
        if line.startswith("## "):
            findings.append(["<section>"])  # a section closes the finding
        elif line.startswith("### "):
            findings.append([])
        elif findings:
            findings[-1].append(line)
    findings = [f for f in findings if f[:1] != ["<section>"]]
    if not findings:
        problems.append("no '### ' findings")
    for finding in findings:
        count = sum(1 for line in finding if line.startswith("**Confidence:**"))
        if count != 1:
            problems.append(f"a finding has {count} confidence lines")
    for line in lines:
        if line.startswith("**Confidence:**") and not CONFIDENCE.match(line):
            problems.append(f"bad confidence line {line!r}")
    return problems


# --------------------------------------------------------------------------
# Small pure functions


def test_briefing_id_hashes_the_entity_and_is_stable():
    night = date(2026, 11, 3)
    assert briefing_id(ENTITY, night) == bid(night)
    assert briefing_id(ENTITY, night) == briefing_id(ENTITY, night)
    assert briefing_id(OTHER_ENTITY, night) != bid(night)
    assert "Quillfeather" not in briefing_id(ENTITY, night)
    assert re.fullmatch(r"brf_2026-11-03_[0-9a-f]{8}", briefing_id(ENTITY, night))


@pytest.mark.parametrize(
    ("change", "direction", "unit", "expected"),
    [
        (8.24, "up", "percent", "up 8.2%"),
        (-1.4, "down", "percent", "down 1.4%"),
        (-0.3, "down", "percentage_points", "down 0.3 points"),
        (12.0, "up", "percentage_points", "up 12.0 points"),
        (0.0, "flat", "percent", "flat"),
        (None, None, "percent", "no comparison available"),
        (3.0, None, "percent", "no comparison available"),
    ],
)
def test_phrase(change, direction, unit, expected):
    assert phrase(change, direction, unit) == expected


# --------------------------------------------------------------------------
# Build and file


@needs_flock
def test_first_build_writes_one_briefing_per_night(tmp_path: Path):
    ws = Workspace(tmp_path)
    result = ws.refresh()

    assert (result.briefings, result.changed, result.tombstones) == (41, 41, 0)
    assert result.path == ws.briefings
    raw = json.loads(ws.briefings.read_text(encoding="utf-8"))
    assert raw["format"] == 1
    assert raw["figures"] == "relative_only"
    ids = [item["id"] for item in raw["briefings"]]
    assert ids == sorted(bid(night) for night in NIGHTS)  # none for OTHER_ENTITY
    for item in raw["briefings"]:
        assert item["deleted"] is False
        assert item["created_at"] == item["updated_at"] == "2026-11-13T11:30:00Z"
        assert item["content_hash"] == content_hash(item)
        assert "sections" not in item
        assert len(item["title"]) <= 80
        assert len(item["summary"]) <= 160
    assert ws.briefings.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".briefings.json.*"))  # no temp file left


@needs_flock
def test_build_creates_parent_and_mode_600_regardless_of_umask(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.briefings = tmp_path / "deeper" / "dir" / "briefings.json"
    old = os.umask(0o000)
    try:
        ws.refresh()
    finally:
        os.umask(old)
    assert ws.briefings.stat().st_mode & 0o777 == 0o600


@needs_flock
def test_entity_is_required_when_the_ledger_has_several(tmp_path: Path):
    ws = Workspace(tmp_path)
    with pytest.raises(ValueError, match="--entity"):
        refresh_briefings(ws.history, ws.manifest, ws.briefings, now=NOW)
    with pytest.raises(ValueError, match="no service nights"):
        refresh_briefings(
            ws.history, ws.manifest, ws.briefings, entity="Nobody Here", now=NOW
        )
    assert not ws.briefings.exists()


@needs_flock
def test_missing_ledger_is_an_error_and_writes_nothing(tmp_path: Path):
    target = tmp_path / "out" / "briefings.json"
    with pytest.raises(OSError):
        refresh_briefings(
            tmp_path / "nope.jsonl", tmp_path / "m.json", target, entity=ENTITY
        )
    assert not target.exists()


# --------------------------------------------------------------------------
# Stability


@needs_flock
def test_unchanged_rebuild_is_byte_identical(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    before = ws.briefings.read_bytes()
    stat = ws.briefings.stat()

    result = ws.refresh(NOW + timedelta(days=1))

    assert (result.briefings, result.changed, result.tombstones) == (41, 0, 0)
    assert ws.briefings.read_bytes() == before
    assert ws.briefings.stat().st_mtime_ns == stat.st_mtime_ns  # not rewritten


@needs_flock
def test_changing_the_latest_night_changes_only_its_briefing(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    before = ws.stored()

    ws.values[date(2026, 11, 12)]["guest_count"] += 1_731.0
    ws.values[date(2026, 11, 12)]["net_sales"] += 98_765.43
    ws.save()
    result = ws.refresh(NOW + timedelta(hours=6))

    after = ws.stored()
    assert result.changed == 1
    moved = [i for i in after if after[i]["updated_at"] != before[i]["updated_at"]]
    assert moved == [bid(date(2026, 11, 12))]
    changed = after[moved[0]]
    assert changed["updated_at"] == "2026-11-13T17:30:00Z"
    assert changed["created_at"] == before[moved[0]]["created_at"]
    assert changed["content_hash"] != before[moved[0]]["content_hash"]
    for ident in after:
        if ident not in moved:
            assert after[ident] == before[ident]


@needs_flock
def test_changing_a_mid_month_night_changes_only_briefings_that_see_it(
    tmp_path: Path,
):
    ws = Workspace(tmp_path)
    ws.build()
    before = ws.stored()

    ws.values[date(2026, 10, 20)]["net_sales"] += 123_457.79
    ws.save()
    ws.refresh(NOW + timedelta(hours=1))

    after = ws.stored()
    moved = {
        after[i]["date"]
        for i in after
        if after[i]["updated_at"] != before[i]["updated_at"]
    }
    assert {"2026-10-20", "2026-10-27"} <= moved
    allowed = {date(2026, 10, d).isoformat() for d in range(20, 32)}
    assert moved <= allowed


@needs_flock
def test_updated_at_increases_even_when_the_clock_steps_back(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    ws.values[date(2026, 11, 12)]["net_sales"] += 98_765.43
    ws.save()

    ws.refresh(NOW - timedelta(days=30))  # the clock went backwards

    stored = ws.stored()
    assert stored[bid(date(2026, 11, 12))]["updated_at"] == "2026-11-13T11:30:01Z"
    stamps = [item["updated_at"] for item in stored.values()]
    assert all(STAMP.match(stamp) for stamp in stamps)
    assert max(stamps) == "2026-11-13T11:30:01Z"

    # Same second again: still strictly later.
    ws.values[date(2026, 11, 12)]["net_sales"] += 98_765.43
    ws.save()
    ws.refresh(NOW)
    assert ws.stored()[bid(date(2026, 11, 12))]["updated_at"] == (
        "2026-11-13T11:30:02Z"
    )


@needs_flock
def test_sub_second_now_is_truncated_to_whole_seconds(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.refresh(NOW.replace(microsecond=987_654))
    stamps = {item["updated_at"] for item in ws.stored().values()}
    assert stamps == {"2026-11-13T11:30:00Z"}


@needs_flock
def test_removed_night_becomes_a_tombstone_and_can_return(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    first = ws.stored()
    gone = bid(date(2026, 10, 1))

    removed = ws.values.pop(date(2026, 10, 1))
    ws.save()
    result = ws.refresh(NOW + timedelta(hours=1))

    assert result.tombstones == 1
    assert result.briefings == 40
    stone = ws.stored()[gone]
    assert stone["deleted"] is True
    assert stone["updated_at"] == "2026-11-13T12:30:00Z"
    assert stone["updated_at"] > max(i["updated_at"] for i in first.values())
    assert "body_markdown" not in stone and "summary" not in stone

    # A second run keeps the tombstone as it is.
    again = ws.refresh(NOW + timedelta(hours=2))
    assert again.changed == 0
    assert ws.stored()[gone] == stone

    ws.values[date(2026, 10, 1)] = removed
    ws.save()
    ws.refresh(NOW + timedelta(hours=3))
    back = ws.stored()[gone]
    assert back["deleted"] is False
    assert back["updated_at"] == "2026-11-13T14:30:00Z"
    assert back["updated_at"] > stone["updated_at"]
    assert back["body_markdown"] == first[gone]["body_markdown"]


@needs_flock
def test_returning_night_gets_a_new_created_at(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    removed = ws.values.pop(date(2026, 10, 1))
    ws.save()
    ws.refresh(NOW + timedelta(hours=1))
    ws.values[date(2026, 10, 1)] = removed
    ws.save()
    ws.refresh(NOW + timedelta(hours=2))
    back = ws.stored()[bid(date(2026, 10, 1))]
    assert back["created_at"] == back["updated_at"] == "2026-11-13T13:30:00Z"


@needs_flock
def test_refresh_counts_follow_the_spec(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.build()
    ws.values.pop(date(2026, 11, 12))  # the latest: no other briefing sees it
    ws.save()
    removal = ws.refresh(NOW + timedelta(hours=1))
    again = ws.refresh(NOW + timedelta(hours=2))
    assert (removal.changed, removal.tombstones) == (1, 1)
    assert (again.changed, again.tombstones) == (0, 1)


@needs_flock
def test_store_rereads_a_replaced_file_with_the_same_mtime_and_size(
    tmp_path: Path,
):
    ws = Workspace(tmp_path)
    ws.build()
    store = BriefingsStore(ws.briefings)
    first = store.snapshot()
    stat = ws.briefings.stat()

    text = ws.briefings.read_text(encoding="utf-8")
    replaced = text.replace('"title": "Thursday', '"title": "Thursdax', 1)
    assert replaced != text and len(replaced) == len(text)
    temporary = tmp_path / "replacement.json"
    temporary.write_text(replaced, encoding="utf-8")
    os.replace(temporary, ws.briefings)
    os.utime(ws.briefings, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert ws.briefings.stat().st_ino != stat.st_ino

    titles = [e.payload.get("title", "") for e in store.snapshot().entries]
    assert titles != [e.payload.get("title", "") for e in first.entries]


# --------------------------------------------------------------------------
# Content


@needs_flock
def test_every_body_is_structured_and_short(built: Workspace):
    for item in built.stored().values():
        assert body_problems(item["body_markdown"]) == [], item["date"]
        tags = item["tags"]
        assert "restaurantos" in tags
        levels = [t for t in tags if t.startswith("confidence:")]
        assert len(levels) == 1
        level = levels[0].split(":", 1)[1]
        assert level in {"low", "medium", "high"}
        assert f"**Confidence:** {level.capitalize()}" in item["body_markdown"]
        assert item["summary"].endswith(f"Confidence: {level}.")


@needs_flock
@pytest.mark.parametrize(
    ("day", "level"),
    [
        ("2026-10-01", "low"),  # no week-earlier night
        ("2026-10-10", "medium"),  # no prior-month data
        ("2026-11-03", "high"),
        ("2026-11-04", "low"),  # the night itself is in review
        ("2026-11-06", "medium"),  # one in review and one missing this month
        ("2026-11-10", "medium"),
        ("2026-11-12", "low"),  # week-earlier night (11-05) is missing
    ],
)
def test_confidence_levels(built: Workspace, day: str, level: str):
    item = built.by_date()[day]
    assert f"confidence:{level}" in item["tags"]
    lines = item["body_markdown"].splitlines()
    coverage = lines[lines.index("### Data coverage") :]
    assert any(
        line.startswith(f"**Confidence:** {level.capitalize()}") for line in coverage
    )


@needs_flock
def test_in_review_night_is_tagged(built: Workspace):
    assert "in-review" in built.by_date()["2026-11-04"]["tags"]
    assert "in-review" not in built.by_date()["2026-11-03"]["tags"]
    assert "- This night: in review" in built.by_date()["2026-11-04"]["body_markdown"]


HEADLINE_LABELS = (
    "Net sales",
    "Covers",
    "Average check",
    "Sales per labor hour",
    "Labor cost (share of sales)",
    "Reservation share",
    "Comp rate",
    "Void rate",
)


def section(body: str, heading: str) -> str:
    """The lines of one '## ' section of a body."""
    lines = body.splitlines()
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[start:end]) + "\n"


NIGHT_SECTION = "## How did the night compare?"
MONTH_SECTION = "## How is the month going?"


@needs_flock
@pytest.mark.parametrize(
    ("day", "heading"),
    [
        ("2026-10-01", NIGHT_SECTION),  # no 2026-09-24
        ("2026-11-12", NIGHT_SECTION),  # 2026-11-05 is missing
        ("2026-10-10", MONTH_SECTION),  # September has no data
        ("2026-10-31", MONTH_SECTION),
    ],
)
def test_no_comparison_available_for_every_metric(
    built: Workspace, day: str, heading: str
):
    item = built.by_date()[day]
    part = section(item["body_markdown"], heading)
    for label in HEADLINE_LABELS:
        assert f"- {label}: no comparison available\n" in part, label
    assert "no comparison available" in item["summary"]


def rate_change(
    values: dict[date, dict[str, float]],
    current: tuple[date, date],
    previous: tuple[date, date],
    numerator: str,
    denominator: str,
) -> float:
    def rate(window: tuple[date, date]) -> float:
        rows = window_rows(values, *window)
        return sum(r[numerator] for r in rows) / sum(r[denominator] for r in rows)

    return (rate(current) - rate(previous)) / rate(previous) * 100.0


def share_points(
    values: dict[date, dict[str, float]],
    current: tuple[date, date],
    previous: tuple[date, date],
    numerator: str,
    denominator: str,
) -> float:
    def share(window: tuple[date, date]) -> float:
        rows = window_rows(values, *window)
        return sum(r[numerator] for r in rows) / sum(r[denominator] for r in rows)

    return (share(current) - share(previous)) * 100.0


@needs_flock
@pytest.mark.parametrize("day", ["2026-11-03", "2026-11-10", "2026-11-08"])
def test_headline_phrases_match_relative_arithmetic(built: Workspace, day: str):
    night = date.fromisoformat(day)
    body = built.by_date()[day]["body_markdown"]
    values = built.values
    week = ((night, night), (night - timedelta(7), night - timedelta(7)))
    month = month_windows(night)

    for heading, windows in ((NIGHT_SECTION, week), (MONTH_SECTION, month)):
        part = section(body, heading)
        expected = {
            "Net sales": expected_phrase(volume_change(values, *windows, "net_sales")),
            "Covers": expected_phrase(volume_change(values, *windows, "guest_count")),
            "Average check": expected_phrase(
                rate_change(values, *windows, "net_sales", "guest_count")
            ),
            "Sales per labor hour": expected_phrase(
                rate_change(values, *windows, "net_sales", "labor_hours")
            ),
            "Labor cost (share of sales)": expected_phrase(
                labor_share_points(values, *windows), "points"
            ),
            "Reservation share": expected_phrase(
                share_points(values, *windows, "reservation_covers", "guest_count"),
                "points",
            ),
            "Comp rate": expected_phrase(
                share_points(values, *windows, "comps", "net_sales"), "points"
            ),
            "Void rate": expected_phrase(
                share_points(values, *windows, "voids", "net_sales"), "points"
            ),
        }
        for label, wording in expected.items():
            assert f"- {label}: {wording}" in part, (heading, label)


@needs_flock
@pytest.mark.parametrize("day", ["2026-11-03", "2026-10-01", "2026-10-10"])
def test_all_spec_headline_labels_are_written(built: Workspace, day: str):
    body = built.by_date()[day]["body_markdown"]
    for label in HEADLINE_LABELS:
        assert body.count(f"- {label}: ") == 2, label


@needs_flock
@pytest.mark.parametrize(
    ("day", "review", "missing"),
    [
        ("2026-10-15", 0, 0),
        ("2026-11-03", 0, 0),
        ("2026-11-04", 1, 0),
        ("2026-11-10", 1, 1),
    ],
)
def test_coverage_lines(built: Workspace, day: str, review: int, missing: int):
    body = built.by_date()[day]["body_markdown"]
    assert f"- Nights in review this month: {review}\n" in body
    assert f"- Nights missing this month: {missing}\n" in body
    # No October night is reviewed, so the comparison days are clean.
    assert "- Nights in review, comparison days: 0\n" in body
    assert "- Nights missing, comparison days: 0\n" in body


@needs_flock
def test_without_a_manifest_coverage_is_unknown_and_never_high(tmp_path: Path):
    ws = Workspace(tmp_path)
    ws.manifest.unlink()
    ws.build()
    for item in ws.stored().values():
        body = item["body_markdown"]
        for line in (
            "- Nights in review this month: unknown",
            "- Nights missing this month: unknown",
            "- Nights in review, comparison days: unknown",
            "- Nights missing, comparison days: unknown",
        ):
            assert line in body
        assert "confidence:high" not in item["tags"]
        assert body_problems(body) == []
    assert "confidence:medium" in ws.by_date()["2026-11-03"]["tags"]
    # Unknown coverage: only the week-earlier rule can make it Low.
    assert "confidence:low" in ws.by_date()["2026-11-12"]["tags"]
    assert "confidence:medium" in ws.by_date()["2026-11-10"]["tags"]


@needs_flock
def test_empty_reviews_list_is_known_zero(tmp_path: Path):
    ws = Workspace(tmp_path, reviews={})
    ws.build()
    item = ws.by_date()["2026-11-12"]
    assert "- Nights in review this month: 0" in item["body_markdown"]
    # 11-05 is not in the ledger at all, so the week comparison is missing.
    assert "confidence:low" in item["tags"]
    assert "confidence:high" in ws.by_date()["2026-11-03"]["tags"]


def _missing_october(ws: Workspace, *days: int) -> None:
    for day in days:
        ws.values.pop(date(2026, 10, day))
        ws.reviews[f"2026-10-{day:02d}"] = ["primary_without_operational_data"]
    ws.save()


@needs_flock
def test_three_missing_nights_make_confidence_low(tmp_path: Path):
    ws = Workspace(tmp_path)
    _missing_october(ws, 7, 9)
    ws.build()
    # 2026-11-10: 11-05 missing (current) + 10-07, 10-09 missing (prior).
    item = ws.by_date()["2026-11-10"]
    assert "confidence:low" in item["tags"]
    body = item["body_markdown"]
    assert "- Nights missing this month: 1\n" in body
    assert "- Nights missing, comparison days: 2\n" in body
    assert "**Confidence:** Low" in section(body, "## How much weight does this bear?")


@needs_flock
def test_two_missing_nights_stay_medium(tmp_path: Path):
    ws = Workspace(tmp_path)
    _missing_october(ws, 7)
    ws.build()
    # 11-05 + 10-07: two missing across both windows, below the threshold.
    assert "confidence:medium" in ws.by_date()["2026-11-10"]["tags"]


@needs_flock
def test_a_review_in_the_prior_month_window_prevents_high(tmp_path: Path):
    ws = Workspace(tmp_path, reviews={"2026-10-02": ["missing_total_covers"]})
    ws.build()
    # 2026-11-03 compares Nov 1-3 against Oct 1-3, which holds a reviewed night.
    item = ws.by_date()["2026-11-03"]
    assert "confidence:medium" in item["tags"]
    assert "- Nights in review, comparison days: 1\n" in item["body_markdown"]
    assert "- Nights in review this month: 0\n" in item["body_markdown"]
    # 2026-11-04 compares against Oct 1-4, which still holds it.
    assert "confidence:medium" in ws.by_date()["2026-11-04"]["tags"]
    # October nights from the 2nd on count it in their own month window.
    assert (
        "- Nights in review this month: 1\n"
        in (ws.by_date()["2026-10-15"]["body_markdown"])
    )


@needs_flock
def test_week_earlier_review_only_lowers_its_own_finding(tmp_path: Path):
    ws = Workspace(tmp_path, reviews={"2026-10-27": ["missing_total_covers"]})
    ws.build()
    # 2026-11-03 against 2026-10-27, which lies outside Nov 1-3 and Oct 1-3.
    item = ws.by_date()["2026-11-03"]
    assert "confidence:high" in item["tags"]
    week = section(item["body_markdown"], NIGHT_SECTION)
    assert "**Confidence:** Medium — a night in the comparison is in review." in week
    month = section(item["body_markdown"], MONTH_SECTION)
    assert "**Confidence:** High" in month


# --------------------------------------------------------------------------
# Privacy of the stored file


@needs_flock
def test_briefings_file_holds_no_absolute_figure(built: Workspace):
    forbidden = forbidden_numbers(built.values)
    separated = with_separators(forbidden)
    for item in built.stored().values():
        visible = {k: v for k, v in item.items() if k not in ("id", "content_hash")}
        text = json.dumps(visible, ensure_ascii=False)
        assert leaks(text, forbidden, separated) == [], item["id"]
        assert stray_numbers(prose_of(item)) == [], item["date"]


@needs_flock
def test_privacy_helpers_catch_a_planted_leak(built: Workspace):
    """Guard against a vacuous privacy check."""
    forbidden = forbidden_numbers(built.values)
    separated = with_separators(forbidden)
    sales = built.values[date(2026, 11, 3)]["net_sales"]
    for planted in (
        str(int(sales)),
        f"{sales:,.2f}",
        f"{sales:.2f}",
        f"{round(sales):,}",
        f"${sales:,.0f}",
        f"Covers 1,234 at {ENTITY}",
    ):
        assert leaks(f"Net sales: {planted}", forbidden, separated), planted
    assert stray_numbers("Covers 1,234 tonight") == ["1,234"]
    assert stray_numbers("average check 45.1") == ["45.1"]
    assert stray_numbers("up 4.2% and down 0.3 points on November 12, 2026") == []


# --------------------------------------------------------------------------
# CLI and nightly wiring


def run_cli(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["restaurantos", *args])
    cli_main()


def parse_lines(out: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            result[key] = value
    return result


@needs_flock
def test_cli_briefings_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    ws = Workspace(tmp_path)
    args = (
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
    run_cli(monkeypatch, *args)
    first = parse_lines(capsys.readouterr().out)
    assert first == {
        "briefings": "41",
        "changed": "41",
        "tombstones": "0",
        "path": str(ws.briefings),
    }
    before = ws.briefings.read_bytes()
    assert ws.briefings.stat().st_mode & 0o077 == 0

    run_cli(monkeypatch, *args)
    second = parse_lines(capsys.readouterr().out)
    assert second["changed"] == "0"
    assert ws.briefings.read_bytes() == before


def test_cli_briefings_refresh_without_ledger_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    target = tmp_path / "elsewhere" / "briefings.json"
    with pytest.raises(SystemExit) as exit_:
        run_cli(
            monkeypatch,
            "briefings-refresh",
            "--history",
            str(tmp_path / "no-such-history.jsonl"),
            "--manifest",
            str(tmp_path / "no-such-manifest.json"),
            "--briefings",
            str(target),
            "--entity",
            ENTITY,
        )
    assert exit_.value.code not in (0, None)
    assert "briefings-refresh" in capsys.readouterr().err
    assert not target.exists()
    assert not target.parent.exists()


def test_cli_briefings_refresh_help_lists_its_flags(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    with pytest.raises(SystemExit) as exit_:
        run_cli(monkeypatch, "briefings-refresh", "--help")
    assert exit_.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--history", "--manifest", "--briefings", "--entity"):
        assert flag in out


@pytest.mark.parametrize("kind", ["short", "same"])
def test_cli_serve_rejects_a_bad_phone_token_without_echoing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
    kind: str,
):
    api_token = "cli-api-token-0123456789abcdefgh"
    bad = "short-phone-tok" if kind == "short" else api_token
    monkeypatch.setenv("ATLAS_API_TOKEN", api_token)
    monkeypatch.setenv("ATLAS_BRIEFINGS_TOKEN", bad)
    with pytest.raises(SystemExit) as exit_:
        run_cli(
            monkeypatch,
            "serve",
            "--history",
            str(tmp_path / "h.jsonl"),
            "--manifest",
            str(tmp_path / "m.json"),
            "--port",
            "0",
        )
    assert exit_.value.code not in (0, None)
    captured = capsys.readouterr()
    assert "ATLAS_BRIEFINGS_TOKEN" in captured.err
    assert bad not in captured.err + captured.out
    assert api_token not in captured.err + captured.out


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


def test_nightly_steps_and_arguments(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    recorded: list[list[str]] = []
    kwargs_seen: list[dict[str, Any]] = []

    def fake(command: Any, *args: Any, **kwargs: Any) -> Any:
        recorded.append([str(part) for part in command])
        kwargs_seen.append(kwargs)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(SystemExit) as exit_:
        runpy.run_path(str(NIGHTLY_SCRIPT), run_name="__main__")
    assert exit_.value.code == 0
    capsys.readouterr()

    fonda = nightly_root / "restaurantos" / "fonda"
    assert len(recorded) == 2
    assert recorded[0][1:4] == ["-m", "restaurantos", "gmail-nightly-refresh"]
    assert recorded[1] == [
        sys.executable,
        "-m",
        "restaurantos",
        "briefings-refresh",
        "--history",
        str(fonda / "nightly-history.jsonl"),
        "--manifest",
        str(fonda / "nightly-manifest.json"),
        "--briefings",
        str(fonda / "briefings.json"),
        "--entity",
        ENTITY,
    ]
    assert all(seen.get("check") is True for seen in kwargs_seen)


def test_nightly_skips_briefings_after_a_failed_refresh(
    nightly_root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    calls: list[list[str]] = []

    def fake(command: Any, *args: Any, **kwargs: Any) -> Any:
        calls.append([str(part) for part in command])
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(subprocess.CalledProcessError):
        runpy.run_path(str(NIGHTLY_SCRIPT), run_name="__main__")
    capsys.readouterr()
    assert len(calls) == 1
    assert "gmail-nightly-refresh" in calls[0]
