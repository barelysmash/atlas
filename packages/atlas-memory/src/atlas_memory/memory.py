from typing import Any


class MemoryStore:
    """In-memory store for Atlas knowledge objects."""

    def __init__(self) -> None:
        self._items: list[Any] = []

    def add(self, item: Any) -> Any:
        self._items.append(item)
        return item

    def all(self) -> list[Any]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)