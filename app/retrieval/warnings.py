"""A small order-preserving, de-duplicating warning collector.

A single :class:`WarningsCollector` instance is created in :func:`retrieve` and
threaded by reference through the query builder, the parser, and the client-side
filters. This lets every stage append human-readable warnings (parse failures,
truncation, client-side filtering) without each function having to return and
re-thread a list. The same message added twice is recorded once.
"""

from __future__ import annotations


class WarningsCollector:
    """Accumulates unique warning messages in insertion order."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._items: list[str] = []

    def add(self, message: str) -> None:
        """Record ``message`` unless an identical one was already added."""
        if message not in self._seen:
            self._seen.add(message)
            self._items.append(message)

    def list(self) -> list[str]:
        """Return a copy of the collected warnings in insertion order."""
        return list(self._items)
