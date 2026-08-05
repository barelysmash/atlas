"""The contract test.

Representative output the engine actually produces, validated against the
schemas vendored under this directory. Handwritten fixtures would prove the
fixtures are well formed and nothing about the engine, so every sample here
comes from the real emission path.

See standards/testing.md in JAM.
"""

import re
from datetime import UTC, datetime

import pytest
from atlas_core import OperationalRecord
from atlas_core.documents import (
    SCHEMA_VERSIONS,
    decision_document,
    insight_document,
    observation_document,
)
from atlas_core.reasoning_pipeline import ReasoningPipeline

BUILD = "0.4.1"
RUN_AT = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)

RECORDS = [
    ("tabc", "Fonda San Miguel", "2026-06", "sales", "wine_receipts", 50000.0),
    ("tabc", "Fonda San Miguel", "2026-05", "sales", "wine_receipts", 41200.0),
    ("tabc", "Casa Madero", "2026-06", "beverage", "wine_receipts", 8346.5),
    ("pos", "Fonda San Miguel", "2026-06", "sales", "beer_receipts", 25000.0),
]


def _emit() -> dict[str, list[dict]]:
    """Run the pipeline over several records and serialize everything."""
    emitted: dict[str, list[dict]] = {
        "observation": [],
        "insight": [],
        "decision": [],
    }
    pipeline = ReasoningPipeline()
    for source, entity, period, category, metric, value in RECORDS:
        record = OperationalRecord.create(
            source=source,
            entity=entity,
            period=period,
            category=category,
            metric=metric,
            value=value,
        )
        result = pipeline.run(record)
        emitted["observation"] += [
            observation_document(o, source_version=BUILD) for o in result.observations
        ]
        emitted["insight"] += [
            insight_document(i, source_version=BUILD) for i in result.insights
        ]
        emitted["decision"] += [
            decision_document(d, source_version=BUILD) for d in result.decisions
        ]
    return emitted


@pytest.fixture(scope="session")
def emitted() -> dict[str, list[dict]]:
    return _emit()


def _describe(kind: str, document: dict, errors: list) -> str:
    identifier = document.get(f"{kind}_id", "<unidentified>")
    lines = [f"{kind} {identifier} does not satisfy the contract:"]
    for error in errors:
        location = "/".join(str(p) for p in error.path) or "<root>"
        lines.append(f"  {location}: {error.message}")
    return "\n".join(lines)


@pytest.mark.parametrize("kind", ["observation", "insight", "decision"])
def test_emitted_documents_satisfy_the_contract(kind, emitted, validators):
    documents = emitted[kind]
    assert documents, f"the pipeline emitted no {kind} to validate"
    for document in documents:
        errors = sorted(validators[kind].iter_errors(document), key=lambda e: list(e.path))
        assert not errors, _describe(kind, document, errors)


@pytest.mark.parametrize("kind", ["observation", "insight", "decision"])
def test_declared_schema_version_matches_the_pinned_schema(kind, pinned_schemas):
    declared = SCHEMA_VERSIONS[kind]
    schema_id = pinned_schemas[kind].get("$id", "")
    match = re.search(rf"/{re.escape(kind)}/(\d+\.\d+\.\d+)/", schema_id)
    assert match, f"the pinned {kind} schema declares no version in its $id"
    assert declared == match.group(1), (
        f"documents declare {kind} {declared} but the pinned schema is "
        f"{match.group(1)}; refresh SCHEMA_VERSIONS alongside the pin"
    )


@pytest.mark.parametrize("kind", ["observation", "insight", "decision"])
def test_version_note_matches_the_pinned_schema(kind, pinned_versions, pinned_schemas):
    schema_id = pinned_schemas[kind].get("$id", "")
    match = re.search(rf"/{re.escape(kind)}/(\d+\.\d+\.\d+)/", schema_id)
    assert match
    assert pinned_versions.get(kind) == match.group(1), (
        f"VERSION records {kind} {pinned_versions.get(kind)} but the pinned "
        f"schema is {match.group(1)}"
    )


def test_the_pin_records_which_jam_release_it_came_from(pinned_versions):
    release = pinned_versions.get("jam", "")
    assert re.match(r"^v\d+\.\d+\.\d+$", release), (
        "VERSION must record the JAM release the schemas came from, as vX.Y.Z"
    )


def test_every_decision_cites_an_observation_that_was_emitted(emitted):
    identifiers = {o["observation_id"] for o in emitted["observation"]}
    for decision in emitted["decision"]:
        for item in decision["evidence"]:
            assert item["observation_id"] in identifiers, (
                f"{decision['decision_id']} cites {item['observation_id']}, "
                "which the pipeline did not emit"
            )


def test_every_decision_rests_on_an_insight_that_was_emitted(emitted):
    identifiers = {i["insight_id"] for i in emitted["insight"]}
    for decision in emitted["decision"]:
        for insight_id in decision.get("derived_from", []):
            assert insight_id in identifiers, (
                f"{decision['decision_id']} rests on {insight_id}, which the "
                "pipeline did not emit"
            )


def test_a_cited_metric_matches_the_observation_it_names(emitted):
    by_id = {o["observation_id"]: o for o in emitted["observation"]}
    for kind in ("insight", "decision"):
        for document in emitted[kind]:
            for item in document["evidence"]:
                metric = item.get("metric")
                if metric is None:
                    continue
                source = by_id[item["observation_id"]]
                match = next(
                    (m for m in source["metrics"] if m["name"] == metric["name"]), None
                )
                assert match is not None, (
                    f"cites metric {metric['name']} of "
                    f"{item['observation_id']}, which has no such metric"
                )
                assert metric == match, (
                    f"the copy of {metric['name']} in this {kind} disagrees "
                    f"with {item['observation_id']}"
                )
