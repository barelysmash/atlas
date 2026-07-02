from atlas_events import Event


def test_event_create():
    event = Event.create("TABC_REFRESHED", {"rows": 120})

    assert event.type == "TABC_REFRESHED"
    assert event.payload["rows"] == 120
    assert event.id is not None
    assert event.timestamp is not None


def test_event_requires_type():
    try:
        Event.create("", {})
    except ValueError as error:
        assert "event_type is required" in str(error)
    else:
        raise AssertionError("Expected ValueError")
