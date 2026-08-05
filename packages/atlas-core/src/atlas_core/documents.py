"""Serialization of reasoning objects into JAM contract documents.

The reasoning types carry what the engine reasoned about. A contract document
also carries who emitted it, at which build, and against which version of the
specification. That metadata belongs to the emission boundary rather than to
the reasoning, which is why it is supplied here and not stored on the objects.

Every function returns a plain dictionary with absent optional fields omitted
rather than set to null, because the schemas forbid additional properties and
treat null as a value.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from atlas_core.decision import Decision
from atlas_core.evidence_item import EvidenceItem
from atlas_core.insight import Insight
from atlas_core.metric import Metric
from atlas_core.observation import Observation
from atlas_core.recommendation import Recommendation

# Atlas is always the source. JARVIS is never a source; it synthesises.
SOURCE = "atlas"

# The specification version each document declares. These must agree with the
# vendored schemas under tests/contracts/, which the contract test asserts.
SCHEMA_VERSIONS = {
    "observation": "1.0.0",
    "insight": "1.0.0",
    "decision": "1.1.0",
}

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

__all__ = [
    "SCHEMA_VERSIONS",
    "SEMVER",
    "SOURCE",
    "decision_document",
    "insight_document",
    "observation_document",
]


def _check_source_version(source_version: str) -> str:
    """The schemas require a bare semver, with no pre-release identifier.

    Raised here rather than discovered at validation, because the engine build
    string is the kind of thing that is wrong once and then wrong everywhere.
    """
    if not SEMVER.match(source_version):
        raise ValueError(
            f"source_version {source_version!r} is not a bare semver; the "
            "contract requires the form 1.2.3, with no pre-release suffix"
        )
    return source_version


def _timestamp(moment: datetime) -> str:
    """RFC 3339 in UTC with a Z suffix, as every contract timestamp requires.

    Serialized the way standards/python.md specifies, which preserves
    sub-second precision where the source has it.
    """
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _prune(document: dict[str, Any]) -> dict[str, Any]:
    """Drop absent optional fields. The schemas forbid unknown properties."""
    return {key: value for key, value in document.items() if value is not None}


def _metric_document(metric: Metric) -> dict[str, Any]:
    return _prune(
        {
            "name": metric.name,
            "value": metric.value,
            "unit": metric.unit,
            "delta": metric.delta,
            "period": metric.period,
        }
    )


def _evidence_document(item: EvidenceItem) -> dict[str, Any]:
    return _prune(
        {
            "observation_id": item.observation_id,
            "statement": item.statement,
            "metric": _metric_document(item.metric) if item.metric else None,
            "source_ref": item.source_ref,
        }
    )


def _recommendation_document(recommendation: Recommendation) -> dict[str, Any]:
    return _prune(
        {
            "recommendation_id": recommendation.recommendation_id,
            "statement": recommendation.statement,
            "action_type": recommendation.action_type,
            "parameters": recommendation.parameters,
            "reversible": recommendation.reversible,
        }
    )


def observation_document(
    observation: Observation, *, source_version: str
) -> dict[str, Any]:
    """Serialize an Observation into an observation contract document."""
    return _prune(
        {
            "schema_version": SCHEMA_VERSIONS["observation"],
            "observation_id": observation.observation_id,
            "source": SOURCE,
            "source_version": _check_source_version(source_version),
            "domain": observation.domain,
            "subject": observation.subject,
            "summary": observation.summary,
            "metrics": [_metric_document(m) for m in observation.metrics],
            "source_ref": observation.source_ref,
            "observed_at": _timestamp(observation.observed_at),
        }
    )


def insight_document(insight: Insight, *, source_version: str) -> dict[str, Any]:
    """Serialize an Insight into an insight contract document."""
    return _prune(
        {
            "schema_version": SCHEMA_VERSIONS["insight"],
            "insight_id": insight.insight_id,
            "source": SOURCE,
            "source_version": _check_source_version(source_version),
            "domain": insight.domain,
            "statement": insight.statement,
            "confidence": insight.confidence,
            "method": insight.method,
            "evidence": [_evidence_document(e) for e in insight.evidence],
            "created_at": _timestamp(insight.created_at),
        }
    )


def decision_document(decision: Decision, *, source_version: str) -> dict[str, Any]:
    """Serialize a Decision into a decision contract document."""
    return _prune(
        {
            "schema_version": SCHEMA_VERSIONS["decision"],
            "decision_id": decision.decision_id,
            "source": SOURCE,
            "source_version": _check_source_version(source_version),
            "domain": decision.domain,
            "category": decision.category,
            "priority": decision.priority,
            "confidence": decision.confidence,
            "summary": decision.summary,
            "rationale": decision.rationale,
            "evidence": [_evidence_document(e) for e in decision.evidence],
            "derived_from": list(decision.derived_from) or None,
            "recommendations": [
                _recommendation_document(r) for r in decision.recommendations
            ],
            "requires_approval": decision.requires_approval,
            "created_at": _timestamp(decision.created_at),
        }
    )
