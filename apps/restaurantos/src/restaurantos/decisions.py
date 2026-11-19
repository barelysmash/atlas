"""Decisions from the nightly ledger, judged against the venue's goals.

The reasoning itself is atlas-core's: weekly blocks, rates derived from each
week's totals, week-over-week and streak observations, insights against
goals, then Decisions. This module supplies what is specific to a venue's
nightly ledger:

- which records are facts (the ledger also holds nightly rates, which cannot
  be rolled up and are derived again from weekly totals);
- the goals, read from a private file, because what counts as progress is the
  operator's call and not something to infer from a metric name;
- a stable identity, so the same finding on the same week keeps one
  decision_id across nightly rebuilds and a consumer can tell new from seen;
- two outputs: the private file of full JAM Decision documents, and a
  relative-only projection for peers such as JARVIS.

The private documents carry absolute figures, as the JAM contract requires.
The projection carries none: it is built field by field from deltas and
engine-written sentences, never by copying an evidence statement or a value.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

from atlas_core.blocking import block_records
from atlas_core.data_gap_engine import generate_data_gaps
from atlas_core.decision import Decision
from atlas_core.decision_engine import generate_decisions
from atlas_core.derived_metric_engine import derive_metrics
from atlas_core.documents import decision_document
from atlas_core.goal import TARGET_DIRECTIONS, Goal, MetricTarget
from atlas_core.grain import SUM
from atlas_core.insight_engine import generate_insights
from atlas_core.operational_record import OperationalRecord
from atlas_core.trend_observation_engine import generate_trend_observations

from restaurantos.metrics import NIGHTLY_DERIVED_METRICS

# The JAM contract wants a bare semver for the engine build.
SOURCE_VERSION = "0.3.0"

DEFAULT_WINDOW_WEEKS = 8

# Written beside the ledger; the peer API looks for it there.
DECISIONS_FILENAME = "nightly-decisions.json"

_DERIVED_NAMES = frozenset(definition.metric for definition in NIGHTLY_DERIVED_METRICS)

METRIC_LABELS = {
    "net_sales": "net sales",
    "guest_count": "covers",
    "average_check": "average check",
    "splh": "sales per labor hour",
    "labor_cost_pct": "labor cost percent",
    "labor_hours": "labor hours",
    "labor_cost": "labor cost",
    "covers_per_labor_hour": "covers per labor hour",
    "reservation_share": "reservation share",
    "comp_pct": "comp percent",
    "void_pct": "void percent",
}


def metric_label(metric: str) -> str:
    return METRIC_LABELS.get(metric, metric.replace("_", " "))


# ── goals ────────────────────────────────────────────────────────────────


def load_goals(path: str | Path) -> list[Goal]:
    """Read the venue's goals. A malformed file is an error, not a skip."""
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    entries = payload.get("goals") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{source.name}: expected a non-empty 'goals' list")

    goals: list[Goal] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{source.name}: goal {index} must be an object")
        targets_raw = entry.get("targets")
        if not isinstance(targets_raw, list) or not targets_raw:
            raise ValueError(f"{source.name}: goal {index} needs targets")
        targets: list[MetricTarget] = []
        for target in targets_raw:
            if not isinstance(target, dict):
                raise ValueError(f"{source.name}: goal {index} has a bad target")
            direction = target.get("direction")
            if direction not in TARGET_DIRECTIONS:
                raise ValueError(
                    f"{source.name}: goal {index} direction must be one of "
                    f"{TARGET_DIRECTIONS}"
                )
            tolerance = target.get("tolerance", 0.0)
            if isinstance(tolerance, bool) or not isinstance(tolerance, int | float):
                raise ValueError(
                    f"{source.name}: goal {index} tolerance must be a number"
                )
            targets.append(
                MetricTarget(
                    metric=str(target.get("metric", "")),
                    direction=direction,
                    tolerance=float(tolerance),
                )
            )
        goals.append(
            Goal.create(
                summary=str(entry.get("summary", "")),
                targets=targets,
                priority=str(entry.get("priority", "medium")),
                category=entry.get("category"),
            )
        )
    return goals


# ── reasoning ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EmittedDecision:
    """One Decision with the handles a consumer needs to track it."""

    key: str
    metric: str
    assessment: str
    goal: str
    latest_period: str
    first_emitted_at: datetime
    decision: Decision


def _facts(
    records: list[OperationalRecord], window_weeks: int
) -> list[OperationalRecord]:
    """Summable nightly facts inside the trailing window."""
    facts = [
        record
        for record in records
        if record.aggregation == SUM and record.metric not in _DERIVED_NAMES
    ]
    if not facts:
        return []
    last = max(date.fromisoformat(record.period) for record in facts)
    first = last - timedelta(weeks=window_weeks)
    return [r for r in facts if date.fromisoformat(r.period) > first]


# A block period inside a source_ref: one date, or first..last. Matched by
# pattern because a venue name may contain spaces, so a ref cannot be split.
_PERIOD = re.compile(r"\d{4}-\d{2}-\d{2}(?:\.\.\d{4}-\d{2}-\d{2})?")


def _latest_period(decision: Decision) -> str:
    """The most recent block the Decision's evidence rests on."""
    periods: list[str] = []
    for item in decision.evidence:
        periods.extend(_PERIOD.findall(item.source_ref or ""))
    return max(periods) if periods else "unknown"


def reason_over_ledger(
    records: list[OperationalRecord],
    goals: list[Goal],
    *,
    now: datetime | None = None,
    window_weeks: int = DEFAULT_WINDOW_WEEKS,
    previous: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[EmittedDecision], list[dict[str, str]]]:
    """Decisions and data gaps for the trailing window of the ledger.

    ``previous`` maps a decision key to its earlier entry. A finding that is
    unchanged since the last run keeps its decision_id and created_at, so it
    is one Decision that persists and not a new one every night.
    """
    moment = now or datetime.now(UTC)
    previous = previous or {}
    facts = _facts(records, window_weeks)
    if not facts or not goals:
        return [], []

    prepared = derive_metrics(block_records(facts), NIGHTLY_DERIVED_METRICS)
    observations = generate_trend_observations(prepared)
    insights = generate_insights(observations, goals, moment)

    emitted: list[EmittedDecision] = []
    for insight in insights:
        for decision in generate_decisions([insight], moment):
            metric = next(
                item.metric.name
                for item in decision.evidence
                if item.metric is not None
            )
            assessment = str(insight.assessment)
            latest = _latest_period(decision)
            key = f"{decision.category}|{metric}|{assessment}|{latest}"
            first_emitted = moment
            earlier = previous.get(key)
            if earlier is not None:
                try:
                    first_emitted = datetime.fromisoformat(earlier["first_emitted_at"])
                    decision = replace(
                        decision,
                        decision_id=earlier["document"]["decision_id"],
                        created_at=first_emitted,
                    )
                except (KeyError, TypeError, ValueError):
                    first_emitted = moment
            emitted.append(
                EmittedDecision(
                    key=key,
                    metric=metric,
                    assessment=assessment,
                    goal=insight.goal.summary if insight.goal else "",
                    latest_period=latest,
                    first_emitted_at=first_emitted,
                    decision=decision,
                )
            )

    gaps = [
        {"goal": gap.goal, "metric": gap.metric, "reason": gap.reason}
        for gap in generate_data_gaps(observations, goals)
    ]
    return emitted, gaps


# ── the private file ─────────────────────────────────────────────────────


def read_decisions_file(path: str | Path) -> dict[str, Any] | None:
    """The private decisions file, or None when absent or unreadable."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_decisions_file(
    records: list[OperationalRecord],
    goals: list[Goal],
    path: str | Path,
    *,
    now: datetime | None = None,
    window_weeks: int = DEFAULT_WINDOW_WEEKS,
) -> int:
    """Reason over the ledger and write the private decisions file.

    Returns how many Decisions were written. The file holds full JAM Decision
    documents, absolute figures included, and is owner-only.
    """
    destination = Path(path)
    moment = now or datetime.now(UTC)
    earlier = read_decisions_file(destination) or {}
    previous = {
        entry["key"]: entry
        for entry in earlier.get("decisions", [])
        if isinstance(entry, dict) and isinstance(entry.get("key"), str)
    }
    emitted, gaps = reason_over_ledger(
        records, goals, now=moment, window_weeks=window_weeks, previous=previous
    )
    payload = {
        "generated_at": moment.isoformat(timespec="seconds"),
        "source_version": SOURCE_VERSION,
        "window_weeks": window_weeks,
        "decisions": [
            {
                "key": item.key,
                "metric": item.metric,
                "assessment": item.assessment,
                "goal": item.goal,
                "latest_period": item.latest_period,
                "first_emitted_at": item.first_emitted_at.isoformat(timespec="seconds"),
                "document": decision_document(
                    item.decision, source_version=SOURCE_VERSION
                ),
            }
            for item in emitted
        ],
        "gaps": gaps,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
    temporary.chmod(0o600)
    temporary.replace(destination)
    return len(emitted)


# ── the relative-only projection ─────────────────────────────────────────

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


_WEEK_BLOCK = re.compile(r"(\d{4}-\d{2}-\d{2})\.\.\d{4}-\d{2}-\d{2}")


def _humanize(text: str) -> str:
    """Engine sentences use snake_case metrics and block periods; use words."""
    for name in sorted(METRIC_LABELS, key=len, reverse=True):
        text = text.replace(name, METRIC_LABELS[name])
    return _WEEK_BLOCK.sub(r"the week of \1", text)


def _blocks_cited(item: dict[str, Any]) -> int:
    """How many weekly blocks a citation rests on, from its source_ref."""
    source_ref = item.get("source_ref")
    return len(_PERIOD.findall(source_ref)) if isinstance(source_ref, str) else 0


def _week_starts(item: dict[str, Any]) -> list[date]:
    """The Monday of each weekly block a citation rests on, oldest first."""
    source_ref = item.get("source_ref")
    if not isinstance(source_ref, str):
        return []
    starts: set[date] = set()
    for period in _PERIOD.findall(source_ref):
        first = date.fromisoformat(period[:10])
        starts.add(first - timedelta(days=first.weekday()))
    return sorted(starts)


def _relative_evidence(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Direction and percent change per citation. Never a value or statement.

    Each citation names the weeks it compares. They are not always
    neighbours: a week with a missing night is left out for the metrics that
    night lacks, and the comparison then reaches back to the week before it.
    Saying "the week before" for such a comparison would be wrong, and two
    metrics in one answer can rest on different pairs of weeks.
    """
    evidence: list[dict[str, Any]] = []
    for item in document.get("evidence", []):
        metric = item.get("metric") if isinstance(item, dict) else None
        if not isinstance(metric, dict):
            continue
        delta = metric.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, int | float):
            continue
        weeks = _week_starts(item)
        skipped = sum(
            (later - earlier).days // 7 - 1 for earlier, later in pairwise(weeks)
        )
        if len(weeks) <= 2:
            basis = (
                "latest full week against the week before"
                if skipped == 0
                else "latest full week against an earlier week, not the week before"
            )
        else:
            basis = f"across {len(weeks) - 1} consecutive weekly moves the same way"
            if skipped:
                basis += ", with skipped weeks between"
        evidence.append(
            {
                "metric": metric_label(str(metric.get("name", ""))),
                "direction": "up" if delta > 0 else "down" if delta < 0 else "flat",
                "change_pct": round(float(delta) * 100, 1),
                "basis": basis,
                "week_of": weeks[-1].isoformat() if weeks else None,
                "compared_with_week_of": (
                    weeks[0].isoformat() if len(weeks) >= 2 else None
                ),
                "weeks_skipped_between": skipped,
            }
        )
    return evidence


def relative_decisions(
    payload: dict[str, Any] | None,
    *,
    today: date,
) -> dict[str, Any]:
    """What a peer may see: relative figures only.

    Built from an explicit list of fields. Evidence statements and metric
    values in the private documents are never copied.
    """
    if payload is None:
        return {
            "decisions": [],
            "count": 0,
            "status": "not_configured",
            "notes": ["Atlas has no goals configured, so it emits no Decisions."],
        }

    decisions: list[dict[str, Any]] = []
    for entry in payload.get("decisions", []):
        document = entry.get("document") if isinstance(entry, dict) else None
        if not isinstance(document, dict):
            continue
        try:
            first = datetime.fromisoformat(str(entry.get("first_emitted_at")))
            age_days: int | None = (today - first.date()).days
        except ValueError:
            age_days = None
        decisions.append(
            {
                "decision_id": document.get("decision_id"),
                "category": document.get("category"),
                "priority": document.get("priority"),
                "confidence": document.get("confidence"),
                "metric": metric_label(str(entry.get("metric", ""))),
                "assessment": entry.get("assessment"),
                "goal": entry.get("goal"),
                "summary": _humanize(str(document.get("summary", ""))),
                "rationale": _humanize(str(document.get("rationale", ""))),
                "recommendations": [
                    _humanize(str(item.get("statement", "")))
                    for item in document.get("recommendations", [])
                    if isinstance(item, dict)
                ],
                "evidence": _relative_evidence(document),
                "latest_week": entry.get("latest_period"),
                "first_emitted_on": first.date().isoformat()
                if age_days is not None
                else None,
                "days_since_first_emitted": age_days,
                "requires_approval": document.get("requires_approval", True),
            }
        )
    decisions.sort(
        key=lambda item: (
            _PRIORITY_ORDER.get(str(item["priority"]), 9),
            item["days_since_first_emitted"]
            if item["days_since_first_emitted"] is not None
            else 0,
        )
    )

    gaps = [
        {
            "goal": gap.get("goal"),
            "metric": metric_label(str(gap.get("metric", ""))),
            "reason": gap.get("reason"),
        }
        for gap in payload.get("gaps", [])
        if isinstance(gap, dict)
    ]
    return {
        "decisions": decisions,
        "count": len(decisions),
        "status": "ok",
        "generated_at": payload.get("generated_at"),
        "window_weeks": payload.get("window_weeks"),
        "unevaluated": gaps,
        "notes": [
            "Each Decision compares whole calendar weeks. A week with fewer "
            "reported nights than usual is left out, so the current week and "
            "a week with a missing night are not judged.",
            "Each evidence item names its own weeks (week_of and "
            "compared_with_week_of). They can differ between metrics, and "
            "when weeks_skipped_between is above zero the comparison is not "
            "with the week before: state the weeks, and do not combine "
            "changes that rest on different pairs of weeks.",
            "change_pct is the relative change in the metric itself. For a "
            "metric that is already a percent, it is not a change in points.",
            "A week-over-week move does not account for holidays, weather or "
            "events. A Decision says a metric moved against or with a goal, "
            "not why.",
            "unevaluated lists goal metrics Atlas could not judge for lack of data.",
        ],
    }
