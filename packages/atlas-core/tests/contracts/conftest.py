"""Fixtures for the contract test.

These live here rather than in tests/conftest.py so that the rest of the
suite does not depend on jsonschema being installed.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

CONTRACTS = Path(__file__).parent
KINDS = ("observation", "insight", "decision")


@pytest.fixture(scope="session")
def contracts_dir() -> Path:
    return CONTRACTS


@pytest.fixture(scope="session")
def pinned_schemas() -> dict[str, dict]:
    schemas = {}
    for kind in KINDS:
        path = CONTRACTS / f"{kind}.schema.json"
        assert path.exists(), f"no vendored schema for {kind}; see VERSION"
        schemas[kind] = json.loads(path.read_text(encoding="utf-8"))
    return schemas


@pytest.fixture(scope="session")
def validators(pinned_schemas: dict[str, dict]) -> dict[str, Draft202012Validator]:
    built = {}
    for kind, schema in pinned_schemas.items():
        Draft202012Validator.check_schema(schema)
        built[kind] = Draft202012Validator(schema, format_checker=FormatChecker())
    return built


@pytest.fixture(scope="session")
def pinned_versions(contracts_dir: Path) -> dict[str, str]:
    """Parse the VERSION note into a mapping of name to version."""
    versions = {}
    for line in (contracts_dir / "VERSION").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, version = line.partition(" ")
        versions[name] = version.strip()
    return versions
