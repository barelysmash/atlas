import pytest

from atlas_events import EventRegistry


def test_register_event_type():
    registry = EventRegistry()

    definition = registry.register(
        "TABC_REFRESHED",
        "TABC data refresh completed.",
    )

    assert definition.type == "TABC_REFRESHED"
    assert definition.description == "TABC data refresh completed."


def test_duplicate_event_registration_fails():
    registry = EventRegistry()

    registry.register("TABC_REFRESHED")

    with pytest.raises(ValueError, match="already registered"):
        registry.register("TABC_REFRESHED")


def test_get_registered_event():
    registry = EventRegistry()

    registry.register("POS_IMPORTED")

    definition = registry.get("POS_IMPORTED")

    assert definition.type == "POS_IMPORTED"


def test_get_unknown_event_fails():
    registry = EventRegistry()

    with pytest.raises(KeyError, match="not registered"):
        registry.get("UNKNOWN_EVENT")


def test_list_registered_events():
    registry = EventRegistry()

    registry.register("TABC_REFRESHED")
    registry.register("POS_IMPORTED")

    assert [event.type for event in registry.list()] == [
        "TABC_REFRESHED",
        "POS_IMPORTED",
    ]