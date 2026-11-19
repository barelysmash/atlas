"""Decisions from the nightly ledger. Every figure in this file is invented."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from atlas_core.goal import Goal, MetricTarget
from atlas_core.grain import DAILY, RATE, SUM
from atlas_core.operational_record import OperationalRecord
from jsonschema import Draft202012Validator, FormatChecker
from restaurantos.api import ApiConfig, make_server
from restaurantos.decisions import (
    DECISIONS_FILENAME,
    load_goals,
    read_decisions_file,
    reason_over_ledger,
    relative_decisions,
    write_decisions_file,
)
from test_peer_api import TOKEN, call

VENUE = "Fonda San Miguel"
MONDAY = date(2026, 6, 1)
NOW = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "packages/atlas-core/tests/contracts/decision.schema.json"
)

GOALS = [
    Goal.create(
        summary="Grow sales",
        targets=[
            MetricTarget("net_sales", "increase", tolerance=3.0),
            MetricTarget("guest_count", "increase", tolerance=3.0),
            MetricTarget("average_check", "increase", tolerance=2.0),
        ],
        priority="high",
        category="atlas.marketing",
    ),
    Goal.create(
        summary="Improve labor efficiency",
        targets=[
            MetricTarget("splh", "increase", tolerance=3.0),
            MetricTarget("labor_cost_pct", "decrease", tolerance=3.0),
        ],
        priority="high",
        category="atlas.labor",
    ),
]


def night(day: date, values: dict[str, float]) -> list[OperationalRecord]:
    categories = {"net_sales": "sales", "guest_count": "demand"}
    return [
        OperationalRecord.create(
            source="nightly_email",
            entity=VENUE,
            period=day.isoformat(),
            category=categories.get(metric, "labor"),
            metric=metric,
            value=value,
            grain=DAILY,
            aggregation=SUM,
        )
        for metric, value in values.items()
    ]


def ledger(
    weeks: int = 7,
    *,
    sales_step: float = -400.0,
    skip: set[date] | None = None,
    sales_only: set[date] | None = None,
) -> list[OperationalRecord]:
    """Seven nights a week. Sales drift by ``sales_step`` a week; labor rises."""
    records: list[OperationalRecord] = []
    for offset in range(weeks * 7):
        day = MONDAY + timedelta(days=offset)
        week = offset // 7
        if skip and day in skip:
            continue
        values = {
            "net_sales": 7111.0 + week * sales_step,
            "guest_count": 333.0 - week * 4,
            "labor_hours": 222.0 + week * 3,
            "labor_cost": 3777.0 + week * 51,
        }
        if sales_only and day in sales_only:
            values = {"net_sales": values["net_sales"]}
        records.extend(night(day, values))
        # The real ledger also holds nightly rates. They must be ignored and
        # derived again from weekly totals, never rolled up.
        records.append(
            OperationalRecord.create(
                source="nightly_email",
                entity=VENUE,
                period=day.isoformat(),
                category="productivity",
                metric="splh",
                value=32.0,
                grain=DAILY,
                aggregation=RATE,
            )
        )
    return records


def by_metric(emitted: list[Any]) -> dict[str, Any]:
    return {item.metric: item for item in emitted}


# ── reasoning ────────────────────────────────────────────────────────────


def test_a_metric_moving_against_its_goal_becomes_a_decision():
    emitted, gaps = reason_over_ledger(ledger(), GOALS, now=NOW)
    found = by_metric(emitted)
    assert set(found) == {
        "net_sales",
        "guest_count",
        "average_check",
        "splh",
        "labor_cost_pct",
    }
    assert gaps == []
    sales = found["net_sales"]
    assert sales.assessment == "unfavorable"
    assert sales.decision.priority == "high"
    assert sales.decision.category == "atlas.marketing"
    assert sales.goal == "Grow sales"
    assert sales.latest_period == "2026-07-13..2026-07-19"
    assert found["labor_cost_pct"].decision.category == "atlas.labor"


def test_a_metric_moving_with_its_goal_is_a_lower_priority_decision():
    emitted, _ = reason_over_ledger(ledger(sales_step=500.0), GOALS, now=NOW)
    sales = by_metric(emitted)["net_sales"]
    assert sales.assessment == "favorable"
    assert sales.decision.priority == "medium"


def test_nightly_rates_in_the_ledger_are_rederived_from_weekly_totals():
    emitted, _ = reason_over_ledger(ledger(), GOALS, now=NOW)
    splh = by_metric(emitted)["splh"]
    # The ledger's nightly splh never moves; the weekly one, from totals, falls.
    assert splh.assessment == "unfavorable"


def test_the_unfinished_current_week_is_not_judged():
    records = ledger(weeks=7) + night(
        MONDAY + timedelta(days=49), {"net_sales": 1.0, "guest_count": 1.0}
    )
    emitted, _ = reason_over_ledger(records, GOALS, now=NOW)
    assert by_metric(emitted)["net_sales"].latest_period == "2026-07-13..2026-07-19"


def test_a_week_with_a_sales_only_night_is_judged_for_sales_but_not_labor():
    partial = {MONDAY + timedelta(days=44)}  # a night in the last week
    emitted, _ = reason_over_ledger(ledger(sales_only=partial), GOALS, now=NOW)
    found = by_metric(emitted)
    assert found["net_sales"].latest_period == "2026-07-13..2026-07-19"
    assert found["splh"].latest_period == "2026-07-06..2026-07-12"
    assert found["labor_cost_pct"].latest_period == "2026-07-06..2026-07-12"


def test_only_the_trailing_window_is_reasoned_over():
    emitted, _ = reason_over_ledger(ledger(weeks=7), GOALS, now=NOW, window_weeks=2)
    cited = by_metric(emitted)["net_sales"].decision.evidence
    assert all("2026-06-" not in (item.source_ref or "") for item in cited)


def test_a_goal_metric_with_no_data_is_reported_as_a_gap():
    goals = [
        Goal.create(
            summary="Grow wine",
            targets=[MetricTarget("wine_receipts", "increase")],
            category="atlas.marketing",
        )
    ]
    emitted, gaps = reason_over_ledger(ledger(), goals, now=NOW)
    assert emitted == []
    assert gaps == [
        {"goal": "Grow wine", "metric": "wine_receipts", "reason": "no_data"}
    ]


def test_no_goals_or_an_empty_ledger_means_no_decisions():
    assert reason_over_ledger(ledger(), [], now=NOW) == ([], [])
    assert reason_over_ledger([], GOALS, now=NOW) == ([], [])


# ── the private file ─────────────────────────────────────────────────────


def test_the_private_file_holds_valid_jam_decisions(tmp_path: Path):
    path = tmp_path / DECISIONS_FILENAME
    assert write_decisions_file(ledger(), GOALS, path, now=NOW) == 5
    assert path.stat().st_mode & 0o777 == 0o600
    payload = read_decisions_file(path)
    assert payload is not None
    validator = Draft202012Validator(
        json.loads(SCHEMA.read_text(encoding="utf-8")),
        format_checker=FormatChecker(),
    )
    for entry in payload["decisions"]:
        validator.validate(entry["document"])
        assert entry["document"]["source"] == "atlas"
        assert entry["document"]["requires_approval"] is True


def test_an_unchanged_finding_keeps_its_id_across_rebuilds(tmp_path: Path):
    path = tmp_path / DECISIONS_FILENAME
    write_decisions_file(ledger(), GOALS, path, now=NOW)
    first = {e["key"]: e for e in read_decisions_file(path)["decisions"]}
    write_decisions_file(ledger(), GOALS, path, now=NOW + timedelta(days=1))
    second = {e["key"]: e for e in read_decisions_file(path)["decisions"]}
    assert first.keys() == second.keys()
    for key, entry in second.items():
        assert entry["document"]["decision_id"] == first[key]["document"]["decision_id"]
        assert entry["first_emitted_at"] == "2026-07-21T12:00:00+00:00"
        assert entry["document"]["created_at"] == "2026-07-21T12:00:00Z"


def test_a_new_week_is_a_new_decision(tmp_path: Path):
    path = tmp_path / DECISIONS_FILENAME
    write_decisions_file(ledger(weeks=7), GOALS, path, now=NOW)
    before = {
        e["document"]["decision_id"] for e in read_decisions_file(path)["decisions"]
    }
    write_decisions_file(ledger(weeks=8), GOALS, path, now=NOW + timedelta(days=7))
    after = read_decisions_file(path)["decisions"]
    assert before.isdisjoint(e["document"]["decision_id"] for e in after)
    assert {e["first_emitted_at"] for e in after} == {"2026-07-28T12:00:00+00:00"}


# ── goals file ───────────────────────────────────────────────────────────


def goals_file(tmp_path: Path, payload: Any) -> Path:
    path = tmp_path / "goals.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_goals_load_from_the_private_file(tmp_path: Path):
    path = goals_file(
        tmp_path,
        {
            "goals": [
                {
                    "summary": "Grow sales",
                    "priority": "high",
                    "category": "atlas.marketing",
                    "targets": [
                        {"metric": "net_sales", "direction": "increase", "tolerance": 3}
                    ],
                }
            ]
        },
    )
    [goal] = load_goals(path)
    assert goal.summary == "Grow sales"
    assert goal.priority == "high"
    assert goal.targets[0].tolerance == 3.0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"goals": []},
        {"goals": [{"summary": "x", "targets": []}]},
        {
            "goals": [
                {"summary": "x", "targets": [{"metric": "a", "direction": "sideways"}]}
            ]
        },
        {
            "goals": [
                {
                    "summary": "x",
                    "category": "sales",
                    "targets": [{"metric": "a", "direction": "increase"}],
                }
            ]
        },
        {
            "goals": [
                {
                    "summary": "x",
                    "targets": [
                        {"metric": "a", "direction": "increase", "tolerance": "big"}
                    ],
                }
            ]
        },
    ],
)
def test_a_malformed_goals_file_is_an_error(tmp_path: Path, payload: Any):
    with pytest.raises(ValueError):
        load_goals(goals_file(tmp_path, payload))


# ── the relative-only projection ─────────────────────────────────────────


def projection(tmp_path: Path) -> dict[str, Any]:
    path = tmp_path / DECISIONS_FILENAME
    write_decisions_file(ledger(), GOALS, path, now=NOW)
    return relative_decisions(read_decisions_file(path), today=date(2026, 7, 23))


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


def test_the_projection_never_contains_an_absolute_figure(tmp_path: Path):
    path = tmp_path / DECISIONS_FILENAME
    write_decisions_file(ledger(), GOALS, path, now=NOW)
    private = read_decisions_file(path)
    assert private is not None
    levels = {
        round(item["metric"]["value"], 2)
        for entry in private["decisions"]
        for item in entry["document"]["evidence"]
    }
    assert levels and min(levels) > 10  # weekly totals and rates, all large
    shown = relative_decisions(private, today=date(2026, 7, 23))
    leaked = {round(number, 2) for number in _numbers(shown)} & levels
    assert leaked == set()
    rendered = json.dumps(shown)
    for level in levels:
        # Small levels (rates) would collide with dates as bare integers, so
        # they are checked to the cent; totals are checked as whole numbers.
        assert f"{level:.2f}" not in rendered
        if level >= 1000:
            assert f"{level:,.0f}" not in rendered
            assert str(int(level)) not in rendered
    assert "was " not in rendered  # no observation sentence was copied


def test_the_projection_says_what_moved_and_by_how_much(tmp_path: Path):
    shown = projection(tmp_path)
    assert shown["status"] == "ok"
    assert shown["count"] == 5
    sales = next(d for d in shown["decisions"] if d["metric"] == "net sales")
    assert sales["summary"] == "Intervene on net sales."
    assert sales["priority"] == "high"
    assert sales["assessment"] == "unfavorable"
    assert sales["goal"] == "Grow sales"
    assert sales["days_since_first_emitted"] == 2
    assert sales["first_emitted_on"] == "2026-07-21"
    assert sales["requires_approval"] is True
    latest, streak = sales["evidence"]
    assert latest["direction"] == "down"
    assert latest["basis"] == "latest full week against the week before"
    assert latest["change_pct"] == pytest.approx(-7.8, abs=0.1)
    assert streak["basis"] == "across 6 consecutive weekly moves the same way"
    assert "net_sales" not in json.dumps(shown)
    assert any("the week of 2026-06-01" in r for r in sales["recommendations"])


def test_high_priority_and_newest_come_first(tmp_path: Path):
    path = tmp_path / DECISIONS_FILENAME
    write_decisions_file(ledger(sales_step=500.0), GOALS, path, now=NOW)
    shown = relative_decisions(read_decisions_file(path), today=date(2026, 7, 23))
    priorities = [d["priority"] for d in shown["decisions"]]
    assert priorities == sorted(priorities, key=["high", "medium", "low"].index)


def test_without_a_decisions_file_the_projection_says_not_configured():
    shown = relative_decisions(None, today=date(2026, 7, 23))
    assert shown["status"] == "not_configured"
    assert shown["decisions"] == []


# ── the peer API ─────────────────────────────────────────────────────────


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    history = tmp_path / "nightly-history.jsonl"
    history.write_text("", encoding="utf-8")
    config = ApiConfig(
        history_path=history,
        manifest_path=tmp_path / "nightly-manifest.json",
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


def test_decisions_route_requires_the_token(server: ThreadingHTTPServer):
    status, body = call(server, "GET", "/v1/decisions", token=None)
    assert status == 401
    assert "data" not in body


def test_decisions_route_before_goals_exist(server: ThreadingHTTPServer):
    status, body = call(server, "GET", "/v1/decisions")
    assert status == 200
    assert body["data"]["status"] == "not_configured"


def test_decisions_route_serves_the_relative_projection(
    server: ThreadingHTTPServer, tmp_path: Path
):
    write_decisions_file(ledger(), GOALS, tmp_path / DECISIONS_FILENAME, now=NOW)
    status, body = call(server, "GET", "/v1/decisions")
    assert status == 200
    assert body["data"]["count"] == 5
    assert "document" not in json.dumps(body)
    assert "observation_id" not in json.dumps(body)


# ── the nightly refresh ──────────────────────────────────────────────────

EOD_BODY = """
SPLH: $80.00
Labor (actual): $4,000.00
Horas (actual): 250.00
Reservations: 200
Dining Room: 240
Bar/Atrium: 160
Total: 400
Total Comps: $500.00
Total Voids: $100.00
"""

GOALS_PAYLOAD = {
    "goals": [
        {
            "summary": "Grow sales",
            "priority": "high",
            "category": "atlas.marketing",
            "targets": [{"metric": "net_sales", "direction": "increase"}],
        }
    ]
}


def refresh(tmp_path: Path, goals: Path | None):
    from restaurantos.nightly_refresh import rebuild_nightly_history

    rows = [
        {
            "message_id": f"m{index}",
            "subject": f"EOD {day.month}/{day.day}/{day.year}",
            "body": EOD_BODY,
            "sent_at": f"{day.isoformat()}T23:30:00-05:00",
        }
        for index, day in enumerate(MONDAY + timedelta(days=n) for n in range(21))
    ]
    messages = tmp_path / "messages.jsonl"
    messages.write_text("\n".join(json.dumps(row) for row in rows) + "\n", "utf-8")
    return rebuild_nightly_history(
        messages,
        tmp_path / "nightly-history.jsonl",
        tmp_path / "nightly-manifest.json",
        restaurant=VENUE,
        goals_path=goals,
    )


def test_the_refresh_writes_decisions_beside_the_ledger(tmp_path: Path):
    result = refresh(tmp_path, goals_file(tmp_path, GOALS_PAYLOAD))
    assert result.decision_error is None
    assert result.decision_count is not None
    payload = read_decisions_file(tmp_path / DECISIONS_FILENAME)
    assert payload is not None
    assert len(payload["decisions"]) == result.decision_count


def test_the_refresh_without_goals_writes_no_decisions(tmp_path: Path):
    result = refresh(tmp_path, None)
    assert result.decision_count is None
    assert not (tmp_path / DECISIONS_FILENAME).exists()


def test_a_bad_goals_file_is_reported_and_never_blocks_the_ledger(tmp_path: Path):
    result = refresh(tmp_path, goals_file(tmp_path, {"goals": []}))
    assert result.decision_count is None
    assert "goals" in str(result.decision_error)
    assert (tmp_path / "nightly-history.jsonl").stat().st_size > 0
    assert result.service_nights == 21
