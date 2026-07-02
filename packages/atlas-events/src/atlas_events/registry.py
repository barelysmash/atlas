from dataclasses import dataclass


@dataclass(frozen=True)
class EventDefinition:
    """Registered Atlas event type."""

    type: str
    description: str = ""


class EventRegistry:
    """Registry for Atlas event definitions."""

    def __init__(self) -> None:
        self._events: dict[str, EventDefinition] = {}

    def register(self, event_type: str, description: str = "") -> EventDefinition:
        if not event_type:
            raise ValueError("event_type is required")

        if event_type in self._events:
            raise ValueError(f"event_type already registered: {event_type}")

        definition = EventDefinition(type=event_type, description=description)
        self._events[event_type] = definition
        return definition

    def get(self, event_type: str) -> EventDefinition:
        if event_type not in self._events:
            raise KeyError(f"event_type not registered: {event_type}")

        return self._events[event_type]

    def list(self) -> list[EventDefinition]:
        return list(self._events.values())